import base64
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from rotary import actions, apps, integrations, obs, winapi
from rotary.app import hand_at_face, pick_hand
from rotary.gestures import extract_features
from tests.synth import make_hand


# ------------------------------------------------------------------ Steam
def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _acf(appid, name, last, flags=4):
    return f'''"AppState"
{{
\t"appid"\t\t"{appid}"
\t"name"\t\t"{name}"
\t"StateFlags"\t\t"{flags}"
\t"installdir"\t\t"{name}"
\t"LastPlayed"\t\t"{last}"
}}'''


def test_parse_vdf_nested_and_escapes():
    d = apps.parse_vdf('"a"\n{\n\t"b"\t"1"\n\t"c"\n\t{\n\t\t"path"\t"C:\\\\Games \\"x\\""\n\t}\n}')
    assert d == {"a": {"b": "1", "c": {"path": 'C:\\Games "x"'}}}


def test_steam_library_reads_all_libraries_newest_first(tmp_path):
    root, second = tmp_path / "Steam", tmp_path / "Lib2"
    _write(root / "steamapps" / "libraryfolders.vdf",
           f'"libraryfolders"\n{{\n"0"\n{{\n"path" "{str(root).replace(chr(92), chr(92) * 2)}"\n}}\n'
           f'"1"\n{{\n"path" "{str(second).replace(chr(92), chr(92) * 2)}"\n}}\n}}')
    _write(root / "steamapps" / "appmanifest_10.acf", _acf(10, "Old Game™", 100))
    _write(root / "steamapps" / "appmanifest_228980.acf", _acf(228980, "Steamworks Common Redistributables", 999))
    _write(root / "steamapps" / "appmanifest_30.acf", _acf(30, "Half Downloaded", 500, flags=1026))
    _write(second / "steamapps" / "appmanifest_20.acf", _acf(20, "New Game", 300))
    icon = root / "appcache" / "librarycache" / "20" / ("a" * 40 + ".jpg")
    _write(icon, "x")
    games = apps.steam_library(str(root))
    assert [g.name for g in games] == ["New Game", "Old Game™"]
    assert games[0].icon == str(icon)


# ------------------------------------------------------------------ VS Code recents
def test_vscode_recents_prefers_history_then_recent_workspaces(tmp_path):
    storage = tmp_path / "Code" / "User" / "globalStorage"
    storage.mkdir(parents=True)
    a, b, c = (tmp_path / n for n in ("alpha", "beta", "gamma"))
    for d in (a, b, c):
        d.mkdir()
    con = sqlite3.connect(storage / "state.vscdb")
    con.execute("CREATE TABLE ItemTable (key TEXT, value TEXT)")
    con.execute("INSERT INTO ItemTable VALUES (?, ?)", ("history.recentlyOpenedPathsList",
                                                       json.dumps({"entries": [{"folderUri": c.as_uri()},
                                                                               {"fileUri": "file:///x.txt"},
                                                                               {"folderUri": "vscode-remote://wsl/x"}]})))
    con.commit()
    con.close()
    ws = storage.parent / "workspaceStorage"
    for i, folder in enumerate((a, b)):
        d = ws / f"h{i}"
        d.mkdir(parents=True)
        (d / "workspace.json").write_text(json.dumps({"folder": folder.as_uri()}), encoding="utf-8")
        t = time.time() - (100 if folder == a else 10)        # beta used more recently
        os.utime(d / "workspace.json", (t, t))
    got = [os.path.basename(p) for p, _ in integrations.vscode_recents(storage)]
    assert got == ["gamma", "beta", "alpha"]


def test_uri_to_path_windows_drive():
    p = integrations.uri_to_path("file:///c%3A/Users/me/My%20Project")
    assert p.lower().replace("/", "\\").endswith(r"users\me\my project")
    assert integrations.uri_to_path("vscode-remote://ssh/x") == ""


# ------------------------------------------------------------------ catalogue & matching
@pytest.mark.parametrize("name,want,ok", [
    ("OBS Studio", "OBS Studio", True), ("OBS Studio (64bit)", "OBS Studio", True),
    ("Blender 4.2", "Blender", True), ("Visual Studio 2022", "Visual Studio", True),
    ("EA Sports FC 25", "EA", False), ("Steam Support Center", "Steam", False), ("XBOX", "Xbox", True),
])
def test_start_menu_name_matching(name, want, ok):
    assert apps.name_matches(name, want) is ok


def test_catalogue_is_well_formed():
    ids = [s.id for s in integrations.CATALOG]
    assert len(ids) == len(set(ids))
    for s in integrations.CATALOG:
        assert s.category in integrations.CATEGORIES
        assert len(s.glyph) == 4 and int(s.glyph, 16)
        assert s.actions is not None


def test_quicknav_is_capped_and_items_are_valid(monkeypatch):
    spec = integrations.BY_ID["steam"]
    a = integrations.App(spec, target="steam.exe", exe="", installed=True)
    monkeypatch.setattr(integrations, "get", lambda app_id: a)
    many = [integrations.item(f"Game {i}", "Play", "E7FC", "#000000", integrations.open_uri(f"steam://rungameid/{i}"))
            for i in range(40)]
    monkeypatch.setitem(integrations._dynamic, "steam", (time.time(), many))
    qn = integrations.quicknav("steam")
    assert len(qn) == integrations.QUICKNAV_MAX
    assert qn[0]["name"] == "Open Steam"
    assert all(actions.item_from(d) is not None for d in qn)
    q = integrations.quicknav_item("steam")
    assert q["action"] == {"type": "quicknav", "app": "steam"}


def test_every_builtin_action_list_builds():
    for s in integrations.CATALOG:
        a = integrations.App(s, target="x.exe", exe="", installed=True)
        for d in s.actions(a):
            assert actions.item_from(d) is not None, (s.id, d)
            if d["action"]["type"] in ("keys", "window_keys"):
                for k in winapi.parse_keys(d["action"]["keys"]):
                    winapi.vk_code(k)            # every shortcut is pressable


# ------------------------------------------------------------------ keys, config, python
def test_parse_keys_symbols_and_aliases():
    assert winapi.parse_keys("win+.") == ["win", "."]
    assert winapi.parse_keys("Ctrl+Shift+Esc") == ["ctrl", "shift", "esc"]
    assert winapi.parse_keys("ctrl++") == ["ctrl", "="]
    assert winapi.parse_keys(["Meta", "D"]) == ["win", "d"]
    assert winapi.vk_code(".") == 0xBE and winapi.vk_code("f12") == 0x7B


def test_broken_config_is_backed_up_not_lost(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ this is not json", encoding="utf-8")
    cfg = actions.load_config(p)
    assert cfg["items"]
    backups = list(tmp_path.glob("config.broken-*.json"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{ this is not json"


def test_editor_only_keys_are_not_saved(tmp_path):
    p = tmp_path / "config.json"
    actions.save_config({"items": [{"name": "x", "_auto_name": "x", "action": {"type": "keys", "_tmp": 1}}]}, p)
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved == {"items": [{"name": "x", "action": {"type": "keys"}}]}


def test_python_command_bundled_runs_code(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "SCRIPTS", tmp_path)
    args, err = actions.python_command("print('hi')", {"general": {"python": "bundled"}})
    assert Path(args[-1]).read_text(encoding="utf-8") == "print('hi')"
    actions._run_checked(args, "Python", err_file=err)          # exits 0 → no exception
    args, err = actions.python_command("raise ValueError('boom')", {"general": {"python": "bundled"}})
    with pytest.raises(RuntimeError, match="boom"):
        actions._run_checked(args, "Python", err_file=err)


# ------------------------------------------------------------------ OBS & secrets
def test_obs_auth_matches_protocol_spec():
    pw, salt, challenge = "supersecretpassword", "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI=", \
        "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="
    secret = base64.b64encode(hashlib.sha256((pw + salt).encode()).digest()).decode()
    expected = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
    assert obs.auth_string(pw, salt, challenge) == expected


def test_password_encryption_roundtrip(monkeypatch):
    if not winapi.WIN:     # keep the test away from the real Keychain / keyring
        monkeypatch.setattr(winapi.posix, "MAC", False)
        monkeypatch.setattr(winapi.posix.shutil, "which", lambda name: None)
    token = winapi.protect("hunter2 ✓")
    assert token and "hunter2" not in token
    assert winapi.unprotect(token) == "hunter2 ✓"
    cfg = {"integrations": {"obs": {"host": "127.0.0.1", "port": 4456, "password_dpapi": token}}}
    assert obs.settings_from(cfg) == ("127.0.0.1", 4456, "hunter2 ✓")


def test_obs_unreachable_without_exe_explains(monkeypatch):
    monkeypatch.setattr(winapi, "is_running", lambda name: False)
    cfg = {"integrations": {"obs": {"host": "127.0.0.1", "port": 1}}}
    with pytest.raises(obs.OBSError):
        obs.run({"type": "obs", "request": "ToggleRecord"}, cfg, obs_exe="")


# ------------------------------------------------------------------ hand choice & the face filter
FACE = (0.4, 0.15, 0.6, 0.45)        # x0, y0, x1, y1 (normalised)


def test_chin_resting_hand_is_at_face():
    assert hand_at_face((0.42, 0.40, 0.58, 0.62), [FACE])          # under the chin
    assert hand_at_face((0.45, 0.20, 0.55, 0.40), [FACE])          # over the face
    assert not hand_at_face((0.70, 0.20, 0.88, 0.45), [FACE])      # raised beside the head
    assert not hand_at_face((0.42, 0.40, 0.58, 0.62), [])          # no face seen


def test_pick_hand_prefers_the_presented_hand():
    resting = extract_features(make_hand(flex=1.0, center=(0.5, 0.55), size=0.2))
    raised = extract_features(make_hand(center=(0.8, 0.35), size=0.2))
    i, _ = pick_hand([resting, raised], [FACE], None)
    assert i == 1


def test_old_terminal_fallback_is_removed_from_other_apps(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"items": [
        {"name": "Steam", "action": {"type": "app", "target": r"C:\Start Menu\Steam.lnk", "fallback": "cmd.exe"}},
        {"name": "Terminal", "action": {"type": "app", "target": "wt.exe", "fallback": "cmd.exe"}}]}), encoding="utf-8")
    items = actions.load_config(p)["items"]
    assert "fallback" not in items[0]["action"]
    assert items[1]["action"]["fallback"] == "cmd.exe"

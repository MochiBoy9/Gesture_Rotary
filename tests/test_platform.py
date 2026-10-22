"""The macOS / Linux side: the icon font, opening things, app discovery, start at login, shortcuts."""
import plistlib
import re
import sys
from pathlib import Path

import pytest

from rotary import ROOT, actions, apps, integrations, posix, system, winapi

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="macOS / Linux behaviour")


# ------------------------------------------------------------------ the bundled icon font
def _glyphs_in_source() -> set[int]:
    found: set[int] = set()
    for p in (ROOT / "rotary").rglob("*.py"):
        t = p.read_text(encoding="utf-8")
        found |= {int(m, 16) for m in re.findall(r'"([EF][0-9A-Fa-f]{3})"', t)}
        found |= {int(m, 16) for m in re.findall(r"\\u([EF][0-9A-Fa-f]{3})", t)}
        found |= {ord(c) for c in t if 0xE000 <= ord(c) <= 0xF8FF}
    return found


def test_icon_font_covers_every_glyph_the_app_uses():
    from fontTools.ttLib import TTFont
    font = TTFont(ROOT / "assets" / "rotary-icons.ttf")
    have = set(font.getBestCmap())
    missing = sorted(f"{cp:04X}" for cp in _glyphs_in_source() - have)
    assert not missing, f"add these to tools/make_icon_font.py and rebuild the font: {missing}"
    assert font["name"].getDebugName(1) == "Rotary Icons"


def test_icon_font_loads_in_qt():
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    fid = QFontDatabase.addApplicationFont(str(ROOT / "assets" / "rotary-icons.ttf"))
    assert fid >= 0 and "Rotary Icons" in QFontDatabase.applicationFontFamilies(fid)


# ------------------------------------------------------------------ default items & shortcuts
@pytest.mark.parametrize("items", [actions.WINDOWS_ITEMS, actions.MAC_ITEMS, actions.LINUX_ITEMS])
def test_every_platforms_default_items_build(items):
    built = actions.build_items({"items": items})
    assert len(built) == len(items) == 8
    for it in built:
        if it.action["type"] == "keys":
            for k in winapi.parse_keys(it.action["keys"]):
                winapi.vk_code(k)


def test_mac_shortcuts_use_command(monkeypatch):
    monkeypatch.setattr(integrations, "MAC", True)
    assert integrations.shortcut("ctrl+shift+m") == "cmd+shift+m"
    assert integrations.shortcut("alt+a", "cmd+shift+a") == "cmd+shift+a"
    assert integrations.key_label("cmd+shift+m") == "⇧⌘M"
    assert integrations.key_label("ctrl+cmd+space") == "⌃⌘Space"
    monkeypatch.setattr(integrations, "MAC", False)
    assert integrations.shortcut("ctrl+shift+m") == "ctrl+shift+m"
    assert integrations.key_label("ctrl+shift+m") == "Ctrl+Shift+M"


def test_catalogue_is_for_this_system_only():
    ids = {s.id for s in integrations.CATALOG}
    assert "media_keys" in ids and "steam" in ids
    if sys.platform == "win32":
        assert "gamebar" in ids and "macos" not in ids
    elif sys.platform == "darwin":
        assert "macos" in ids and "gamebar" not in ids and "windows" not in ids
    else:
        assert "linux" in ids and "gamebar" not in ids and "apple_music" not in ids
    assert all(s.category in integrations.CATEGORIES for s in integrations.CATALOG)


def test_mac_and_linux_names_are_searched(monkeypatch):
    spec = integrations.BY_ID["obs"]
    monkeypatch.setattr(integrations, "MAC", True)
    monkeypatch.setattr(integrations, "LINUX", False)
    assert "OBS" in spec.names and "OBS Studio" in spec.names


def test_window_keys_carry_the_mac_bundle(monkeypatch):
    monkeypatch.setattr(integrations, "MAC", True)
    a = integrations.App(integrations.BY_ID["discord"], "/Applications/Discord.app", "/Applications/Discord.app", True)
    act = a.keys("cmd+shift+m")
    assert act["bundle"] == "/Applications/Discord.app" and act["process"] == "Discord.exe"


# ------------------------------------------------------------------ Linux .desktop files & macOS bundles
def test_desktop_entry_and_exec(tmp_path):
    f = tmp_path / "code.desktop"
    f.write_text("[Desktop Entry]\nName=Visual Studio Code\nExec=/usr/share/code/code --unity-launch %F\n"
                 "Type=Application\n[Desktop Action new-empty-window]\nName=New Empty Window\nExec=code -n\n")
    e = posix.desktop_entry(str(f))
    assert e["Name"] == "Visual Studio Code" and e["Exec"].endswith("%F")
    assert posix.desktop_exec(e) == ["/usr/share/code/code", "--unity-launch"]
    assert posix.desktop_exec(e, '"/home/me/my project"') == ["/usr/share/code/code", "--unity-launch",
                                                               "/home/me/my project"]
    assert posix.desktop_exec({"Exec": "steam %U"}, "--x") == ["steam", "--x"]


def test_linux_apps_menu_is_scanned(tmp_path, monkeypatch):
    apps_dir = tmp_path / "share" / "applications"
    apps_dir.mkdir(parents=True)
    (apps_dir / "steam.desktop").write_text("[Desktop Entry]\nName=Steam\nExec=steam %U\nType=Application\n")
    (apps_dir / "hidden.desktop").write_text("[Desktop Entry]\nName=Hidden\nExec=x\nNoDisplay=true\n")
    (apps_dir / "link.desktop").write_text("[Desktop Entry]\nName=Docs\nType=Link\nURL=https://x\n")
    monkeypatch.setattr(apps, "linux_app_dirs", lambda: [apps_dir])
    found = apps._load_linux_apps()
    assert [(a.name, a.app_id) for a in found] == [("Steam", "steam.desktop")]
    assert found[0].launch_target == str(apps_dir / "steam.desktop")


def test_mac_applications_are_scanned(tmp_path, monkeypatch):
    for rel in ("Discord.app", "Adobe Photoshop 2025/Adobe Photoshop 2025.app", "Utilities/Terminal.app"):
        (tmp_path / rel / "Contents").mkdir(parents=True)
    (tmp_path / "readme.txt").write_text("x")
    monkeypatch.setattr(apps, "MAC_APP_DIRS", [str(tmp_path)])
    names = sorted(a.name for a in apps._load_mac_apps())
    assert names == ["Adobe Photoshop 2025", "Discord", "Terminal"]
    assert apps.name_matches("Adobe Photoshop 2025", "Adobe Photoshop")


def test_bundle_executable(tmp_path):
    app = tmp_path / "Thing.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "thing").write_text("")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleExecutable": "thing"}, f)
    assert posix.bundle_executable(str(app)) == str(app / "Contents" / "MacOS" / "thing")
    assert posix.bundle_executable(str(tmp_path)) == ""


# ------------------------------------------------------------------ start at login
@pytest.mark.parametrize("mac", [True, False])
def test_login_item_roundtrip(tmp_path, monkeypatch, mac):
    monkeypatch.setattr(posix, "MAC", mac)
    monkeypatch.setattr(posix, "LAUNCH_AGENT", tmp_path / "LaunchAgents" / "app.gesturerotary.plist")
    monkeypatch.setattr(posix, "AUTOSTART", tmp_path / "autostart" / "gesture-rotary.desktop")
    assert posix.login_item_command() is None
    cmd = ["/Applications/Gesture Rotary.app/Contents/MacOS/Gesture Rotary", "--minimized"]
    posix.set_login_item(cmd)
    assert posix.login_item_command() == cmd
    posix.set_login_item(None)
    assert posix.login_item_command() is None


@posix_only
def test_running_from_source_has_nothing_to_uninstall():
    assert system.install_folder() is None
    assert system.login_command()[1:] == ["-m", "rotary", "--minimized"]


# ------------------------------------------------------------------ processes, secrets, battery
@posix_only
def test_process_list_includes_us():
    procs = posix.processes()
    assert procs and all(isinstance(k, int) for k in procs)
    assert posix._norm("C:\\Apps\\Discord.exe") == "discord"
    assert posix._norm("/Applications/OBS.app/Contents/MacOS/OBS") == "obs"


def test_secret_fallback_roundtrip(monkeypatch):
    monkeypatch.setattr(posix, "MAC", False)
    monkeypatch.setattr(posix.shutil, "which", lambda name: None)
    token = posix.protect("s3cret ✓", "test")
    assert "s3cret" not in token and posix.unprotect(token) == "s3cret ✓"


def test_battery_reading_is_sane():
    if sys.platform == "win32":
        pytest.skip("Windows reads GetSystemPowerStatus")
    b = posix.battery()
    assert b is None or (0 <= b[0] <= 100 and isinstance(b[1], bool))


def test_playerctl_line_parses():
    from rotary.live import PlayerctlMedia
    line = "spotify\tPlaying\tMidnight City\tM83\t83000000\t243000000\thttps://i.scdn.co/x\n"
    d = PlayerctlMedia.parse(line)
    assert d["title"] == "Midnight City" and d["status"] == "Playing"
    assert PlayerctlMedia._seconds(d["mpris:length"]) == 243.0
    assert PlayerctlMedia.parse("No players found") is None


def test_terminal_command_keeps_the_window_open(monkeypatch):
    monkeypatch.setattr(posix, "MAC", True)
    cmd = posix.terminal_command('echo "hi"')
    assert cmd[0] == "osascript" and 'echo \\"hi\\"' in cmd[2]
    monkeypatch.setattr(posix, "MAC", False)
    monkeypatch.setattr(posix.shutil, "which", lambda name: "/usr/bin/" + name if name == "xterm" else None)
    assert posix.terminal_command("ls") == ["xterm", "-e", "sh", "-c", 'ls; exec "${SHELL:-sh}"']


def test_data_dir_is_per_platform(monkeypatch):
    import rotary
    for attr, expected in (("WIN", "GestureRotary"), ("MAC", "Application Support"), ("LINUX", ".config")):
        for a in ("WIN", "MAC"):
            monkeypatch.setattr(rotary, a, a == attr)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert expected in str(rotary._user_data_dir())
    assert Path(rotary._user_data_dir()).name == "GestureRotary"

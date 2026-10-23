"""Safety nets: API keys never sent in the clear, updates only from GitHub, settings only this user can read,
slow lookups kept off the UI thread, and the glass not worked out again for a still desktop."""
import os
import sys
import threading
import time

import numpy as np
import pytest

from rotary import actions, assist, integrations, obs, update
from rotary.ui import liquid


# ------------------------------------------------------------------ screen assist
@pytest.mark.parametrize("url, local", [
    ("http://localhost:1234/v1", True), ("http://127.0.0.1:11434", True), ("http://192.168.1.20:1234/v1", True),
    ("http://[::1]:8080", True), ("http://studio.local:1234", True),
    ("http://api.example.com/v1", False), ("https://api.openai.com/v1", False), ("http://8.8.8.8", False)])
def test_local_addresses(url, local):
    assert assist.is_local(url) is local


def test_api_keys_go_only_over_https_unless_its_this_computer():
    p = assist.BY_ID["openai"]
    assist.check_address("https://api.openai.com/v1/models", {"Authorization": "Bearer k"}, p)
    assist.check_address("http://localhost:1234/v1/models", {"Authorization": "Bearer k"}, p)
    assist.check_address("http://api.example.com/v1/models", {}, p)             # no key, nothing to leak
    with pytest.raises(assist.AssistError, match="https"):
        assist.check_address("http://api.example.com/v1/models", {"Authorization": "Bearer k"}, p)
    with pytest.raises(assist.AssistError, match="https"):
        assist.check_address("http://evil.example/v1", {"x-api-key": "k"}, assist.BY_ID["anthropic"])
    with pytest.raises(assist.AssistError):
        assist.check_address("file:///etc/passwd", {}, p)


def test_a_key_is_refused_before_any_request_to_a_plain_http_server(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("nothing should be sent")
    monkeypatch.setattr(assist.urllib.request, "urlopen", no_network)
    p = assist.BY_ID["openai"]
    with pytest.raises(assist.AssistError, match="https"):
        assist.post("http://api.example.com/v1/chat/completions", {"Authorization": "Bearer sk"}, {}, p)


def test_the_tls_context_is_made_once():
    assert assist._ssl_context() is assist._ssl_context()


def test_odd_model_lists_dont_crash(monkeypatch):
    monkeypatch.setattr(assist, "post", lambda *a, **k: {"data": [
        "not a model", {"id": "gpt-x", "created": "yesterday"}, {"id": "gpt-y", "created": 5}, {"created": 9}]})
    cfg = {"assist": {"provider": "openai", "keys": {}}}
    assert [m for m, _n in assist.list_models(cfg, assist.BY_ID["openai"])] == ["gpt-y", "gpt-x"]
    monkeypatch.setattr(assist, "post", lambda *a, **k: {"data": [{"display_name": "no id"}, {"id": "claude-a"}]})
    assert assist.list_models(cfg, assist.BY_ID["anthropic"]) == [("claude-a", "claude-a")]


# ------------------------------------------------------------------ updates
@pytest.mark.parametrize("url, ok", [
    ("https://github.com/MochiBoy9/Gesture_Rotary/releases/download/v2/x.zip", True),
    ("https://objects.githubusercontent.com/abc", True),
    ("https://release-assets.githubusercontent.com/abc", True),
    ("https://evilgithubusercontent.com/abc", False),
    ("http://github.com/x", False), ("https://github.com.evil.example/x", False), ("https://example.com/x", False),
    ("file:///tmp/x", False)])
def test_updates_come_only_from_github_over_https(url, ok):
    assert update.trusted(url) is ok


def test_an_update_from_elsewhere_is_refused(monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("nothing should be downloaded")
    monkeypatch.setattr(update.urllib.request, "urlopen", no_network)
    with pytest.raises(update.UpdateError, match="Refused"):
        update._get("https://example.com/GestureRotary.zip", 5)


def test_a_redirect_away_from_github_is_refused(monkeypatch):
    class Resp:
        closed = False

        def geturl(self):
            return "https://example.com/elsewhere"

        def close(self):
            self.closed = True
    r = Resp()
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: r)
    with pytest.raises(update.UpdateError, match="example.com"):
        update._get("https://github.com/x", 5)
    assert r.closed


def test_windows_script_keeps_percent_signs_and_accents(tmp_path):
    folder = tmp_path / "Zoë 100%" / "Gesture Rotary"
    staged = update.Staged("9.0.0", "swap", update.staging_path(folder), folder)
    script = update.windows_script(staged, 1, folder / "Gesture Rotary.exe", ["--show"])
    assert "chcp 65001" in script.splitlines()[1]
    assert "100%%" in script and "100% " not in script.replace("100%%", "")


# ------------------------------------------------------------------ settings and actions
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_settings_file_is_only_readable_by_this_user(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    actions.save_config({"assist": {"keys": {"gemini": "c2VjcmV0"}}}, p)
    assert (p.stat().st_mode & 0o777) == 0o600
    assert actions.load_config(p)["assist"]["keys"]["gemini"] == "c2VjcmV0"


def test_a_chatty_long_running_command_doesnt_hang():
    # Far more than a pipe holds: with stderr on a pipe nobody reads, the script would block forever.
    code = "import sys, time\nsys.stderr.write('x' * 2_000_000)\nsys.stderr.flush()\ntime.sleep(0.2)\nsys.exit(3)"
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="failed"):
        actions._run_checked([sys.executable, "-c", code], "Python", grace=20)
    assert time.monotonic() - t0 < 15


def test_failed_command_reports_its_last_error_line():
    code = "import sys\nprint('first', file=sys.stderr)\nprint('the real problem', file=sys.stderr)\nsys.exit(1)"
    with pytest.raises(RuntimeError, match="the real problem"):
        actions._run_checked([sys.executable, "-c", code], "Python")


def test_obs_port_that_isnt_a_number_falls_back():
    cfg = {"integrations": {"obs": {"host": "h", "port": "four"}}}
    assert obs.settings_from(cfg) == ("h", obs.DEFAULTS["port"], "")


# ------------------------------------------------------------------ app detection off the UI thread
def test_stale_app_scan_answers_at_once_and_refreshes_in_the_background(monkeypatch):
    old = {"x": "old"}
    started, release = threading.Event(), threading.Event()

    def slow_scan(force):
        started.set()
        release.wait(5)
        with integrations._det_lock:
            integrations._detected, integrations._detected_at = {"x": "new"}, time.time()
        return integrations._detected

    monkeypatch.setattr(integrations, "_scan", slow_scan)
    monkeypatch.setattr(integrations, "_detected", old)
    monkeypatch.setattr(integrations, "_detected_at", time.time() - integrations.DETECT_TTL - 1)
    monkeypatch.setattr(integrations, "_det_bg", False)
    t0 = time.monotonic()
    assert integrations.detect() is old                    # straight away, though the scan takes a while
    assert time.monotonic() - t0 < 0.5
    assert started.wait(2)
    assert integrations.detect() is old                    # only one rescan at a time
    release.set()
    for _ in range(100):
        if integrations.detect() == {"x": "new"}:
            break
        time.sleep(0.02)
    assert integrations.detect() == {"x": "new"}


# ------------------------------------------------------------------ glass
def test_a_still_backdrop_is_the_same():
    img = np.full((10, 20, 3), 120.0, np.float32)
    a = liquid.Backdrop(img, 0.5, 0.47)
    assert a.same_as(liquid.Backdrop(img + 0.2, 0.5, 0.47))
    assert not a.same_as(liquid.Backdrop(img + 30, 0.5, 0.5))
    assert not a.same_as(liquid.Backdrop(np.zeros((10, 21, 3), np.float32), 0.5, 0.0))
    assert not a.same_as(None)

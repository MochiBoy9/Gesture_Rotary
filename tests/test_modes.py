"""Slides / video rings, the volume slider's level parsing and the mouse button logic."""
import pytest

from rotary import modes
from rotary.mouse import HOLD_SECONDS, MouseLogic
from rotary.volume import parse_percent


@pytest.mark.parametrize("exe,title,kind,app", [
    ("POWERPNT.EXE", "Quarterly review - PowerPoint", "slides", "PowerPoint"),
    ("powerpnt.exe", "PowerPoint Slide Show - Quarterly review", "slides", "PowerPoint"),
    ("chrome.exe", "Team offsite - Google Slides - Google Chrome", "slides", "Google Slides"),
    ("msedge.exe", "Pitch deck.pptx - PowerPoint - Microsoft Edge", "slides", "PowerPoint"),
    ("Keynote", "", "slides", "Keynote"),
    ("soffice.bin", "talk.odp - LibreOffice Impress", "slides", "Impress"),
    ("vlc.exe", "movie.mkv - VLC media player", "video", "VLC"),
    ("chrome.exe", "Never Gonna Give You Up - YouTube - Google Chrome", "video", "YouTube"),
    ("firefox", "Netflix — Mozilla Firefox", "video", "Netflix"),
    ("msedge.exe", "Watch Hulu - Microsoft Edge", "video", "Hulu"),
    ("netflix", "Netflix", "video", "Netflix"),
    ("QuickTime Player", "", "video", "QuickTime Player"),
])
def test_classify_finds_slideshows_and_videos(exe, title, kind, app):
    ctx = modes.classify(exe, title)
    assert (ctx.kind, ctx.app) == (kind, app)


@pytest.mark.parametrize("exe,title", [
    ("soffice.bin", "budget.ods - LibreOffice Calc"),      # LibreOffice, but a spreadsheet
    ("code.exe", "youtube.py - Visual Studio Code"),        # the word, but not in a browser
    ("chrome.exe", "Maximum effort - Google Docs"),         # 'Max' inside another word
    ("explorer.exe", "Videos"),
    ("", ""),
])
def test_classify_leaves_everything_else_alone(exe, title):
    assert modes.classify(exe, title).kind == ""


def test_classify_respects_the_switches():
    assert modes.classify("vlc.exe", "", video=False).kind == ""
    assert modes.classify("powerpnt.exe", "x - PowerPoint", slides=False).kind == ""


def test_slide_info_parsing():
    assert modes.parse_slide_info("4 20\r\n") == (4, 20)
    assert modes.parse_slide_info("0 12") == (1, 12)
    assert modes.parse_slide_info("30 12") == (12, 12)
    assert modes.parse_slide_info("") is None
    assert modes.parse_slide_info("1 0") is None


def test_time_format():
    assert modes.fmt_time(65) == "1:05"
    assert modes.fmt_time(754) == "12:34"
    assert modes.fmt_time(3723) == "1:02:03"
    assert modes.fmt_time(-3) == "0:00"


def test_media_session_must_belong_to_the_app_in_front():
    yt = modes.classify("chrome.exe", "Song - YouTube - Google Chrome")
    assert modes.media_matches(yt, "Chrome", "Chrome")
    assert not modes.media_matches(yt, "Spotify.exe", "Spotify")
    vlc = modes.classify("vlc.exe", "x - VLC media player")
    assert modes.media_matches(vlc, "vlc", "VLC")
    assert not modes.media_matches(vlc, "Chrome", "Chrome")


def test_volume_percent_parsing():
    assert parse_percent("Volume: front-left: 32768 /  50% / -18.06 dB,   front-right: 32768 /  50%") == 0.5
    assert parse_percent("  Front Left: Playback 52428 [80%] [on]") == 0.8
    assert parse_percent("nothing here") is None


# ------------------------------------------------------------------ the mouse button
def test_quick_middle_click_goes_to_the_app():
    m = MouseLogic("middle")
    assert m.feed("down", "middle", 10, 10, now=0.0)          # held back while we find out
    m.tick(0.1)
    assert m.feed("up", "middle", 10, 10, now=0.12)
    assert m.replay == "middle" and m.take() == []


def test_holding_the_middle_button_opens():
    m = MouseLogic("middle")
    m.feed("down", "middle", 10, 10, now=0.0)
    m.tick(HOLD_SECONDS + 0.01)
    assert m.take() == [("open", 0)]
    assert m.feed("up", "middle", 10, 10, now=1.0)            # its release is ours too
    assert m.replay is None


def test_middle_drag_still_drags():
    m = MouseLogic("middle")
    m.feed("down", "middle", 10, 10, now=0.0)
    assert not m.feed("move", "", 40, 10, now=0.05)
    assert m.replay == "middle_down"
    m.tick(1.0)
    assert m.take() == []                                    # a drag never opens it
    assert not m.feed("up", "middle", 40, 10, now=1.2)       # the app gets the release as usual


def test_side_button_toggles():
    m = MouseLogic("back")
    assert m.feed("down", "back", 0, 0) and m.take() == [("toggle", 0)]
    assert m.feed("up", "back", 0, 0)
    assert not m.feed("down", "middle", 0, 0)                # other buttons are left alone
    assert not m.feed("down", "forward", 0, 0)


def test_while_open_clicks_and_scrolls_outside_stop_here():
    m = MouseLogic("middle")
    m.set_active(True, (500, 500, 300))
    assert m.feed("wheel", "", 50, 50, delta=-120)           # outside: turns the rotary, the app sees nothing
    assert m.take() == [("turn", 1)]
    assert not m.feed("wheel", "", 500, 400, delta=-120)     # over the rotary: its own window handles it
    assert m.feed("down", "left", 50, 50) and m.take() == [("close", 0)]
    assert m.feed("up", "left", 50, 50)
    assert m.feed("down", "right", 50, 50) and m.take() == [("back", 0)]
    assert m.feed("up", "right", 50, 50)
    assert not m.feed("down", "left", 520, 520)              # on the rotary: a normal click on it
    m.set_active(False)
    assert not m.feed("wheel", "", 50, 50, delta=-120)
    assert not m.feed("down", "left", 50, 50)


def test_trigger_closes_when_open():
    m = MouseLogic("middle")
    m.set_active(True, (0, 0, 10))
    assert m.feed("down", "middle", 500, 500, now=0.0)
    assert m.take() == [("close", 0)]
    m.tick(1.0)
    assert m.take() == []
    assert m.feed("up", "middle", 500, 500, now=1.0)


def test_off_does_nothing():
    m = MouseLogic("")
    assert not m.feed("down", "middle", 0, 0)
    m.tick(5.0)
    assert m.take() == []


def test_mouse_hook_lets_the_volume_slider_through():
    m = MouseLogic("middle")
    m.set_active(True, (500, 500, 300), ((830, 300, 880, 700),))
    assert not m.feed("down", "left", 850, 500)          # on the slider beside the ring: the rotary's own
    assert not m.feed("wheel", "", 850, 500, delta=120)
    assert m.take() == []
    assert m.feed("down", "left", 950, 500)               # beyond it: closes
    assert m.take() == [("close", 0)]
    m.set_active(False)
    assert m.zones == ()

import json
import os
import time

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication

from rotary import live
from rotary.live import BatteryWatch, ClipScanner, LiveState, NowPlaying
from rotary.ui.notch import NotchWindow, clock_text, mmss

app = QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ sources
def test_player_names():
    assert live.app_display_name("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "Spotify"
    assert live.app_display_name("Chrome") == "Chrome"
    assert live.app_display_name("MSEdge") == "Edge"
    assert live.app_display_name("AppleInc.AppleMusicWin_nzyj5cx40ttqa!App") == "Apple Music"
    assert live.app_display_name(r"C:\Tools\CoolPlayer.exe") == "CoolPlayer"


def test_position_moves_only_while_playing():
    t = time.monotonic()
    playing = NowPlaying("a", "A", "Song", playing=True, position=10, duration=100, at=t - 5)
    paused = NowPlaying("a", "A", "Song", playing=False, position=10, duration=100, at=t - 5)
    assert 14.5 < playing.position_now(t) < 15.5
    assert paused.position_now(t) == 10
    assert NowPlaying("a", "A", "S", playing=True, position=99, duration=100, at=t - 50).position_now(t) == 100


def test_clip_scanner_announces_new_finished_files_only(tmp_path):
    old = tmp_path / "old.mp4"
    old.write_bytes(b"x" * 10)
    sub = tmp_path / "Game"
    sub.mkdir()
    s = ClipScanner([("Medal", tmp_path, 2)])
    assert s.scan() == []                              # learns what's already there
    clip = sub / "clip.mp4"
    clip.write_bytes(b"x" * 100)
    assert s.scan() == []                              # just appeared: wait until it stops growing
    clip.write_bytes(b"x" * 200)
    assert s.scan() == []
    assert s.scan() == [("Medal", str(clip), "clip")]
    (tmp_path / "shot.png").write_bytes(b"png")
    s.scan()
    assert s.scan() == [("Medal", str(tmp_path / "shot.png"), "screenshot")]
    (tmp_path / "notes.txt").write_text("not a clip")
    s.scan()
    assert s.scan() == []


def test_battery_moments():
    b = BatteryWatch()
    assert b.update((50, True)) == []
    assert b.update((50, False)) == [("power", {"percent": 50, "plugged": False})]
    assert b.update((20, False)) == [("battery_low", {"percent": 20})]
    assert b.update((19, False)) == []                 # said once
    assert b.update((10, False)) == [("battery_low", {"percent": 10})]
    assert b.update(None) == []


def test_medal_activity_reads_the_live_game(tmp_path, monkeypatch):
    monkeypatch.setattr(live.winapi, "is_running", lambda name: name == "medal.exe")
    (tmp_path / "game.json").write_text(json.dumps({"game": None, "activeGames": []}))
    assert live.medal_activity(tmp_path) == ""
    (tmp_path / "game.json").write_text(json.dumps({"game": {"name": "VALORANT", "id": 1}}))
    assert live.medal_activity(tmp_path) == "VALORANT"
    monkeypatch.setattr(live.winapi, "is_running", lambda name: False)
    assert live.medal_activity(tmp_path) == ""         # Medal closed: whatever the file says


def test_crashed_apps_dont_count_as_using_the_mic(monkeypatch):
    monkeypatch.setattr(live.winapi, "running_processes", lambda: {"explorer.exe"})
    assert all(not n.lower().startswith("medalencoder") for n in live.in_use("microphone"))


# ------------------------------------------------------------------ the notch as a Dynamic Island
def _settle(n: NotchWindow):
    for _ in range(90):
        for sp in n._springs:
            sp.step(1 / 60)


def test_clock_and_timer_text():
    t = time.struct_time((2026, 10, 21, 21, 5, 0, 2, 294, 0))
    assert clock_text(t, False, False) == "9:05"
    assert clock_text(t, True, False) == "21:05"
    assert clock_text(t, True, True).endswith("21  21:05")
    assert mmss(272) == "4:32" and mmss(3725) == "1:02:05"


def test_activity_priority_and_options():
    n = NotchWindow()
    song = NowPlaying("Spotify.exe", "Spotify", "Song", playing=True)
    n.set_live(LiveState(media=song))
    assert n.activity() == "media"
    n.set_live(LiveState(media=song, clipping="VALORANT"))
    assert n.activity() == "clip"
    n.start_timer(60)
    assert n.activity() == "timer"
    n.cancel_timer()
    n.set_options({"clips": False, "media": False})
    assert n.activity() == ""
    n.set_options({"clock": "off"})
    assert n._clock() == ""


def test_paused_music_leaves_after_a_while(monkeypatch):
    n = NotchWindow()
    n.set_live(LiveState(media=NowPlaying("a", "A", "Song", playing=False)))
    assert n.media() is not None
    n._paused_at -= 1000
    assert n.media() is None


def test_resting_notch_grows_for_an_activity():
    n = NotchWindow()
    n.set_options({"clock": "time"})
    _settle(n)
    w0 = n.body_rect().width()
    n.set_live(LiveState(media=NowPlaying("a", "A", "Song", playing=True), mic=["Discord"]))
    _settle(n)
    assert n.body_rect().width() > w0


def test_media_card_buttons(monkeypatch):
    n = NotchWindow()
    n.set_live(LiveState(media=NowPlaying("a", "A", "Song", playing=True, duration=200)))
    n.hovered = True
    n._retarget()
    _settle(n)
    from PySide6.QtGui import QImage, QPainter
    img = QImage(n.width(), n.height(), QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    n.paint(p)
    p.end()
    assert set(n._buttons) == {"previous", "play_pause", "next"}
    got, opened = [], []
    n.media_command.connect(got.append)
    n.clicked.connect(lambda: opened.append(1))

    class Press:
        def __init__(self, pt):
            self.pt = pt

        def button(self):
            return Qt.MouseButton.LeftButton

        def position(self):
            return self.pt
    n.mousePressEvent(Press(n._buttons["next"].center()))
    n.mousePressEvent(Press(QPointF(n.body_rect().left() + 30, 40)))     # the album art: opens the rotary
    assert got == ["next"] and opened == [1]


def test_calls_come_from_call_apps_holding_the_mic():
    assert live.call_from([("OBS64", 1.0), ("Discord", 100.0)]) == ("Discord", 100.0)
    assert live.call_from([("MSTeams", 5.0)]) == ("Teams", 5.0)
    assert live.call_from([("Zoom", 7.0)]) == ("Zoom", 7.0)
    assert live.call_from([("chrome", 1.0), ("Audacity", 2.0)]) is None


def test_discord_voice_socket_means_a_call(monkeypatch):
    procs = {10: "discord.exe", 11: "discord.exe", 12: "discord.exe", 99: "chrome.exe"}
    cmds = {10: "discord.exe --type=renderer --enable-features=NetworkServiceInProcess",
            11: "discord.exe --type=utility --utility-sub-type=network.mojom.NetworkService",
            12: "discord.exe"}
    monkeypatch.setattr(live.winapi, "processes", lambda: procs)
    monkeypatch.setattr(live.winapi, "command_line", lambda pid: cmds.get(pid, ""))
    live._cmdlines.clear()
    monkeypatch.setattr(live, "udp_sockets", lambda: [(11, 50.0), (99, 60.0)])
    assert live.discord_call() is None                 # only the network service and Chrome: no call
    monkeypatch.setattr(live, "udp_sockets", lambda: [(11, 50.0), (10, 1000.0), (10, 1200.0)])
    assert live.discord_call() == 1000.0               # the app's own voice socket
    monkeypatch.setattr(live.winapi, "processes", lambda: {99: "chrome.exe"})
    assert live.discord_call() is None


def test_udp_table_reads():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    try:
        mine = [t for pid, t in live.udp_sockets() if pid == os.getpid()]
        assert mine and abs(mine[0] - time.time()) < 120
    finally:
        s.close()


def test_a_call_outranks_everything_and_counts_up():
    n = NotchWindow()
    n.start_timer(60)
    n.set_live(LiveState(media=NowPlaying("a", "A", "Song", playing=True), call=("Discord", time.time() - 754)))
    assert n.activity() == "call"
    assert 753 <= n.call_seconds() <= 756 and mmss(n.call_seconds()) in ("12:34", "12:35", "12:33")
    n.set_options({"calls": False})
    assert n.activity() == "timer"


def test_call_card_buttons():
    n = NotchWindow()
    n.set_live(LiveState(call=("Discord", time.time() - 5)))
    n.hovered = True
    n._retarget()
    _settle(n)
    from PySide6.QtGui import QImage, QPainter
    img = QImage(n.width(), n.height(), QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    n.paint(p)
    p.end()
    assert set(n._buttons) == {"call_mute", "call_deafen"}
    got = []
    n.call_command.connect(lambda app_, what: got.append((app_, what)))
    ev = type("E", (), {"button": lambda self: Qt.MouseButton.LeftButton,
                        "position": lambda self: n._buttons["call_deafen"].center()})()
    n.mousePressEvent(ev)
    assert got == [("Discord", "deafen")]


def test_timer_rings():
    n = NotchWindow()
    rang = []
    n.timer_done.connect(lambda: rang.append(1))
    n.start_timer(10)
    n.add_time(60)
    assert 69 < n.timer_left() <= 70
    n.timer_end = time.monotonic() - 0.1
    n._live_tick()
    assert rang == [1] and n.timer_end is None

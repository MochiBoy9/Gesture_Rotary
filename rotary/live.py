"""Live activities for the notch — the things a Dynamic Island shows.

  * Now playing: whatever Windows' media controls know about (YouTube and other sites in Chrome / Edge /
    Firefox, Spotify, Apple Music, Windows Media Player, …) with album art, progress and play / skip.
    On Linux, any MPRIS player through playerctl. (macOS has no public API for this.)
  * Clips: Medal is recording a game; a clip or screenshot was just saved by Medal, Xbox Game Bar, the NVIDIA
    app or OBS.
  * Privacy: an app is using the microphone or the camera (other than Gesture Rotary itself).
  * Battery: plugged in / unplugged, running low.

Everything runs on one background thread with its own asyncio loop (the media API is async) and reports to
the UI thread through Qt signals. Nothing here starts unless the notch is showing.
"""
from __future__ import annotations

import asyncio
import ctypes
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from . import winapi

log = logging.getLogger(__name__)

VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm", ".flv")
IMAGE_EXT = (".png", ".jpg", ".jpeg")


# =========================================================================== data
@dataclass
class NowPlaying:
    app: str                       # the player's app id
    app_name: str                  # what to call it ("Spotify", "Chrome", …)
    title: str
    artist: str = ""
    playing: bool = False
    position: float = 0.0          # seconds, as of `at`
    duration: float = 0.0          # 0 = unknown
    at: float = field(default_factory=time.monotonic)
    art: bytes | None = None       # album art / video thumbnail (an encoded image)
    can_prev: bool = True
    can_next: bool = True

    def position_now(self, now: float | None = None) -> float:
        p = self.position + ((now or time.monotonic()) - self.at if self.playing else 0.0)
        return max(0.0, min(p, self.duration)) if self.duration > 0 else max(0.0, p)

    @property
    def key(self) -> tuple:
        return self.app, self.title, self.artist


@dataclass
class LiveState:
    media: NowPlaying | None = None
    clipping: str = ""             # e.g. "Medal · VALORANT" while Medal records a game
    mic: list[str] = field(default_factory=list)
    camera: list[str] = field(default_factory=list)
    call: tuple[str, float] | None = None     # (app, started — Unix time) while in a voice call


# =========================================================================== app names
_KNOWN_PLAYERS = {
    "spotify": "Spotify", "applemusic": "Apple Music", "itunes": "iTunes", "chrome": "Chrome", "msedge": "Edge",
    "firefox": "Firefox", "opera": "Opera", "brave": "Brave", "vivaldi": "Vivaldi", "zunemusic": "Media Player",
    "microsoft.media.player": "Media Player", "vlc": "VLC", "foobar2000": "foobar2000", "musicbee": "MusicBee",
    "tidal": "TIDAL", "deezer": "Deezer", "amazonmusic": "Amazon Music", "youtube": "YouTube", "discord": "Discord",
    "zen": "Zen", "arc": "Arc", "thebrowsercompany": "Arc", "soundcloud": "SoundCloud",
}


def app_display_name(app_id: str) -> str:
    """'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' → 'Spotify', 'Chrome' → 'Chrome', 'msedge.exe' → 'Edge'."""
    low = app_id.lower().replace(" ", "")
    for key, name in _KNOWN_PLAYERS.items():
        if key in low:
            return name
    base = app_id.split("!")[0].split("\\")[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    else:
        base = base.split("_")[0].rsplit(".", 1)[-1]
    return base or "Media"


# =========================================================================== clips
def medal_store() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Medal" / "store"


def medal_activity(store: Path | None = None) -> str:
    """The game Medal is recording right now, '' if none. Medal writes its live game state to game.json."""
    if not winapi.is_running("medal.exe"):
        return ""
    try:
        data = json.loads(((store or medal_store()) / "game.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    games = [data.get("game")] + list(data.get("activeGames") or [])
    for g in games:
        if not g:
            continue
        if isinstance(g, str):
            return g
        if isinstance(g, dict):
            for k in ("name", "title", "gameName", "displayName", "processName"):
                if isinstance(g.get(k), str) and g[k]:
                    return g[k]
            return "a game"
    return ""


def _medal_folder() -> Path:
    """Medal's clip folder: the setting if it has one, else the default under Videos."""
    try:
        data = json.loads((medal_store() / "settings.json").read_text(encoding="utf-8"))
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                for k, v in d.items():
                    if isinstance(v, str) and any(w in k.lower() for w in ("clipfolder", "clipsfolder", "clipdir",
                                                                           "clipsdir", "clippath", "clipspath",
                                                                           "savepath", "storagepath")):
                        if os.path.isdir(v):
                            return Path(v)
                    elif isinstance(v, (dict, list)):
                        stack.append(v)
            elif isinstance(d, list):
                stack.extend(d)
    except (OSError, ValueError):
        pass
    return videos_folder() / "Medal"


def videos_folder() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Movies"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            v, _ = winreg.QueryValueEx(k, "My Video")
            return Path(os.path.expandvars(v))
    except (OSError, ImportError):
        return Path.home() / "Videos"


def obs_config() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", "")) / "obs-studio"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "obs-studio"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "obs-studio"


def _obs_folders() -> list[Path]:
    out = []
    base = obs_config() / "basic" / "profiles"
    for ini in base.glob("*/basic.ini") if base.exists() else []:
        try:
            for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith(("FilePath=", "RecFilePath=")):
                    p = Path(line.split("=", 1)[1].replace("\\\\", "\\").strip())
                    if p.is_dir() and p not in out:
                        out.append(p)
        except OSError:
            pass
    return out


def clip_folders() -> list[tuple[str, Path, int]]:
    """(who saves there, folder, how deep to look) for every clip tool we know that's set up on this PC."""
    vids = videos_folder()
    found = [("Medal", _medal_folder(), 3), ("Xbox Game Bar", vids / "Captures", 1), ("NVIDIA", vids / "NVIDIA", 2)]
    found += [("OBS", p, 1) for p in _obs_folders()]
    out, seen = [], set()
    for who, p, depth in found:
        key = str(p).lower()
        if p.is_dir() and key not in seen:
            seen.add(key)
            out.append((who, p, depth))
    return out


class ClipScanner:
    """Notices new clips and screenshots. The first scan only learns what's already there; a file counts once
    it has stopped growing (so a clip that's still being written isn't announced early)."""

    def __init__(self, folders: list[tuple[str, Path, int]]):
        self.folders = folders
        self.seen: set[str] = set()
        self.pending: dict[str, int] = {}
        self.primed = False

    def _walk(self, root: Path, depth: int):
        try:
            with os.scandir(root) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        if depth > 1:
                            yield from self._walk(Path(e.path), depth - 1)
                    elif e.name.lower().endswith(VIDEO_EXT + IMAGE_EXT):
                        yield e
        except OSError:
            return

    def scan(self) -> list[tuple[str, str, str]]:
        """New, finished files since the last scan: (who, path, 'clip' | 'screenshot')."""
        out = []
        for who, root, depth in self.folders:
            for e in self._walk(root, depth):
                if e.path in self.seen:
                    continue
                if not self.primed:
                    self.seen.add(e.path)
                    continue
                try:
                    size = e.stat().st_size
                except OSError:
                    continue
                if size > 0 and self.pending.get(e.path) == size:
                    self.seen.add(e.path)
                    self.pending.pop(e.path, None)
                    kind = "screenshot" if e.name.lower().endswith(IMAGE_EXT) else "clip"
                    out.append((who, e.path, kind))
                else:
                    self.pending[e.path] = size
        self.primed = True
        return out


# =========================================================================== privacy
def _consent_root(kind: str) -> str:
    return rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{kind}"


def in_use(kind: str, exclude: tuple[str, ...] = ()) -> list[str]:
    """Apps using the microphone / webcam right now."""
    return [name for name, _since in in_use_since(kind, exclude)]


def in_use_since(kind: str, exclude: tuple[str, ...] = ()) -> list[tuple[str, float]]:
    """(app, when it started — Unix time) for every app using the microphone / webcam right now. Windows
    records a start time and a zero stop time while an app holds the device."""
    if sys.platform != "win32":
        return []
    import winreg
    found: list[tuple[str, float]] = []
    running = winapi.running_processes()      # a crashed app can leave "still in use" behind

    def check(key, label: str) -> None:
        try:
            stop, _ = winreg.QueryValueEx(key, "LastUsedTimeStop")
            start, _ = winreg.QueryValueEx(key, "LastUsedTimeStart")
        except OSError:
            return
        if stop == 0 and start > 0 and label and all(label != n for n, _s in found):
            found.append((label, start / 1e7 - 11644473600.0))        # FILETIME → Unix time

    def walk(path: str, nonpackaged: bool) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    if sub == "NonPackaged":
                        walk(path + "\\NonPackaged", True)
                        continue
                    full = sub.replace("#", "\\")
                    if nonpackaged and (any(full.lower() == x.lower() for x in exclude)
                                        or (running and Path(full).name.lower() not in running)):
                        continue
                    label = (Path(full).stem if nonpackaged else sub.split("_")[0].rsplit(".", 1)[-1])
                    with winreg.OpenKey(k, sub) as sk:
                        check(sk, label)
        except OSError:
            return

    walk(_consent_root(kind), False)
    return found


class _Udp4Row(ctypes.Structure):          # MIB_UDPROW_OWNER_MODULE
    _fields_ = [("addr", ctypes.c_uint32), ("port", ctypes.c_uint32), ("pid", ctypes.c_uint32),
                ("created", ctypes.c_int64), ("flags", ctypes.c_uint32), ("module", ctypes.c_uint64 * 16)]


class _Udp6Row(ctypes.Structure):          # MIB_UDP6ROW_OWNER_MODULE
    _fields_ = [("addr", ctypes.c_ubyte * 16), ("scope", ctypes.c_uint32), ("port", ctypes.c_uint32),
                ("pid", ctypes.c_uint32), ("created", ctypes.c_int64), ("flags", ctypes.c_uint32),
                ("module", ctypes.c_uint64 * 16)]


def udp_sockets() -> list[tuple[int, float]]:
    """(owning pid, when it was opened — Unix time, 0 if unknown) for every UDP socket on the PC."""
    if sys.platform != "win32":
        return []
    out = []
    fn = ctypes.windll.iphlpapi.GetExtendedUdpTable
    for family, row in ((2, _Udp4Row), (23, _Udp6Row)):
        size = ctypes.c_ulong(0)
        fn(None, ctypes.byref(size), False, family, 2, 0)               # UDP_TABLE_OWNER_MODULE
        if not size.value:
            continue
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = ctypes.c_ulong(ctypes.sizeof(buf))
        if fn(buf, ctypes.byref(size), False, family, 2, 0) != 0:
            continue
        n = ctypes.c_uint32.from_buffer(buf).value
        base = ctypes.alignment(row)                                      # the rows start after the count
        base = (4 + base - 1) // base * base
        for i in range(n):
            r = row.from_buffer(buf, base + i * ctypes.sizeof(row))
            t = r.created / 1e7 - 11644473600.0 if r.created > 0 else 0.0
            out.append((int(r.pid), t))
    return out


DISCORD_EXES = ("discord.exe", "discordptb.exe", "discordcanary.exe")
_cmdlines: dict[int, str] = {}


def discord_call() -> float | None:
    """When the current Discord voice call started (Unix time), or None if not in one. A voice connection is
    a UDP socket opened by Discord's app (renderer) process — muted or not. Its network-service process keeps
    unrelated UDP sockets of its own, so those don't count."""
    pids = {pid for pid, name in winapi.processes().items() if name in DISCORD_EXES}
    if not pids:
        _cmdlines.clear()
        return None
    for gone in [p for p in _cmdlines if p not in pids]:
        _cmdlines.pop(gone, None)
    starts = []
    for pid, t in udp_sockets():
        if pid not in pids:
            continue
        cmd = _cmdlines.get(pid)
        if cmd is None:
            cmd = _cmdlines[pid] = winapi.command_line(pid).lower()
        if ("--utility-sub-type=network.mojom.networkservice" in cmd or "--type=gpu-process" in cmd
                or "--type=crashpad-handler" in cmd):
            continue
        starts.append(t or time.time())
    return min(starts) if starts else None


CALL_APPS = {"discord": "Discord", "msteams": "Teams", "ms-teams": "Teams", "teams": "Teams", "zoom": "Zoom",
             "slack": "Slack", "skype": "Skype", "whatsapp": "WhatsApp", "telegram": "Telegram", "signal": "Signal",
             "webex": "Webex", "ciscocollabhost": "Webex", "guilded": "Guilded", "teamspeak": "TeamSpeak",
             "mumble": "Mumble", "facetime": "FaceTime"}


def call_from(mic: list[tuple[str, float]]) -> tuple[str, float] | None:
    """A voice call, inferred from a call app holding the microphone: (app, started — Unix time)."""
    for label, since in mic:
        low = label.lower().replace(" ", "")
        for key, name in CALL_APPS.items():
            if low == key or low.startswith(key):
                return name, since
    return None


# =========================================================================== battery
class _PowerStatus(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


def battery() -> tuple[int, bool] | None:
    """(percent, plugged in), or None on a PC without a battery."""
    if sys.platform != "win32":
        from . import posix
        return posix.battery()
    s = _PowerStatus()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return None
    if s.BatteryFlag & 128 or s.BatteryFlag == 255 or s.BatteryLifePercent > 100:
        return None
    return int(s.BatteryLifePercent), s.ACLineStatus == 1


class BatteryWatch:
    """Turns battery readings into moments worth a glance."""

    def __init__(self):
        self.last: tuple[int, bool] | None = None
        self.warned = 100

    def update(self, reading: tuple[int, bool] | None) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        if reading is None:
            return out
        pct, plugged = reading
        if self.last is not None and plugged != self.last[1]:
            out.append(("power", {"percent": pct, "plugged": plugged}))
        if plugged:
            self.warned = 100
        else:
            for level in (10, 20):
                if pct <= level < self.warned:
                    self.warned = level
                    out.append(("battery_low", {"percent": pct}))
                    break
        self.last = reading
        return out


# =========================================================================== media (Windows media controls)
class Media:
    """Reads and controls the system media session. Must be used from one asyncio loop."""

    def __init__(self):
        self.mgr = None
        self._art_key = None
        self._art: bytes | None = None

    async def _manager(self):
        if self.mgr is None:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            self.mgr = await M.request_async()
        return self.mgr

    async def _session(self):
        mgr = await self._manager()
        sessions = list(mgr.get_sessions())
        cur = mgr.get_current_session()
        playing = [s for s in sessions if int(s.get_playback_info().playback_status) == 4]
        if cur is not None and (not playing or any(s.source_app_user_model_id == cur.source_app_user_model_id
                                                   for s in playing)):
            return cur
        return playing[0] if playing else (cur or (sessions[0] if sessions else None))

    async def read(self, want_art: bool = True) -> NowPlaying | None:
        s = await self._session()
        if s is None:
            return None
        props = await s.try_get_media_properties_async()
        if props is None or not (props.title or "").strip():
            return None
        info = s.get_playback_info()
        status = int(info.playback_status)
        if status in (0, 1):                 # closed / just opened
            return None
        tl = s.get_timeline_properties()
        duration = max(0.0, (tl.end_time - tl.start_time).total_seconds())
        position = max(0.0, (tl.position - tl.start_time).total_seconds())
        playing = status == 4
        now = time.monotonic()
        if playing and tl.last_updated_time is not None and tl.last_updated_time.year > 2000:
            age = (dt.datetime.now(dt.timezone.utc) - tl.last_updated_time).total_seconds()
            if 0 <= age < 3600:
                position += age
        app = s.source_app_user_model_id or ""
        title, artist = props.title.strip(), (props.artist or props.album_artist or "").strip()
        key = (app, title, artist)
        if want_art and key != self._art_key:
            self._art_key, self._art = key, await self._thumbnail(props)
        ctl = info.controls
        return NowPlaying(app, app_display_name(app), title, artist, playing, position,
                          duration if duration > 1 else 0.0, now, self._art if want_art else None,
                          bool(ctl.is_previous_enabled), bool(ctl.is_next_enabled))

    @staticmethod
    async def _thumbnail(props) -> bytes | None:
        if props.thumbnail is None:
            return None
        try:
            from winrt.windows.storage.streams import Buffer, InputStreamOptions
            stream = await props.thumbnail.open_read_async()
            size = min(int(stream.size), 8_000_000)
            buf = Buffer(size)
            await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            return bytes(buf)
        except Exception:
            log.debug("no album art", exc_info=True)
            return None

    async def command(self, cmd: str) -> None:
        s = await self._session()
        if s is None:
            return
        if cmd == "play_pause":
            await s.try_toggle_play_pause_async()
        elif cmd == "next":
            await s.try_skip_next_async()
        elif cmd == "previous":
            await s.try_skip_previous_async()


# =========================================================================== media (Linux: MPRIS via playerctl)
class PlayerctlMedia:
    """The same interface as Media, for Linux media players (anything speaking MPRIS: Spotify, browsers,
    VLC, Rhythmbox…), read through the playerctl command."""
    FIELDS = ("playerName", "status", "title", "artist", "position", "mpris:length", "mpris:artUrl")

    def __init__(self):
        self._art_key = None
        self._art: bytes | None = None

    @staticmethod
    def _run(*args: str) -> str:
        import subprocess
        try:
            return subprocess.run(["playerctl", *args], capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    @staticmethod
    def parse(line: str) -> dict | None:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != len(PlayerctlMedia.FIELDS):
            return None
        return dict(zip(PlayerctlMedia.FIELDS, parts))

    @staticmethod
    def _seconds(us: str) -> float:
        try:
            return max(0.0, int(float(us)) / 1e6)
        except ValueError:
            return 0.0

    async def read(self, want_art: bool = True) -> NowPlaying | None:
        fmt = "\t".join("{{" + f + "}}" for f in self.FIELDS)
        d = self.parse(await asyncio.to_thread(self._run, "metadata", "--format", fmt))
        if d is None or not d["title"].strip() or d["status"] not in ("Playing", "Paused"):
            return None
        key = (d["playerName"], d["title"], d["artist"])
        if want_art and key != self._art_key:
            self._art_key, self._art = key, await asyncio.to_thread(self._fetch_art, d["mpris:artUrl"])
        duration = self._seconds(d["mpris:length"])
        return NowPlaying(d["playerName"], app_display_name(d["playerName"]), d["title"].strip(), d["artist"].strip(),
                          d["status"] == "Playing", self._seconds(d["position"]), duration if duration > 1 else 0.0,
                          time.monotonic(), self._art if want_art else None)

    @staticmethod
    def _fetch_art(url: str) -> bytes | None:
        import urllib.parse
        import urllib.request
        try:
            if url.startswith("file://"):
                return Path(urllib.request.url2pathname(urllib.parse.urlparse(url).path)).read_bytes()[:8_000_000]
            if url.startswith(("http://", "https://")):
                with urllib.request.urlopen(url, timeout=3) as r:
                    return r.read(8_000_000)
        except (OSError, ValueError):
            log.debug("no album art", exc_info=True)
        return None

    async def command(self, cmd: str) -> None:
        verb = {"play_pause": "play-pause", "next": "next", "previous": "previous"}.get(cmd)
        if verb:
            await asyncio.to_thread(self._run, verb)


def media_source():
    """Where 'now playing' comes from on this system (None: nowhere)."""
    if sys.platform == "win32":
        return Media()
    import shutil
    if sys.platform.startswith("linux") and shutil.which("playerctl"):
        return PlayerctlMedia()
    return None


# =========================================================================== the watcher thread
class LiveWatcher(QThread):
    state = Signal(object)            # LiveState, whenever something visible changes
    event = Signal(str, object)       # ("clip", {...}) | ("power", {...}) | ("battery_low", {...})

    def __init__(self, parent=None):
        super().__init__(parent)
        self.opts = {"media": True, "media_art": True, "clips": True, "privacy": True, "battery": True,
                     "calls": True}
        self.exclude: tuple[str, ...] = (sys.executable,)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._last: LiveState | None = None
        self._media: NowPlaying | None = None
        self._clipping = ""
        self._mic: list[str] = []
        self._cam: list[str] = []
        self._call: tuple[str, float] | None = None
        self._media_error_logged = False
        self._media_api = None

    # -- from the UI thread
    def configure(self, opts: dict) -> None:
        self.opts.update({k: bool(v) for k, v in opts.items() if k in self.opts})

    def control(self, cmd: str) -> None:
        loop = self._loop
        if loop is not None and not self._stop.is_set():
            asyncio.run_coroutine_threadsafe(self._command(cmd), loop)

    def stop(self) -> None:
        self._stop.set()
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: None)

    # -- thread body
    def run(self) -> None:
        self._stop.clear()
        if sys.platform == "win32":
            try:
                import winrt.runtime
                winrt.runtime.init_apartment(winrt.runtime.MTA)   # Windows' media API needs COM on this thread
            except Exception:
                log.debug("COM already set up on the live thread", exc_info=True)
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._main())
        except Exception:
            log.exception("live activities stopped")
        finally:
            self._loop = None
            loop.close()

    async def _command(self, cmd: str) -> None:
        if self._media_api is None:
            return
        try:
            await self._media_api.command(cmd)
            await asyncio.sleep(0.25)
            await self._poll_media()
        except Exception:
            log.debug("media command %s failed", cmd, exc_info=True)

    async def _main(self) -> None:
        self._media_api = media_source()
        if self._media_api is None:
            log.info("no source for what's playing on this system")
        clips = ClipScanner(await asyncio.to_thread(clip_folders))
        power = BatteryWatch()
        tick = 0
        while not self._stop.is_set():
            if self.opts["media"]:
                await self._poll_media()
            elif self._media is not None:
                self._media = None
            if tick % 2 == 0:
                if self.opts["clips"]:
                    try:
                        for who, path, kind in await asyncio.to_thread(clips.scan):
                            self.event.emit("clip", {"who": who, "path": path, "kind": kind})
                        clipping = await asyncio.to_thread(medal_activity)
                        if clipping != self._clipping:
                            log.info("Medal %s", f"is clipping {clipping}" if clipping else "stopped clipping")
                        self._clipping = clipping
                    except Exception:
                        log.debug("clip scan failed", exc_info=True)
                else:
                    self._clipping = ""
                if self.opts["privacy"] or self.opts["calls"]:
                    mic = await asyncio.to_thread(in_use_since, "microphone", self.exclude)
                    call = None
                    if self.opts["calls"]:
                        started = await asyncio.to_thread(discord_call)
                        call = ("Discord", started) if started else call_from(mic)
                        if call and self._call and call[0] == self._call[0]:
                            call = (call[0], min(call[1], self._call[1]))   # a reconnect isn't a new call
                    if (call and call[0]) != (self._call and self._call[0]):
                        log.info("call %s", f"started in {call[0]}" if call else "ended")
                    self._call = call
                    self._mic = [n for n, _t in mic] if self.opts["privacy"] else []
                    self._cam = (await asyncio.to_thread(in_use, "webcam", self.exclude)
                                 if self.opts["privacy"] else [])
                else:
                    self._mic, self._cam, self._call = [], [], None
            if tick % 10 == 0 and self.opts["battery"]:
                for name, data in power.update(battery()):
                    self.event.emit(name, data)
            if tick % 60 == 59:
                clips.folders = await asyncio.to_thread(clip_folders)      # new tools / folders
            self._publish()
            tick += 1
            for _ in range(10):
                if self._stop.is_set():
                    break
                await asyncio.sleep(0.1)

    async def _poll_media(self) -> None:
        before = self._media
        if self._media_api is None:
            self._media = None
            return
        try:
            self._media = await self._media_api.read(self.opts["media_art"])
        except Exception:
            if not self._media_error_logged:          # say it once, plainly, then stay quiet
                log.warning("can't read what's playing from the system's media controls", exc_info=True)
                self._media_error_logged = True
            self._media = None
        m = self._media
        if (m and m.key) != (before and before.key):
            log.info("now playing: %s", f"{m.title!r} by {m.artist!r} in {m.app_name}" if m else "nothing")
        self._publish()

    def _publish(self) -> None:
        st = LiveState(self._media, self._clipping, list(self._mic), list(self._cam), self._call)
        last = self._last
        if (last is None or st.clipping != last.clipping or st.mic != last.mic or st.camera != last.camera
                or st.call != last.call
                or (st.media is None) != (last.media is None)
                or (st.media is not None and last.media is not None and (
                    st.media.key != last.media.key or st.media.playing != last.media.playing
                    or abs(st.media.position_now() - last.media.position_now()) > 2.0
                    or (st.media.art is None) != (last.media.art is None)))):
            self._last = st
            self.state.emit(st)

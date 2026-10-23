"""The system output volume, for the two-finger volume slider.

Windows: the default speakers' master volume through Core Audio (IAudioEndpointVolume, called over raw COM
with ctypes), so it changes silently, without Windows' volume flyout appearing over a full-screen game.
If that fails, the volume keys. macOS: AppleScript's `output volume`. Linux: PulseAudio / PipeWire through
`pactl`, or ALSA's `amixer`.

`Volume.change(steps)` and `Volume.set(level)` (the mouse's slider beside the rotary) never block the caller for
long: on macOS and Linux the commands run on one background thread, and changes that arrive while one is running
are added together (the last level set wins)."""
from __future__ import annotations

import ctypes
import logging
import re
import shutil
import subprocess
import sys
import threading
from typing import Callable

log = logging.getLogger(__name__)

STEP = 0.02          # one step of the slider: 2 %


# --------------------------------------------------------------------------- Windows: Core Audio over COM
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s: str) -> "_GUID":
        h = s.replace("-", "")
        d4 = bytes.fromhex(h[16:])
        return cls(int(h[:8], 16), int(h[8:12], 16), int(h[12:16], 16), (ctypes.c_ubyte * 8)(*d4))


CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IAudioEndpointVolume = "5CDF2C82-841E-4546-9722-0CF74078229A"


def _method(ptr: ctypes.c_void_p, index: int, restype, *argtypes):
    """Method `index` of a COM interface pointer's vtable, as a callable taking the remaining arguments."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(ptr, *args)


class _EndpointVolume:
    """IAudioEndpointVolume of the default render device (re-fetched if the speakers change)."""

    def __init__(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, 0x2)                 # apartment-threaded; harmless if already set up
        enum = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_GUID.parse(CLSID_MMDeviceEnumerator)), None, 23,
                                    ctypes.byref(_GUID.parse(IID_IMMDeviceEnumerator)), ctypes.byref(enum))
        if hr != 0 or not enum:
            raise OSError(hr, "MMDeviceEnumerator")
        dev = ctypes.c_void_p()
        hr = _method(enum, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
            0, 1, ctypes.byref(dev))                    # GetDefaultAudioEndpoint(eRender, eMultimedia)
        _method(enum, 2, ctypes.c_ulong)()              # Release the enumerator
        if hr != 0 or not dev:
            raise OSError(hr, "GetDefaultAudioEndpoint")
        vol = ctypes.c_void_p()
        hr = _method(dev, 3, ctypes.c_long, ctypes.POINTER(_GUID), ctypes.c_uint32, ctypes.c_void_p,
                     ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(_GUID.parse(IID_IAudioEndpointVolume)), 23,
                                                      None, ctypes.byref(vol))     # Activate
        _method(dev, 2, ctypes.c_ulong)()
        if hr != 0 or not vol:
            raise OSError(hr, "IAudioEndpointVolume")
        self.ptr = vol
        self._set = _method(vol, 7, ctypes.c_long, ctypes.c_float, ctypes.c_void_p)      # SetMasterVolumeLevelScalar
        self._get = _method(vol, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float))       # GetMasterVolumeLevelScalar
        self._set_mute = _method(vol, 14, ctypes.c_long, ctypes.c_int, ctypes.c_void_p)  # SetMute

    def get(self) -> float:
        v = ctypes.c_float()
        hr = self._get(ctypes.byref(v))
        if hr != 0:
            raise OSError(hr, "GetMasterVolumeLevelScalar")
        return float(v.value)

    def set(self, level: float) -> None:
        hr = self._set(ctypes.c_float(max(0.0, min(1.0, level))), None)
        if hr != 0:
            raise OSError(hr, "SetMasterVolumeLevelScalar")
        if level > 0:
            self._set_mute(0, None)                     # turning it up unmutes, like the volume keys do

    def release(self) -> None:
        if self.ptr:
            _method(self.ptr, 2, ctypes.c_ulong)()
            self.ptr = None


# --------------------------------------------------------------------------- macOS / Linux commands
def _run(args: list[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_percent(text: str) -> float | None:
    """The first 'NN%' in pactl / amixer output, as 0..1."""
    m = re.search(r"(\d{1,3})%", text)
    return min(1.0, int(m.group(1)) / 100.0) if m else None


def _posix_get() -> float | None:
    if sys.platform == "darwin":
        out = _run(["osascript", "-e", "output volume of (get volume settings)"]).strip()
        return min(1.0, int(out) / 100.0) if out.isdigit() else None
    if shutil.which("pactl"):
        v = parse_percent(_run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
        if v is not None:
            return v
    if shutil.which("amixer"):
        return parse_percent(_run(["amixer", "get", "Master"]))
    return None


def _posix_set(level: float) -> bool:
    pct = int(round(max(0.0, min(1.0, level)) * 100))
    if sys.platform == "darwin":
        _run(["osascript", "-e", f"set volume output volume {pct}"
              + (" without output muted" if pct > 0 else "")])
        return True
    if shutil.which("pactl"):
        _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"])
        if pct > 0:
            _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        return True
    if shutil.which("amixer"):
        _run(["amixer", "-q", "set", "Master", f"{pct}%", "unmute" if pct > 0 else "mute"])
        return True
    return False


# --------------------------------------------------------------------------- the one callers use
class Volume:
    """Change the output volume by slider steps. `on_level(level)` reports the new level (0..1), or -1 when
    the level can't be read (Windows' volume keys); it may be called from a background thread."""

    def __init__(self, on_level: Callable[[float], None]):
        self.on_level = on_level
        self._ep: _EndpointVolume | None = None
        self._ep_failed = False
        self._pending = 0
        self._target: float | None = None
        self._lock = threading.Lock()
        self._busy = False
        self._level: float | None = None

    def change(self, steps: int) -> None:
        if not steps:
            return
        if sys.platform == "win32":
            self._change_windows(steps)
            return
        with self._lock:
            self._pending += steps
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._posix_worker, daemon=True, name="volume").start()

    def set(self, level: float) -> None:
        """Set the volume to `level` (0..1)."""
        level = max(0.0, min(1.0, round(level / STEP) * STEP))
        if sys.platform == "win32":
            self._windows(lambda cur: level)      # (the volume keys can't go to a level: then it does nothing)
            return
        with self._lock:
            self._target, self._pending = level, 0
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._posix_worker, daemon=True, name="volume").start()

    def read(self, on_read: Callable[[float], None]) -> None:
        """Report the current level (0..1, or -1 when it can't be read) to `on_read`, maybe from another thread."""
        if sys.platform == "win32":
            got = self._windows(None)
            on_read(-1.0 if got is None else got)
            return

        def work():
            try:
                v = _posix_get()
            except Exception:
                v = None
            if v is not None:
                self._level = v
            on_read(-1.0 if v is None else v)

        threading.Thread(target=work, daemon=True, name="volume-read").start()

    def _windows(self, fn: Callable[[float], float] | None) -> float | None:
        """Core Audio: read the level, and with `fn` set it to fn(level). The level, or None if that fails."""
        if self._ep_failed:
            return None
        for attempt in range(2):
            try:
                if self._ep is None:
                    self._ep = _EndpointVolume()
                level = self._ep.get()
                if fn is not None:
                    level = fn(level)
                    self._ep.set(level)
                    self.on_level(level)
                return level
            except Exception:
                if self._ep is not None:            # the speakers changed: fetch the new default once
                    try:
                        self._ep.release()
                    except Exception:
                        pass
                    self._ep = None
                if attempt:
                    log.warning("can't set the volume through Core Audio; using the volume keys", exc_info=True)
                    self._ep_failed = True
        return None

    def _change_windows(self, steps: int) -> None:
        if not steps:
            return
        if self._windows(lambda cur: max(0.0, min(1.0, round(cur / STEP + steps) * STEP))) is not None:
            return
        from . import winapi
        key = "volume_up" if steps > 0 else "volume_down"
        for _ in range(abs(steps)):                     # each key press is 2 %, like a slider step
            winapi.press_keys(key)
        self.on_level(-1.0)

    def _posix_worker(self) -> None:
        while True:
            with self._lock:
                steps, self._pending = self._pending, 0
                target, self._target = self._target, None
                if not steps and target is None:
                    self._busy = False
                    return
            try:
                if target is not None:
                    cur = target
                else:
                    cur = _posix_get() if self._level is None else self._level
                    if cur is None:
                        cur = 0.5
                level = max(0.0, min(1.0, round(cur / STEP + steps) * STEP))
                if _posix_set(level):
                    self._level = level
                    self.on_level(level)
            except Exception:
                log.debug("volume change failed", exc_info=True)

    def forget(self) -> None:
        """Read the level afresh next time (something else may have changed it since)."""
        self._level = None

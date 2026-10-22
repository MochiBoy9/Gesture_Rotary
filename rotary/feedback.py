"""Sounds and speech through the system itself: no media framework to load or ship.
Windows: winsound + SAPI. macOS: afplay + say. Linux: paplay / pw-play / aplay + spd-say / espeak."""
from __future__ import annotations

import ctypes
import logging
import shutil
import subprocess
import sys
import tempfile
import wave
from ctypes import wintypes
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)
RATE = 44100


def _write_wav(path: Path, samples: np.ndarray) -> None:
    data = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)


def _waves() -> dict[str, np.ndarray]:
    t = np.arange(int(RATE * 0.035)) / RATE
    tick = 0.32 * np.sin(2 * np.pi * 2300 * t) * np.exp(-t * 260) + 0.18 * np.sin(2 * np.pi * 900 * t) * np.exp(-t * 180)
    t2 = np.arange(int(RATE * 0.22)) / RATE
    conf = (0.22 * np.sin(2 * np.pi * 880 * t2) * np.exp(-t2 * 22)
            + 0.18 * np.sin(2 * np.pi * 1318.5 * t2) * np.exp(-np.clip(t2 - 0.06, 0, None) * 20) * (t2 > 0.06))
    t3 = np.arange(int(RATE * 0.12)) / RATE
    openr = 0.16 * np.sin(2 * np.pi * (520 + 900 * t3) * t3) * np.exp(-t3 * 30)
    return {"tick": tick, "confirm": conf, "open": openr}


class Sounds:
    """Short UI sounds. The volume is baked into the files (winsound has no volume control)."""
    BASE = {"tick": 0.9, "confirm": 0.8, "open": 0.8}

    def __init__(self, enabled: bool, volume: float = 0.6):
        self.enabled = enabled
        self.dir = Path(tempfile.gettempdir()) / "gesture-rotary"
        self.files: dict[str, str] = {}
        self._volume = -1.0
        self.set_volume(volume)

    def set_volume(self, v: float) -> None:
        v = round(max(0.0, min(1.0, float(v))), 2)
        if v == self._volume:
            return
        self._volume = v
        try:
            self.dir.mkdir(exist_ok=True)
            for name, s in _waves().items():
                p = self.dir / f"{name}-{int(v * 100)}.wav"
                if not p.exists():
                    _write_wav(p, s * v * self.BASE[name])
                self.files[name] = str(p)
        except OSError as e:
            log.info("sounds unavailable: %s", e)
            self.files = {}

    def play(self, name: str) -> None:
        if not (self.enabled and name in self.files):
            return
        if sys.platform != "win32":
            _play_posix(self.files[name])
            return
        import winsound
        try:
            winsound.PlaySound(self.files[name], winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except RuntimeError:
            pass


_player: list[str] | None = None


def _play_posix(path: str) -> None:
    """Fire and forget: the sounds are a fraction of a second long."""
    global _player
    if _player is None:
        if sys.platform == "darwin":
            _player = ["afplay"]
        else:
            _player = next(([p] + extra for p, extra in (("paplay", []), ("pw-play", []), ("aplay", ["-q"]))
                            if shutil.which(p)), [])
    if not _player:
        return
    try:
        subprocess.Popen(_player + [path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- speech (SAPI 5 over raw COM)
class _GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, s: str) -> "_GUID":
        g = cls()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
        return g


CLSID_SpVoice = "{96749377-3391-11D2-9EE3-00C04F797396}"
IID_ISpVoice = "{6C44DF74-72B9-4992-A1EC-EF996E0422D4}"
SPF_ASYNC, SPF_PURGEBEFORESPEAK, SPF_IS_NOT_XML = 1, 2, 16
# ISpVoice vtable slots (IUnknown 3 + ISpNotifySource 7 + ISpEventSource 3 come first)
_SPEAK, _SET_RATE, _SET_VOLUME, _GET_VOLUME = 20, 28, 30, 31


class Voice:
    """The default Windows voice. Must be used from one thread (the UI thread)."""

    def __init__(self):
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)          # apartment-threaded; fine if already set up
        self._p = ctypes.c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(_GUID.parse(CLSID_SpVoice)), None, 0x17,
                                             ctypes.byref(_GUID.parse(IID_ISpVoice)), ctypes.byref(self._p))
        self._vt = ctypes.cast(self._p, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    def _fn(self, slot: int, *argtypes):
        return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(self._vt[slot])

    def speak(self, text: str) -> None:
        self._fn(_SPEAK, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p)(
            self._p, text, SPF_ASYNC | SPF_PURGEBEFORESPEAK | SPF_IS_NOT_XML, None)

    def stop(self) -> None:
        self._fn(_SPEAK, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_void_p)(
            self._p, None, SPF_ASYNC | SPF_PURGEBEFORESPEAK, None)

    def set_volume(self, v: int) -> None:
        self._fn(_SET_VOLUME, ctypes.c_ushort)(self._p, max(0, min(100, int(v))))

    def volume(self) -> int:
        out = ctypes.c_ushort()
        self._fn(_GET_VOLUME, ctypes.POINTER(ctypes.c_ushort))(self._p, ctypes.byref(out))
        return out.value

    def set_rate(self, r: int) -> None:
        self._fn(_SET_RATE, ctypes.c_long)(self._p, max(-10, min(10, int(r))))


class CommandVoice:
    """macOS `say`, or speech-dispatcher / eSpeak on Linux. A new phrase cuts off the one before it."""

    def __init__(self):
        if sys.platform == "darwin":
            self.cmd = ["say", "-r", "220"]
        elif shutil.which("spd-say"):
            self.cmd = ["spd-say", "-C"]           # -C: cancel what's being said; spd-say queues by itself
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                raise OSError("no speech synthesizer (install speech-dispatcher or espeak-ng)")
            self.cmd = [exe, "-s", "190"]
        self.proc: subprocess.Popen | None = None

    def speak(self, text: str) -> None:
        if self.cmd[0] == "spd-say":
            subprocess.run(["spd-say", "-C"], capture_output=True, timeout=2)
            args = ["spd-say", text]
        else:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
            args = self.cmd + ["--", text]
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)

    def set_rate(self, r: int) -> None:
        pass


class Speaker:
    """Speaks item names. The voice starts the first time something is said."""

    def __init__(self):
        self.enabled = False
        self.voice: Voice | CommandVoice | None = None
        self._failed = False

    def say(self, text: str) -> None:
        if not self.enabled or not text or self._failed:
            return
        if sys.platform != "win32":
            try:
                if self.voice is None:
                    self.voice = CommandVoice()
                self.voice.speak(text)
            except (OSError, subprocess.SubprocessError) as e:
                log.info("speech unavailable: %s", e)
                self._failed = True
            return
        try:
            if self.voice is None:
                self.voice = Voice()
                self.voice.set_rate(1)
            self.voice.speak(text)
        except OSError as e:
            log.info("speech unavailable: %s", e)
            self._failed = True

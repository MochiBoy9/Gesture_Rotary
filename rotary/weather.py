"""The weather for the rotary's clock: what it's like outside right now, as one of a few icons and a temperature.

It comes from wttr.in, which needs no account or key and finds a rough location from the internet address the
request comes from (or uses the place in `appearance.weather_place`). It's read when the app starts and every
half hour after that, on a background thread; a failed read just leaves the icon out."""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

URL = "https://wttr.in/{place}?format=j1"
REFRESH_MINUTES = 30
STALE_HOURS = 3                    # an older reading isn't shown

# wttr.in's (WorldWeatherOnline) condition codes, by the icon they get
_CODES = {
    "clear": {113},
    "partly": {116},
    "cloudy": {119, 122},
    "fog": {143, 248, 260},
    "rain": {176, 263, 266, 281, 284, 293, 296, 299, 302, 305, 308, 311, 314, 353, 356, 359},
    "snow": {179, 182, 185, 227, 230, 317, 320, 323, 326, 329, 332, 335, 338, 350, 362, 365, 368, 371, 374, 377},
    "storm": {200, 386, 389, 392, 395},
}
KINDS = tuple(_CODES)


def kind_for(code: int) -> str:
    return next((k for k, codes in _CODES.items() if code in codes), "cloudy")


@dataclass
class Weather:
    kind: str                      # clear | partly | cloudy | fog | rain | snow | storm
    temp_c: float
    temp_f: float
    night: bool = False
    text: str = ""                 # "Light rain"
    at: float = 0.0                # time.time() it was read

    def temperature(self, fahrenheit: bool) -> str:
        return f"{round(self.temp_f if fahrenheit else self.temp_c):.0f}°"


def _clock_hour(s: str) -> float | None:
    """'07:12 AM' → 7.2"""
    try:
        t = time.strptime(s.strip(), "%I:%M %p")
    except (ValueError, AttributeError):
        return None
    return t.tm_hour + t.tm_min / 60


def parse(data: dict, now: time.struct_time | None = None) -> Weather | None:
    """wttr.in's j1 JSON → Weather (None if it doesn't say)."""
    try:
        cur = data["current_condition"][0]
        code = int(cur["weatherCode"])
        temp_c, temp_f = float(cur["temp_C"]), float(cur["temp_F"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    text = ""
    try:
        text = str(cur["weatherDesc"][0]["value"]).strip()
    except (KeyError, IndexError, TypeError):
        pass
    now = now or time.localtime()
    hour = now.tm_hour + now.tm_min / 60
    rise, sset = 6.5, 19.0
    try:
        astro = data["weather"][0]["astronomy"][0]
        rise = _clock_hour(astro["sunrise"]) or rise
        sset = _clock_hour(astro["sunset"]) or sset
    except (KeyError, IndexError, TypeError):
        pass
    return Weather(kind_for(code), temp_c, temp_f, not (rise <= hour < sset), text, time.time())


def fetch(place: str = "", timeout: float = 8.0) -> Weather | None:
    url = URL.format(place=urllib.parse.quote(place.strip()))
    from .assist import _ssl_context        # the packaged Mac app has no system CA path of its own
    req = urllib.request.Request(url, headers={"User-Agent": "RotaryUI", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        return parse(json.loads(r.read(2_000_000).decode("utf-8", "replace")))


class WeatherWatcher(QObject):
    """Reads the weather now and every half hour while switched on; `changed` carries a Weather (or None)."""
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.enabled = False
        self.place = ""
        self.current: Weather | None = None
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MINUTES * 60 * 1000)
        self._timer.timeout.connect(self.refresh)
        self.changed.connect(self._store)          # first, so later listeners see `current` already set

    def configure(self, enabled: bool, place: str = "") -> None:
        place = (place or "").strip()
        was = (self.enabled, self.place)
        self.enabled, self.place = bool(enabled), place
        if not self.enabled:
            self._timer.stop()
            if self.current is not None:
                self.changed.emit(None)
            return
        if not self._timer.isActive():
            self._timer.start()
        if was != (self.enabled, self.place) or self.current is None:
            self.refresh()

    def fresh(self) -> Weather | None:
        w = self.current
        return w if (self.enabled and w is not None and time.time() - w.at < STALE_HOURS * 3600) else None

    def refresh(self) -> None:
        if not self.enabled or self._busy:
            return
        self._busy = True
        place = self.place

        def work():
            w = None
            try:
                w = fetch(place)
            except Exception as e:                   # offline, blocked, or the service is down
                log.info("weather unavailable: %s", e)
            finally:
                self._busy = False
            if w is not None:
                self.changed.emit(w)

        threading.Thread(target=work, daemon=True, name="weather").start()

    def _store(self, w) -> None:
        self.current = w

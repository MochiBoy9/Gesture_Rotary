"""The first-run tour: a short series of cards that show how to use RotaryUI.

Pure Python: no Qt. `steps_for(ctx)` builds the cards for this user (camera or mouse, their gesture
settings, their shortcuts) and `Tour` walks through them. ui/tutorial.py draws them.

A card can have a goal: an engine event ("open", "select", "execute", "close", "volume") or a snapshot
flag ("presented", "gripping", "pointing", "pinching", "sliding"). When the user does it, the card ticks
and moves on by itself; Next always works too, so nobody gets stuck on a gesture their camera can't see.

Adding a card for a new feature: call `register(Step(...), after="<key>")` once at import time (from the
feature's own module). `when` decides who sees it, e.g. `when=lambda ctx: ctx.camera` for a gesture.
The text may use {hotkey}, {assist_key}, {hold} and {dwell}.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

EVENT_GOALS = ("open", "select", "execute", "close", "volume")
SNAPSHOT_GOALS = ("presented", "gripping", "pointing", "pinching", "sliding")
# what ui/tutorial.py can draw
POSES = ("rotary", "palm", "fist", "point", "two", "pinch", "back", "notch", "mouse", "keys")
MOTIONS = ("", "hold", "close", "tilt", "slide", "updown", "push", "flip", "lower")


@dataclass
class Context:
    """What the tour needs to know about this user."""
    camera: bool = True                 # hand gestures are on
    grip: bool = True                   # a fist opens the rotary
    still: bool = True                  # holding a palm still opens it
    still_seconds: float = 3.0
    turn_style: str = "tilt"            # tilt | move | direct
    pinch: bool = True
    finger: bool = True                 # point and swipe / push
    volume: bool = True                 # two fingers up slide the volume
    resize: bool = True                 # a two-hand pinch resizes the window in front
    dwell_seconds: float = 1.6
    hotkey: str = "Ctrl + Alt + Space"  # '' when off
    assist_key: str = "Win + Alt + A"   # '' when off
    mouse_button: str = "middle"        # middle | back | forward | off
    notch: bool = True                  # the notch is on screen (always, or because there's no camera)

    @classmethod
    def from_config(cls, cfg: dict, hotkey: str, assist_key: str) -> "Context":
        g = cfg.get("gestures") or {}
        gen = cfg.get("general") or {}
        return cls(camera=bool(gen.get("camera", True)),
                   grip=bool(g.get("grip_summon", True)), still=bool(g.get("still_summon", True)),
                   still_seconds=float(g.get("still_seconds", 3.0)), turn_style=str(g.get("turn_style", "tilt")),
                   pinch=bool(g.get("pinch_click", True)),
                   finger=bool(g.get("finger_swipe", True) or g.get("finger_push", True)),
                   volume=bool(g.get("volume_slide", True)), resize=bool(g.get("window_resize", True)),
                   dwell_seconds=float(g.get("dwell_seconds", 1.6)),
                   hotkey=hotkey, assist_key=assist_key, mouse_button=str(gen.get("mouse_button", "middle")),
                   notch=gen.get("notch", "auto") == "on" or (gen.get("notch", "auto") == "auto"
                                                               and not gen.get("camera", True)))

    def fields(self) -> dict:
        return {"hotkey": self.hotkey or "your shortcut", "assist_key": self.assist_key or "its shortcut",
                "hold": _seconds(self.still_seconds), "dwell": _seconds(self.dwell_seconds)}


def _seconds(s: float) -> str:
    s = round(s, 1)
    return f"{s:g} second" + ("" if s == 1 else "s")


@dataclass
class Step:
    key: str
    title: str
    body: str
    pose: str = "rotary"
    motion: str = ""
    goal: str = ""                       # see EVENT_GOALS / SNAPSHOT_GOALS; '' = just read it
    hint: str = ""                       # the "try it" line under the text
    chapter: str = ""                    # small heading above the title
    when: Callable[[Context], bool] | None = field(default=None, compare=False, repr=False)

    def shown(self, ctx: Context) -> bool:
        return self.when is None or bool(self.when(ctx))

    def filled(self, ctx: Context) -> "Step":
        f = ctx.fields()
        return Step(self.key, self.title.format(**f), self.body.format(**f), self.pose, self.motion, self.goal,
                    self.hint.format(**f), self.chapter, self.when)


# --------------------------------------------------------------------------- the cards
def _open_step(ctx: Context) -> Step:
    if ctx.grip:
        body = ("Close your open palm into a fist and the rotary appears straight away."
                + (" Or keep your palm still for {hold}." if ctx.still else ""))
        return Step("open", "Open the rotary", body, "fist", "close", "open", "Try it: open palm, then a fist")
    return Step("open", "Open the rotary", "Keep your palm still for {hold} and the rotary appears.",
                "palm", "hold", "open", "Try it: hold your palm still")


def _turn_step(ctx: Context) -> Step:
    if ctx.turn_style == "move":
        return Step("turn", "Turn the ring", "Slide your hand left or right of where it started and hold it "
                    "there. The ring keeps scrolling until you come back to the middle.", "palm", "slide", "select",
                    "Try it: slide your hand to one side")
    if ctx.turn_style == "direct":
        return Step("turn", "Turn the ring", "Turn your hand like a dial. The ring follows it exactly.",
                    "palm", "tilt", "select", "Try it: turn your hand")
    return Step("turn", "Turn the ring", "Lean your hand left or right, like tipping a glass, and hold it. The "
                "ring keeps scrolling until you straighten your hand again.", "palm", "tilt", "select",
                "Try it: lean your hand to one side")


def _launch_step(ctx: Context) -> Step:
    ways = []
    if ctx.pinch:
        ways.append("pinch your thumb and index finger together")
    ways.append("hold your hand still on an item for {dwell}")
    body = (ways[0][0].upper() + ways[0][1:] + (", or " + ways[1] if len(ways) > 1 else "") + ". "
            "While this tour is open, launching is only practice: nothing actually opens.")
    return Step("launch", "Launch an item", body, "pinch" if ctx.pinch else "palm",
                "" if ctx.pinch else "hold", "execute", "Try it: launch the item at the top")


def _notch_step(ctx: Context) -> Step:
    button = {"middle": "hold the middle mouse button", "back": "press your mouse's back button",
              "forward": "press your mouse's forward button"}.get(ctx.mouse_button, "")
    ways = (["click the small notch at the top of your screen"] if ctx.notch else []) + \
        (["press {hotkey}"] if ctx.hotkey else []) + ([button] if button else [])
    if not ways:
        ways = ["click the notch at the top of your screen (switch it on from the Notch page)"]
    said = ", ".join(ways[:-1]) + (" or " if len(ways) > 1 else "") + ways[-1]
    body = said[0].upper() + said[1:] + ". " + ("All of them open" if len(ways) > 2 else "It opens" if
                                                 len(ways) == 1 else "Both open") + \
        " the same rotary for your mouse and keyboard."
    if not ctx.notch:
        body += " The notch shows itself when there's no camera, or always if you choose so on the Notch page."
    hint = "Try it: " + ("click the notch" if ctx.notch else "press {hotkey}" if ctx.hotkey else ways[-1])
    return Step("notch", "No camera? Use the mouse" if not ctx.notch else "No camera? Use the notch", body,
                "notch" if ctx.notch else "mouse", "", "open", hint, "Mouse and keyboard")


def _camera(ctx: Context) -> bool:
    return ctx.camera


CORE: list[Step | Callable[[Context], Step]] = [
    lambda ctx: Step("welcome", "Welcome to RotaryUI",
                     ("A one-minute tour: how to open the rotary with your hand, turn it, launch things, and how "
                      "to do all of it with a mouse instead." if ctx.camera else
                      "A quick tour: how to open the rotary with your mouse and keyboard, turn it and launch "
                      "things.") + " Skip it whenever you like; you can replay it from Home.", "rotary"),
    Step("palm", "Show your palm",
         "Hold one hand up with your palm toward the camera, about an arm's length away. The note at the top "
         "of the screen turns blue once it sees you.",
         "palm", "hold", "presented", "Try it: raise your hand", "Hand gestures", when=_camera),
    lambda ctx: _open_step(ctx) if ctx.camera else None,
    lambda ctx: _turn_step(ctx) if ctx.camera else None,
    Step("knob", "Or turn it like a knob",
         "Keep your fist closed and twist it, as if turning a knob. The ring clicks over one item at a time and "
         "stays there. Hold it turned for a moment and it keeps turning by itself until you turn back. Open your "
         "hand briefly and close it again to re-grip without moving the ring. Point your index finger to launch.",
         "fist", "tilt", "", "", when=lambda ctx: ctx.camera and ctx.grip),
    lambda ctx: _launch_step(ctx) if ctx.camera else None,
    Step("point", "Point and push",
         "Point with your index finger and move it aside to scroll. Push it toward the camera to click.",
         "point", "push", "pointing", "Try it: point your index finger", when=lambda ctx: ctx.camera and ctx.finger),
    Step("close", "Put it away",
         "Turn your hand round to show the back of it, or just lower it out of view.",
         "back", "flip", "close", "Try it: show the back of your hand", when=_camera),
    Step("volume", "Change the volume",
         "Raise your index and middle fingers, keep the others curled, and slide your hand up or down like a "
         "fader. A volume ring shows up in a corner of the screen, whether the rotary is open or not.",
         "two", "updown", "volume", "Try it: two fingers up, then slide", when=lambda ctx: ctx.camera and ctx.volume),
    Step("winsize", "Resize a window",
         "Pinch with both hands, then pull them apart to make the window in front bigger, or push them together "
         "to make it smaller. Side by side changes the width, one above the other the height, opposite corners "
         "both. Let go of the pinch to stop.",
         "pinch", "slide", "", "", when=lambda ctx: ctx.camera and ctx.resize),
    Step("ignored", "What it ignores",
         "So it doesn't open by accident, it ignores a hand that touches your face, moves fast or stretches, "
         "and a fist that didn't start as an open palm. A hand held up in front of your face still works.",
         "palm", "", when=_camera),
    _notch_step,
    Step("mouse", "Turn and click",
         "Scroll over the ring, or drag it around, to turn it. Click an item to bring it to the top, then click it "
         "again (or the centre) to open it. Right-click or Esc goes back or closes. ← → and Enter work too. The "
         "mouse works on the rotary over any app, even when your hand opened it.",
         "mouse", "", "select", "Try it: scroll while the rotary is open"),
    Step("notch_move", "Move the notch, take calls",
         "Drag the notch along the top, or pull it down and put it anywhere; a middle click sends it home. When "
         "a call rings in (Discord, Teams…) it shows who's calling with Accept and Decline, and Leave while "
         "you're on it.",
         "notch", ""),
    Step("modes", "Slides, videos and Quick nav",
         "Over a slideshow the rotary turns into a slides ring, and over a video it scrubs through the video. "
         "Apps marked with a chevron open a second ring of their own actions.",
         "rotary", "", chapter="More"),
    Step("assist", "Screen assist",
         "Press {assist_key} and an AI reads your screen and answers on the notch: the question on it, or a short "
         "summary if there isn't one. Hover the notch for the longer answer. Choose a free service on the Screen "
         "assist page.",
         "keys", "", when=lambda ctx: bool(ctx.assist_key)),
    Step("gestures_later", "Prefer gestures?",
         "Turn the camera on from Home, then replay this tour to learn the hand gestures.",
         "palm", "", when=lambda ctx: not ctx.camera),
    Step("done", "You're all set",
         "Replay this tour any time from Home, from General, or from the tray icon's menu.", "rotary"),
]

# Cards added by other features: (step, key of the card to follow)
_EXTRA: list[tuple[Step, str]] = []


def register(step: Step, after: str = "modes") -> None:
    """Add a card to the tour after the card called `after` (or before the last card if there's none)."""
    unregister(step.key)
    _EXTRA.append((step, after))


def unregister(key: str) -> None:
    _EXTRA[:] = [(s, a) for s, a in _EXTRA if s.key != key]


def steps_for(ctx: Context) -> list[Step]:
    out: list[Step] = []
    for entry in CORE:
        s = entry(ctx) if callable(entry) and not isinstance(entry, Step) else entry
        if s is not None and s.shown(ctx):
            out.append(s)
    placed: dict[str, int] = {}          # cards already added after each anchor, so they keep their order
    for s, after in _EXTRA:
        if not s.shown(ctx):
            continue
        keys = [x.key for x in out]
        if after in keys:
            i = keys.index(after) + 1 + placed.get(after, 0)
            placed[after] = placed.get(after, 0) + 1
        else:
            i = len(out) - 1
        out.insert(i, s)
    return [s.filled(ctx) for s in out]


class Tour:
    """Where the user is in the tour, and which goals they have reached."""

    def __init__(self, steps: list[Step]):
        self.steps = steps or steps_for(Context())
        self.index = 0
        self.reached: set[str] = set()

    @property
    def step(self) -> Step:
        return self.steps[self.index]

    @property
    def last(self) -> bool:
        return self.index >= len(self.steps) - 1

    @property
    def done(self) -> bool:
        """The current card's goal has been reached (or it has none)."""
        return not self.step.goal or self.step.key in self.reached

    def go(self, i: int) -> bool:
        i = max(0, min(len(self.steps) - 1, i))
        moved = i != self.index
        self.index = i
        return moved

    def next(self) -> bool:
        return self.go(self.index + 1)

    def back(self) -> bool:
        return self.go(self.index - 1)

    def feed(self, event: str) -> bool:
        """An engine event happened. True if it reached the current card's goal just now."""
        return self._reach(self.step.goal == event and event in EVENT_GOALS)

    def feed_snapshot(self, snap) -> bool:
        g = self.step.goal
        return self._reach(g in SNAPSHOT_GOALS and bool(getattr(snap, g, False)))

    def _reach(self, hit: bool) -> bool:
        if not hit or self.step.key in self.reached:
            return False
        self.reached.add(self.step.key)
        return True

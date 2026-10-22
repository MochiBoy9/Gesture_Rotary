"""Hand features, intent detection and the rotary gesture state machine.

Pure Python + numpy: no Qt, no camera. Everything here is driven by
`GestureEngine.update(features, now)` and is unit-tested with synthetic hands.

Coordinate conventions
----------------------
Frames are mirrored (selfie view) before tracking, so the image looks like a
mirror to the user. Image landmarks are normalised (x right, y down). We scale x
by the frame aspect so distances are in "image heights".

Angles grow clockwise on screen (y points down), so turning the hand clockwise
as the user sees it increases `HandFeatures.angle`. Fingers pointing straight
up is an angle of -90 degrees.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, fields
from enum import Enum

import numpy as np

WRIST = 0
THUMB_TIP = 4
INDEX_MCP, INDEX_TIP = 5, 8
MIDDLE_MCP = 9
PINKY_MCP = 17
# (mcp, pip, dip, tip) for index, middle, ring, pinky
FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))
PALM_POINTS = [0, 5, 9, 13, 17]


# --------------------------------------------------------------------------- #
# Raw hand + extracted features
# --------------------------------------------------------------------------- #
@dataclass
class HandFrame:
    """One tracked hand as produced by the tracker (mirrored image)."""
    landmarks: np.ndarray      # (21, 3) normalised image coords
    world: np.ndarray          # (21, 3) metric coords centred on the hand
    handedness: str            # MediaPipe label, "Left" / "Right"
    score: float
    aspect: float              # frame width / height


@dataclass
class HandFeatures:
    center: tuple[float, float]   # palm centre, image-height units
    scale: float                  # palm length, image-height units
    angle: float                  # hand roll in the image plane, radians
    facing: float                 # +1 palm toward camera, -1 back of hand
    curls: tuple[float, ...]      # index..pinky, 0 = straight, 1 = fully curled
    grip: float                   # 0..1 mean finger curl
    pinch: float                  # thumb-tip to index-tip / palm length
    handedness: str
    raw_facing: float = 0.0       # facing before any handedness flip (calibration)
    tip: tuple[float, float] = (0.0, 0.0)          # index fingertip, image-height units
    index_fs: float = 1.0         # index finger foreshortening: 1 = in the image plane, →0 = pointing at camera
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)  # normalised x0, y0, x1, y1
    in_frame: bool = True         # whole hand visible (not cut by the frame edge)
    handed_conf: float = 1.0      # 0..1 how sure we are of left/right (from HandednessTracker)
    at_face: bool = False         # resting on / in front of the face (set by the app from face boxes)

    @property
    def upright_dev(self) -> float:
        """Degrees away from fingers-straight-up."""
        return abs(math.degrees(wrap_pi(self.angle + math.pi / 2)))


def _norm(v: np.ndarray) -> float:
    return float(np.linalg.norm(v))


def _angle_between(u: np.ndarray, v: np.ndarray) -> float:
    nu, nv = _norm(u), _norm(v)
    if nu < 1e-9 or nv < 1e-9:
        return 0.0
    c = float(np.dot(u, v)) / (nu * nv)
    return math.acos(max(-1.0, min(1.0, c)))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def wrap_pi(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def extract_features(hand: HandFrame, flip_handedness: bool = False, handedness: str | None = None,
                     handed_conf: float = 1.0) -> HandFeatures:
    label = handedness or hand.handedness
    p = hand.landmarks[:, :2].astype(np.float64).copy()
    p[:, 0] *= hand.aspect
    w = hand.world.astype(np.float64)

    right = label == "Right"
    # In a mirrored image a right palm facing the camera has its thumb on the
    # left, which makes (index_mcp - wrist) x (pinky_mcp - wrist) positive.
    a = p[INDEX_MCP] - p[WRIST]
    b = p[PINKY_MCP] - p[WRIST]
    sin_ab = (a[0] * b[1] - a[1] * b[0]) / (_norm(a) * _norm(b) + 1e-9)
    raw_facing = sin_ab * (1.0 if right else -1.0)
    facing = -raw_facing if flip_handedness else raw_facing
    sign = 1.0 if (right != flip_handedness) else -1.0

    # Roll: wrist -> middle knuckle, blended with the knuckle line rotated 90deg.
    v1 = p[MIDDLE_MCP] - p[WRIST]
    ang1 = math.atan2(v1[1], v1[0])
    v2 = p[PINKY_MCP] - p[INDEX_MCP]
    ang2 = math.atan2(v2[1], v2[0]) - sign * math.pi / 2
    k = _clamp01(facing * 4.0)  # knuckle line is only meaningful palm-on
    angle = math.atan2(math.sin(ang1) + k * math.sin(ang2), math.cos(ang1) + k * math.cos(ang2))

    # Finger curl from the metric 3D skeleton (rotation invariant).
    curls = []
    for mcp, pip, _dip, tip in FINGERS:
        v0 = w[mcp] - w[WRIST]
        s1 = w[pip] - w[mcp]
        s2 = w[tip] - w[pip]
        bend = _angle_between(v0, s1) + _angle_between(s1, s2)
        c_bend = _clamp01((bend - 0.9) / (2.4 - 0.9))
        reach = _norm(w[tip] - w[WRIST]) / (_norm(v0) + 1e-9)
        c_reach = _clamp01((1.75 - reach) / (1.75 - 1.15))
        curls.append(0.5 * c_bend + 0.5 * c_reach)

    palm_len_w = _norm(w[MIDDLE_MCP] - w[WRIST]) + 1e-9
    pinch = _norm(w[THUMB_TIP] - w[INDEX_TIP]) / palm_len_w

    center = p[PALM_POINTS].mean(axis=0)
    palm_len_img = _norm(p[MIDDLE_MCP] - p[WRIST])
    scale = max(palm_len_img, _norm(p[PINKY_MCP] - p[INDEX_MCP]) * 1.3, 1e-4)

    # Index foreshortening: on-screen finger length vs its true 3D length.
    px_per_m = scale / palm_len_w
    idx_world = _norm(w[INDEX_TIP] - w[INDEX_MCP]) + 1e-9
    index_fs = _norm(p[INDEX_TIP] - p[INDEX_MCP]) / (idx_world * px_per_m)

    lm = hand.landmarks
    x0, y0 = float(lm[:, 0].min()), float(lm[:, 1].min())
    x1, y1 = float(lm[:, 0].max()), float(lm[:, 1].max())
    in_frame = x0 > 0.01 and y0 > 0.01 and x1 < 0.99 and y1 < 0.99

    return HandFeatures(
        center=(float(center[0]), float(center[1])),
        scale=float(scale),
        angle=float(angle),
        facing=float(facing),
        curls=tuple(curls),
        grip=float(sum(curls) / 4.0),
        pinch=float(pinch),
        handedness=label,
        raw_facing=float(raw_facing),
        tip=(float(p[INDEX_TIP][0]), float(p[INDEX_TIP][1])),
        index_fs=float(index_fs),
        bbox=(x0, y0, x1, y1),
        in_frame=in_frame,
        handed_conf=handed_conf,
    )


class HandednessTracker:
    """Left/right for one tracked hand, voted over time.

    MediaPipe's per-frame label is reliable for open hands but flickers for fists,
    and palm-vs-back depends on it. Open-hand frames vote strongly, fist frames
    barely, so a fist that arrives without ever showing its palm stays uncertain."""

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.p_right = 0.5
        self._last_t: float | None = None

    def update(self, label: str, score: float, grip: float, now: float) -> tuple[str, float]:
        if self._last_t is None or now - self._last_t > 0.6:
            self.p_right = 0.5
        self._last_t = now
        obs = score if label == "Right" else 1.0 - score
        w = 0.25 if grip < 0.4 else 0.03
        self.p_right += w * (obs - self.p_right)
        return ("Right" if self.p_right >= 0.5 else "Left"), abs(self.p_right - 0.5) * 2.0


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #
class OneEuro:
    """One Euro filter (Casiez et al.) — low jitter when still, low lag when moving."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.0, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self) -> None:
        self.t = None
        self.x = 0.0
        self.dx = 0.0

    @staticmethod
    def _alpha(dt: float, cutoff: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float) -> float:
        if self.t is None:
            self.t, self.x, self.dx = t, x, 0.0
            return x
        dt = max(t - self.t, 1e-3)
        dx = (x - self.x) / dt
        ad = self._alpha(dt, self.d_cutoff)
        self.dx = ad * dx + (1 - ad) * self.dx
        a = self._alpha(dt, self.min_cutoff + self.beta * abs(self.dx))
        self.x = a * x + (1 - a) * self.x
        self.t = t
        return self.x


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
INTENT_PROFILES = {
    #             facing  upright  handed  open-palm  cooldown  grip-hold  max-speed
    "relaxed":  (0.22,    80.0,    0.45,   False,     0.8,      0.00,      4.0),
    "balanced": (0.35,    60.0,    0.60,   True,      1.2,      0.06,      2.5),
    "strict":   (0.45,    40.0,    0.75,   True,      1.8,      0.20,      1.6),
}


class Phase(str, Enum):
    IDLE = "idle"
    OPEN = "open"
    EXECUTING = "executing"


@dataclass
class GestureSettings:
    # opening
    grip_summon: bool = True          # make a fist to open
    still_summon: bool = True         # hold an open palm still to open
    still_seconds: float = 3.0
    large_move: float = 0.45          # movement (palm lengths) that counts as "large"
    intent: str = "balanced"          # relaxed | balanced | strict
    ignore_near_face: bool = True
    grab_window: float = 1.5          # fist must follow an open palm within this many seconds
    min_hand_size: float = 0.07       # palm length in image heights (ignore far-away hands)
    # turning
    turn_style: str = "tilt"          # tilt: lean the hand · move: slide it sideways · direct: ring follows the hand
    degrees_per_item: float = 22.0    # direct: roll per item · tilt: roll that starts scrolling
    move_distance: float = 0.8        # move: palm lengths of sideways travel that start scrolling
    scroll_speed: float = 1.0         # tilt / move: repeat-rate multiplier
    detent_hysteresis: float = 0.12
    # launching
    dwell_seconds: float = 1.6
    pinch_click: bool = True
    finger_swipe: bool = True
    finger_push: bool = True
    push_sensitivity: float = 0.5     # 0 = firm push needed, 1 = light push
    swipe_distance: float = 0.7       # palm lengths the fingertip moves sideways to start scrolling
    # closing
    lost_close_seconds: float = 1.5
    dismiss_seconds: float = 0.6
    idle_timeout: float = 15.0        # close after this long without input (0 = never)
    execute_cooldown: float = 0.7
    # recognition
    flip_handedness: bool = True
    require_palm: bool = True
    either_side: bool = False         # palm or back of the hand both count (limited forearm rotation)
    facing_on: float = 0.18
    facing_off: float = 0.06
    grip_on: float = 0.60
    grip_off: float = 0.40
    pinch_on: float = 0.30
    pinch_off: float = 0.45

    @classmethod
    def from_dict(cls, d: dict | None) -> "GestureSettings":
        d = d or {}
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @property
    def profile(self):
        return INTENT_PROFILES.get(self.intent, INTENT_PROFILES["balanced"])


@dataclass
class EngineSnapshot:
    phase: Phase = Phase.IDLE
    hand_present: bool = False
    facing: bool = False
    facing_value: float = 0.0
    presented: bool = False        # hand held up deliberately (could open the rotary)
    at_face: bool = False
    gripping: bool = False
    pinching: bool = False
    pointing: bool = False
    grip_value: float = 0.0
    arming: float = 0.0            # 0..1 stillness progress
    rearm_needed: bool = False
    cooling: bool = False
    position: float = 0.0          # continuous dial position (items)
    selected: int = 0              # index into items
    dwell: float = 0.0             # 0..1
    push: float = 0.0              # 0..1 finger push progress
    lean: float = 0.0              # -1..1 how far the hand/finger leans toward scrolling (+ = clockwise/right)
    scrolling: int = 0             # -1 / 0 / +1 while auto-scrolling
    pointer: tuple[float, float] = (0.0, 0.0)   # fingertip offset in palm lengths
    opened_by: str = ""
    grip_turned: bool = False      # gripping and has turned since grabbing
    interacted: bool = False


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class GestureEngine:
    def __init__(self, n_items: int, settings: GestureSettings | None = None):
        self.s = settings or GestureSettings()
        self.n = max(1, n_items)
        self._ang_f = OneEuro(min_cutoff=1.5, beta=0.6)
        self._cx_f = OneEuro(min_cutoff=1.0, beta=0.8)
        self._cy_f = OneEuro(min_cutoff=1.0, beta=0.8)
        self.phase = Phase.IDLE
        self.paused = False
        self.opened_by = ""
        # hand state
        self._present = False
        self._f: HandFeatures | None = None
        self._last_seen: float | None = None
        self._facing_ema = 0.0
        self._grip_ema = 0.0
        self.facing = False
        self.gripping = False
        self.pinching = False
        self.pointing = False
        self._grip_frames = 0
        self._pinch_frames = 0
        self._point_frames = 0
        self._pinch_edge = False
        self._ang_prev: float | None = None
        self._ang_unwrapped = 0.0
        self._ang = 0.0
        self._cx = self._cy = 0.0
        self._scale = 0.1
        self._speed = 0.0
        self._prev_c: tuple[float, float, float] | None = None
        # intent / arming
        self.grip_armed = True
        self._ungrip_since: float | None = None
        self._grip_since: float | None = None
        self.still_armed = True
        self._anchor: tuple[float, float] | None = None
        self._still_start = 0.0
        self._arming = 0.0
        self._open_palm_t = -1e9
        self._open_palm_c = (0.0, 0.0)
        self._cooldown_until = 0.0
        self._presented = False
        # open state
        self.sel_raw = 0
        self.position = 0.0
        self._base_angle = 0.0
        self._base_cx = 0.0
        self._base_pos = 0.0
        self._rebase = True
        self._sel_since = 0.0
        self._last_interaction = 0.0
        self._interacted = False
        self._grip_start_sel: int | None = None
        self._lost_since: float | None = None
        self._back_since: float | None = None
        self._dwell = 0.0
        self._exec_until = 0.0
        self._seen_open = True
        # finger mode
        self._point_since = 0.0
        self._tips: deque = deque()          # (t, x, y, index_fs, scale)
        self._last_swipe = 0.0
        self._push = 0.0
        self._pointer = (0.0, 0.0)
        self._point_origin = (0.0, 0.0)
        self._point_angle = 0.0
        self._lean = 0.0
        self._scroll_dir = 0
        self._next_step = 0.0

    # ------------------------------------------------------------------ api
    def set_item_count(self, n: int) -> None:
        self.n = max(1, n)
        self.sel_raw %= self.n
        self.position = float(self.sel_raw)

    @property
    def selected(self) -> int:
        return self.sel_raw % self.n

    @property
    def step_degrees(self) -> float:
        # Keep every item reachable within ~100 degrees of wrist roll either way.
        half = max(1.0, self.n / 2.0)
        return min(self.s.degrees_per_item, 100.0 / half)

    def force_open(self, now: float) -> list:
        if self.phase != Phase.IDLE:
            return []
        return self._open("manual", now)

    def force_close(self, now: float, reason: str = "manual") -> list:
        if self.phase != Phase.OPEN:
            return []
        return self._close(reason, now)

    def key_step(self, delta: int, now: float) -> list:
        """Keyboard / switch access: move one item."""
        if self.phase != Phase.OPEN or self.n <= 1:
            return []
        self._scroll_dir = 0
        return self._step(delta, now)

    def key_execute(self, now: float) -> list:
        if self.phase != Phase.OPEN:
            return []
        return self._execute(now)

    def enter_level(self, n: int, now: float, selected: int = 0) -> None:
        """Swap the ring's contents (Quick nav / Back) and keep going from a neutral hand."""
        self.n = max(1, n)
        self.sel_raw = selected % self.n
        self.position = float(self.sel_raw)
        self._base_pos = self.position
        self.phase = Phase.OPEN
        self._interacted = False
        self._sel_since = now
        self._last_interaction = now
        self._rebase = True
        self._scroll_dir = 0
        self._lean = 0.0
        self._dwell = 0.0
        self._push = 0.0
        self._pinch_edge = False
        self._tips.clear()
        self._lost_since = None
        self._back_since = None
        self._grip_start_sel = self.sel_raw if self.gripping else None
        if self._f is not None:
            self._point_origin = self._f.tip
            self._point_since = now
            self._point_angle = self._ang

    def snapshot(self) -> EngineSnapshot:
        f = self._f
        return EngineSnapshot(
            phase=self.phase,
            hand_present=self._present,
            facing=self.facing,
            facing_value=self._facing_ema,
            presented=self._presented,
            at_face=bool(f and f.at_face and self._present),
            gripping=self.gripping,
            pinching=self.pinching,
            pointing=self.pointing,
            grip_value=self._grip_ema,
            arming=self._arming,
            rearm_needed=self.phase == Phase.IDLE and self._presented and not self.still_armed
            and self.s.still_summon,
            cooling=self.phase == Phase.IDLE and self._last_now < self._cooldown_until,
            position=self.position,
            selected=self.selected,
            dwell=self._dwell,
            push=self._push,
            lean=max(-1.0, min(1.0, self._lean)),
            scrolling=self._scroll_dir,
            pointer=self._pointer,
            opened_by=self.opened_by,
            grip_turned=self.gripping and self._grip_start_sel is not None
            and self.sel_raw != self._grip_start_sel,
            interacted=self._interacted,
        )

    _last_now = 0.0

    # --------------------------------------------------------------- update
    def update(self, f: HandFeatures | None, now: float) -> list:
        events: list = []
        s = self.s
        self._last_now = now
        if self.paused:
            f = None

        if f is not None:
            self._ingest(f, now)
        elif self._last_seen is None or now - self._last_seen > 0.3:
            self._reset_hand()
        self._present = f is not None
        self._f = f
        tracked = self._present and (self.facing or not s.require_palm)

        # Re-arm grip once the hand is open (or gone) for a moment.
        if not self.gripping:
            self._grip_since = None
            if self._ungrip_since is None:
                self._ungrip_since = now
            if now - self._ungrip_since >= 0.15:
                self.grip_armed = True
        else:
            self._ungrip_since = None
            if self._grip_since is None:
                self._grip_since = now
        # Stillness re-arms when the hand leaves.
        if self._last_seen is None or now - self._last_seen > 0.5:
            self.still_armed = True

        self._presented = bool(tracked and self._is_presented(f))

        if self.phase == Phase.IDLE:
            events += self._update_idle(tracked, now)
        elif self.phase == Phase.OPEN:
            events += self._update_open(tracked, now)
        elif self.phase == Phase.EXECUTING:
            self._arming = 0.0
            if now >= self._exec_until:
                self.phase = Phase.IDLE
                self._anchor = None
                self._cooldown_until = now + s.profile[4]
                events.append(("closed", "executed"))
        return events

    # ------------------------------------------------------------ internals
    def _reset_hand(self) -> None:
        self._ang_f.reset()
        self._cx_f.reset()
        self._cy_f.reset()
        self._ang_prev = None
        self._prev_c = None
        self._speed = 0.0
        self._grip_frames = self._pinch_frames = self._point_frames = 0
        self.gripping = self.pinching = self.pointing = False
        self.facing = False
        self._facing_ema = 0.0
        self._grip_ema = 0.0
        self._tips.clear()
        self._push = 0.0

    def _ingest(self, f: HandFeatures, now: float) -> None:
        s = self.s
        fresh = self._last_seen is None or now - self._last_seen > 0.3
        facing = abs(f.facing) if s.either_side else f.facing
        if fresh:
            self._reset_hand()
            self._facing_ema = facing
            self._grip_ema = f.grip
        else:
            self._facing_ema += 0.45 * (facing - self._facing_ema)
            self._grip_ema += 0.5 * (f.grip - self._grip_ema)
        self._last_seen = now

        if self.facing:
            if self._facing_ema < s.facing_off:
                self.facing = False
        elif self._facing_ema > s.facing_on:
            self.facing = True

        if self._ang_prev is None:
            self._ang_unwrapped = f.angle
        else:
            self._ang_unwrapped += wrap_pi(f.angle - self._ang_prev)
        self._ang_prev = f.angle
        self._ang = self._ang_f(self._ang_unwrapped, now)
        self._cx = self._cx_f(f.center[0], now)
        self._cy = self._cy_f(f.center[1], now)
        self._scale = f.scale

        # Hand speed in palm lengths per second (lightly smoothed).
        if self._prev_c is not None:
            dt = max(now - self._prev_c[2], 1e-3)
            v = math.hypot(self._cx - self._prev_c[0], self._cy - self._prev_c[1]) / max(f.scale, 1e-4) / dt
            self._speed += 0.35 * (v - self._speed)
        self._prev_c = (self._cx, self._cy, now)

        # Grip: hysteresis + two-frame debounce on the way in.
        g = self._grip_ema
        if self.gripping:
            if g < s.grip_off:
                self.gripping = False
                self._grip_frames = 0
        else:
            curled = sum(c > 0.5 for c in f.curls)
            if g > s.grip_on and curled >= 3 and f.curls[0] > 0.45:   # index curled too (not pointing)
                self._grip_frames += 1
                if self._grip_frames >= 2:
                    self.gripping = True
            else:
                self._grip_frames = 0

        # Pointing: index straight, the other three curled.
        others = (f.curls[1] + f.curls[2] + f.curls[3]) / 3.0
        is_point = f.curls[0] < 0.35 and others > 0.6
        if self.pointing:
            if f.curls[0] > 0.5 or others < 0.45:
                self._point_frames -= 1
                if self._point_frames <= -3:
                    self.pointing = False
                    self._point_frames = 0
            else:
                self._point_frames = 0
        elif is_point:
            self._point_frames += 1
            if self._point_frames >= 3:
                self.pointing = True
                self._point_frames = 0
                self._point_since = now
                self._point_origin = f.tip
                self._point_angle = self._ang
                self._scroll_dir = 0
                self._tips.clear()
        else:
            self._point_frames = 0

        # Pinch only counts with the other fingers open.
        others_open = others < 0.5
        if self.pinching:
            if f.pinch > s.pinch_off or self.gripping:
                self.pinching = False
                self._pinch_frames = 0
        elif f.pinch < s.pinch_on and others_open and not self.gripping:
            self._pinch_frames += 1
            if self._pinch_frames >= 3:
                self.pinching = True
                self._pinch_edge = True
        else:
            self._pinch_frames = 0

    def _is_presented(self, f: HandFeatures | None) -> bool:
        """A hand held up on purpose: palm clearly toward the camera, roughly upright,
        fully in view, not tiny, not resting against the face, and we know which hand it is."""
        if f is None:
            return False
        s = self.s
        min_facing, max_tilt, min_handed = s.profile[0], s.profile[1], s.profile[2]
        return (self._facing_ema >= min_facing and f.upright_dev <= max_tilt and f.in_frame
                and f.scale >= s.min_hand_size and f.handed_conf >= min_handed
                and not (s.ignore_near_face and f.at_face))

    def _update_idle(self, tracked: bool, now: float) -> list:
        s = self.s
        f = self._f
        _, _, _, need_open_palm, _, grip_hold, max_speed = s.profile
        if not tracked or f is None:
            self._anchor = None
            self._arming = 0.0
            return []
        cooling = now < self._cooldown_until
        open_hand = self._grip_ema < 0.3

        if self._presented and open_hand and self._speed < max_speed:
            self._open_palm_t = now
            self._open_palm_c = (self._cx, self._cy)

        # ---- fist: a deliberate grab (open palm → fist, steady, not at the face)
        if s.grip_summon and self.gripping and self.grip_armed and not cooling:
            fist_ok = (self._facing_ema >= s.profile[0] * 0.8 and f.in_frame
                       and f.scale >= s.min_hand_size and self._speed < max_speed
                       and not (s.ignore_near_face and f.at_face))
            if need_open_palm:
                moved = math.hypot(self._cx - self._open_palm_c[0], self._cy - self._open_palm_c[1]) / max(f.scale, 1e-4)
                fist_ok = fist_ok and now - self._open_palm_t <= s.grab_window and moved <= 0.9
            held = self._grip_since is not None and now - self._grip_since >= grip_hold
            if fist_ok and held:
                return self._open("grip", now)
            if not fist_ok:
                self.grip_armed = False      # this fist doesn't count; open the hand to try again

        # ---- hold an open palm still
        if not (s.still_summon and self._presented and open_hand):
            self._anchor = None
            self._arming = 0.0
            return []
        if self._anchor is None:
            self._anchor = (self._cx, self._cy)
            self._still_start = now
        moved = math.hypot(self._cx - self._anchor[0], self._cy - self._anchor[1]) / max(self._scale, 1e-4)
        if moved > s.large_move:
            self._anchor = (self._cx, self._cy)
            self._still_start = now
            self.still_armed = True
        if self.still_armed and not cooling:
            self._arming = min(1.0, (now - self._still_start) / s.still_seconds)
            if self._arming >= 1.0:
                return self._open("still", now)
        else:
            self._arming = 0.0
            if cooling:
                self._still_start = now
        return []

    def _open(self, reason: str, now: float) -> list:
        self.phase = Phase.OPEN
        self.opened_by = reason
        self._arming = 0.0
        self._rebase = True
        self._base_pos = float(self.sel_raw)
        self.position = float(self.sel_raw)
        self._interacted = False
        self._sel_since = now
        self._last_interaction = now
        self._grip_start_sel = self.sel_raw if self.gripping else None
        self._lost_since = None
        self._back_since = None
        self._dwell = 0.0
        self._pinch_edge = False
        self._seen_open = reason != "manual"
        self._tips.clear()
        self._push = 0.0
        self._lean = 0.0
        self._scroll_dir = 0
        if self.gripping:
            self.grip_armed = False
        return [("open", reason)]

    def _close(self, reason: str, now: float) -> list:
        self.phase = Phase.IDLE
        self.still_armed = False
        self.grip_armed = not self.gripping
        self._anchor = None
        self._dwell = 0.0
        self._push = 0.0
        self._cooldown_until = now + self.s.profile[4]
        self._open_palm_t = -1e9
        self.sel_raw %= self.n
        self.position = float(self.sel_raw)
        return [("close", reason)]

    def _execute(self, now: float) -> list:
        self.phase = Phase.EXECUTING
        self._exec_until = now + self.s.execute_cooldown
        self.still_armed = False
        self.grip_armed = False
        self._dwell = 0.0
        self._push = 0.0
        self._grip_start_sel = None
        self._open_palm_t = -1e9
        sel = self.selected
        self.sel_raw = sel
        self.position = float(sel)
        return [("execute", sel)]

    def _step(self, delta: int, now: float, rebase: bool = False) -> list:
        self.sel_raw += delta
        self.position = float(self.sel_raw)
        self._base_pos = self.position
        if rebase:
            self._rebase = True
        self._interacted = True
        self._sel_since = now
        self._last_interaction = now
        return [("select", self.selected)]

    def _tilt_scroll(self, lean: float, now: float) -> list:
        """Joystick-style scrolling: leaning past the threshold (|lean| >= 1) steps once right away,
        then keeps stepping — faster the further you lean — until you come back toward neutral."""
        s = self.s
        self._lean = lean
        if self.n <= 1:
            return []
        a = abs(lean)
        speed = max(0.2, s.scroll_speed)
        if self._scroll_dir == 0:
            if a >= 1.0:
                self._scroll_dir = 1 if lean > 0 else -1
                self._next_step = now + 0.5 / speed
                return self._step(-self._scroll_dir, now)
            return []
        if a < 0.7 or (lean > 0) != (self._scroll_dir > 0):
            self._scroll_dir = 0          # back to neutral: stop
            self._sel_since = now
            return []
        if now >= self._next_step:
            excess = min(1.0, max(0.0, (a - 1.0) / 1.0))
            self._next_step = now + (0.42 - 0.26 * excess) / speed
            return self._step(-self._scroll_dir, now)
        return []

    def _update_fingers(self, now: float) -> list:
        """Index-finger mode: swipe sideways to step, push toward the camera to click."""
        s = self.s
        f = self._f
        self._tips.append((now, f.tip[0], f.tip[1], f.index_fs, f.scale))
        while self._tips and now - self._tips[0][0] > 0.6:
            self._tips.popleft()
        self._pointer = ((f.tip[0] - self._point_origin[0]) / max(f.scale, 1e-4),
                         (f.tip[1] - self._point_origin[1]) / max(f.scale, 1e-4))
        self._last_interaction = now
        settled = now - self._point_since >= 0.25

        # sideways: hold the finger off to one side (or tilt it) to keep scrolling
        if s.finger_swipe and settled:
            lean_x = self._pointer[0] / max(s.swipe_distance, 1e-3)
            lean_t = math.degrees(self._ang - self._point_angle) / max(self.step_degrees, 1e-3)
            lean = lean_x if abs(lean_x) >= abs(lean_t) else lean_t
            ev = self._tilt_scroll(lean, now)
            if ev:
                self._last_swipe = now
                return ev
        else:
            self._lean = 0.0
            self._scroll_dir = 0

        # push: the finger foreshortens (points at the camera) or the hand moves closer
        self._push = 0.0
        if s.finger_push and settled and self._scroll_dir == 0 and len(self._tips) >= 4 \
                and now - self._last_swipe >= 0.3:
            k = 0.5 + max(0.0, min(1.0, s.push_sensitivity))           # 0.5 (firm) .. 1.5 (light)
            need_drop, need_grow = 0.34 / k, 0.18 / k
            window = [t for t in self._tips if now - t[0] <= 0.5]
            fs_max = max(t[3] for t in window)
            sc_min = min(t[4] for t in window)
            drop = (fs_max - f.index_fs) / max(fs_max, 1e-3)
            grow = f.scale / max(sc_min, 1e-4) - 1.0
            lateral = math.hypot(window[-1][1] - window[0][1], window[-1][2] - window[0][2]) / max(f.scale, 1e-4)
            self._push = max(0.0, min(1.0, max(drop / need_drop, grow / need_grow)))
            if self._push >= 1.0 and lateral < 0.6 and fs_max > 0.45:
                return self._execute(now)
        return []

    def _update_open(self, tracked: bool, now: float) -> list:
        s = self.s
        events: list = []
        pinch_edge, self._pinch_edge = self._pinch_edge, False

        if tracked:
            self._seen_open = True
            self._lost_since = None
            self._back_since = None

            if self.pointing:
                if not self._rebase:
                    self._scroll_dir = 0
                self._rebase = True
                self._dwell = 0.0
                return events + self._update_fingers(now)
            self._push = 0.0
            self._pointer = (0.0, 0.0)

            if self._rebase:
                self._base_angle = self._ang
                self._base_cx = self._cx
                self._base_pos = self.position if s.turn_style == "direct" else float(self.sel_raw)
                self._rebase = False
                self._scroll_dir = 0
            delta_deg = math.degrees(self._ang - self._base_angle)

            if s.turn_style in ("tilt", "move"):
                if s.turn_style == "move":
                    lean = (self._cx - self._base_cx) / max(self._scale, 1e-4) / max(s.move_distance, 0.1)
                else:
                    lean = delta_deg / self.step_degrees
                events += self._tilt_scroll(lean, now)
                # the ring leans a little toward the tilt so you can see it coming
                self.position = self.sel_raw - max(-1.0, min(1.0, self._lean)) * 0.45
            else:
                self._lean = 0.0
                self.position = self._base_pos - delta_deg / self.step_degrees
                if abs(self.position - self.sel_raw) > 0.5 + s.detent_hysteresis:
                    self.sel_raw = int(round(self.position))
                    self._interacted = True
                    self._sel_since = now
                    self._last_interaction = now
                    events.append(("select", self.selected))

            # Grab-turn-release.
            if self.gripping:
                if self._grip_start_sel is None:
                    self._grip_start_sel = self.sel_raw
                self._last_interaction = now
            elif self._grip_start_sel is not None:
                turned = self.sel_raw != self._grip_start_sel
                self._grip_start_sel = None
                self._sel_since = now
                if turned:
                    return events + self._execute(now)

            if pinch_edge and s.pinch_click and not self.gripping:
                return events + self._execute(now)

            # Dwell: open hand resting on a detent after turning.
            if s.turn_style in ("tilt", "move"):
                settled = self._scroll_dir == 0 and abs(self._lean) < 0.6
            else:
                settled = abs(self.position - self.sel_raw) < 0.35
            if not settled:
                self._sel_since = now
            if s.dwell_seconds > 0 and self._interacted and not self.gripping:
                self._dwell = min(1.0, (now - self._sel_since) / s.dwell_seconds)
                if self._dwell >= 1.0:
                    return events + self._execute(now)
            else:
                self._dwell = 0.0
        else:
            self._rebase = True
            self._sel_since = now
            self._dwell = 0.0
            self._push = 0.0
            self._lean = 0.0
            self._scroll_dir = 0
            if self._present and self._facing_ema < -0.15:
                self._back_since = self._back_since or now
                if now - self._back_since >= s.dismiss_seconds:
                    return events + self._close("dismiss", now)
            else:
                self._back_since = None
            if not self._present and self._seen_open:
                self._lost_since = self._lost_since or now
                if now - self._lost_since >= s.lost_close_seconds:
                    return events + self._close("lost", now)

        if s.idle_timeout > 0 and now - self._last_interaction >= s.idle_timeout:
            events += self._close("timeout", now)
        return events

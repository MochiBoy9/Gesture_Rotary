"""The rotary: a liquid-glass ring of items that turns with the user's hand."""
from __future__ import annotations

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import QWidget

from ..actions import Item
from ..gestures import EngineSnapshot, Phase
from . import liquid
from .glass import (DISPLAY, ICONS, TEXT, Spring, angle_point, app_icon, black, circle, ease_out_cubic,
                    exclude_from_capture, font, glass_disc, grab_behind, overlay_flags, qcolor, smoothstep,
                    soft_shadow, stroke_rim, white)


def _wrap180(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t, 1.0)


def _canvas(w: float, h: float, dpr: float) -> QPixmap:
    pm = QPixmap(max(1, int(math.ceil(w * dpr))), max(1, int(math.ceil(h * dpr))))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _hq(p: QPainter) -> None:
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                     | QPainter.RenderHint.TextAntialiasing)


class DialPainter:
    """All dial drawing + animation state. Window-agnostic so it can render offscreen.

    Anything that doesn't move while the dial is open (the refracting glass ring and centre disc,
    icon platters, colour glows, the lens' glass) is rendered once into cached pixmaps; each frame
    only composites those and draws what turns, plus the light that moves with it."""

    MARGIN = 84
    PLATTER_R = 27 * 1.3
    PLATTER_PAD = 14

    def __init__(self, items: list[Item], size: int = 600):
        self.items = items
        self.D = size
        self.state = EngineSnapshot()
        self._backdrop: liquid.Backdrop | None = None
        self._backdrop_ver = 0
        self.appear = Spring(0.0, 190.0, 20.0)     # a touch of overshoot
        self.rot = Spring(0.0, 520.0, 36.0)        # snappy follow of the hand, a little click of overshoot
        self.title = Spring(1.0, 240.0, 30.0)
        self.grip_vis = Spring(0.0, 260.0, 30.0)
        self.tracked_vis = Spring(1.0, 200.0, 28.0)
        self.point_vis = Spring(0.0, 240.0, 28.0)
        self.push_vis = Spring(0.0, 420.0, 34.0)
        self.px = Spring(0.0, 300.0, 30.0)
        self.py = Spring(0.0, 300.0, 30.0)
        self.tint = QColor(items[0].tint if items else "#0A84FF")
        self.open_t = 0.0
        self.exec_t: float | None = None
        self.exiting = False
        self._title_dir = 1.0
        self._prev_sel = 0
        self._cur_sel = 0
        self._cache_key = None
        self.text_scale = 1.0
        self.high_contrast = False
        self.reduce_motion = False
        self.controls: dict = {}       # gesture settings, so hints only mention what's switched on
        self.crumb = ""                # app name while inside a Quick nav ring
        self.keyboard = False          # opened from the keyboard shortcut
        self.level_kick = Spring(0.0, 260.0, 22.0)
        self.turned = 0.0              # degrees the primary ring has turned since it opened (360° gauge)
        self.gauge_vis = Spring(0.0, 200.0, 26.0)
        self._gauge_rot = 0.0
        self._appear_kc = (190.0, 20.0)
        self.invalidate()

    def set_accessibility(self, text_scale: float = 1.0, high_contrast: bool = False,
                          reduce_motion: bool = False) -> None:
        if high_contrast != self.high_contrast:
            self._cache_key = None
        self.text_scale = max(0.8, min(1.8, float(text_scale)))
        self.high_contrast = bool(high_contrast)
        self.reduce_motion = bool(reduce_motion)
        if reduce_motion:          # critically damped: no overshoot, no wobble
            self.rot.k, self.rot.c = 520.0, 46.0
            self._appear_kc = (320.0, 36.0)
        else:
            self.rot.k, self.rot.c = 520.0, 36.0
            self._appear_kc = (190.0, 20.0)

    def set_level(self, items: list[Item], crumb: str, state: EngineSnapshot) -> None:
        """Swap to another ring (Quick nav in / Back out) with a short zoom."""
        self.items = items
        self.crumb = crumb
        self._cache_key = None
        self.state = state
        self.rot.snap(state.position)
        self._gauge_rot = state.position
        self._cur_sel = self._prev_sel = state.selected
        self.title.snap(1.0)
        self.tint = QColor(items[state.selected % max(1, len(items))].tint)
        self.exec_t = None
        self.exiting = False
        self.appear.target = 1.0
        if self.reduce_motion:
            self.open_t = 1.0
        else:
            self.open_t = 0.0
            self.level_kick.snap(1.0)
            self.level_kick.target = 0.0

    # ------------------------------------------------------------- state
    @property
    def size(self) -> int:
        return self.D + 2 * self.MARGIN

    @property
    def backdrop(self) -> liquid.Backdrop | None:
        return self._backdrop

    @backdrop.setter
    def backdrop(self, bd: liquid.Backdrop | None) -> None:
        self._backdrop = bd
        self._backdrop_ver += 1

    def invalidate(self) -> None:
        self._static: QPixmap | None = None
        self._lens_brush: QBrush | None = None
        self._platters: dict = {}
        self._glows: dict = {}
        self._fonts: dict = {}

    def set_items(self, items: list[Item]) -> None:
        self.items = items
        self._cur_sel = self._prev_sel = 0
        self._cache_key = None

    def set_size(self, size: int) -> None:
        self.D = int(size)
        self._cache_key = None

    def begin(self, state: EngineSnapshot) -> None:
        self.state = state
        self.appear.snap(0.0)
        self.appear.target = 1.0
        self.appear.k, self.appear.c = self._appear_kc
        self.rot.snap(state.position)
        self._gauge_rot = state.position
        self.turned = 0.0
        self.gauge_vis.snap(0.0)
        self.title.snap(1.0)
        self._cur_sel = self._prev_sel = state.selected
        self.tint = QColor(self.items[state.selected].tint)
        self.open_t = 0.0
        self.exec_t = None
        self.exiting = False

    def set_state(self, state: EngineSnapshot) -> None:
        n = max(1, len(self.items))
        if state.selected != self._cur_sel and state.phase == Phase.OPEN:
            diff = (state.selected - self._cur_sel) % n
            self._title_dir = 1.0 if diff <= n / 2 else -1.0
            self._prev_sel, self._cur_sel = self._cur_sel, state.selected
            self.title.snap(0.0)
            self.title.target = 1.0
        self.state = state
        if state.phase == Phase.OPEN:
            sel = round(state.position)
            if state.grip_mode:
                # The engine already strains the knob against its detent: follow it as is.
                self.rot.target = state.position
            else:
                # Magnetic detent: the ring leans toward the hand, then snaps to the item.
                self.rot.target = sel + (state.position - sel) * 0.42
        self.grip_vis.target = 1.0 if state.gripping else 0.0
        self.tracked_vis.target = 1.0 if (state.hand_present and state.facing) else 0.0
        self.point_vis.target = 1.0 if state.pointing else 0.0
        self.push_vis.target = state.push if state.pointing else 0.0
        self.px.target = max(-1.0, min(1.0, state.pointer[0] / 1.6))
        self.py.target = max(-1.0, min(1.0, state.pointer[1] / 1.6))

    def close(self) -> None:
        self.appear.target = 0.0

    def execute(self) -> None:
        self.exec_t = 0.0

    def tick(self, dt: float) -> bool:
        """Advance animations. Returns False once fully closed."""
        dt = min(dt, 1 / 30)
        self.open_t += dt
        if self.exec_t is not None:
            self.exec_t += dt
            if self.exec_t > 0.34 and self.appear.target != 0.0:
                self.exiting = True
                self.appear.target = 0.0
                self.appear.k, self.appear.c = 120.0, 22.0
        for s in (self.appear, self.rot, self.title, self.grip_vis, self.tracked_vis,
                  self.point_vis, self.push_vis, self.px, self.py, self.level_kick, self.gauge_vis):
            s.step(dt)
        if self.items:
            # Ring turned clockwise = positive degrees. Only the primary ring keeps count.
            if not self.crumb:
                self.turned += (self._gauge_rot - self.rot.value) * 360.0 / len(self.items)
            self._gauge_rot = self.rot.value
        self.gauge_vis.target = 1.0 if (not self.crumb and abs(self.turned) > 0.5) else 0.0
        if self.items:
            target = QColor(self.items[self.state.selected % len(self.items)].tint)
            self.tint = _mix(self.tint, target, min(1.0, dt * 10))
        if self.appear.target == 0.0 and self.appear.value < 0.012 and abs(self.appear.velocity) < 0.5:
            return False
        return True

    # ------------------------------------------------------------- geometry & caches
    def _geom(self):
        R = self.D / 2 - 8
        Rin = R * 0.585
        Rmid = (R + Rin) / 2
        rc = Rin - 13
        lens_r = (R - Rin) / 2 - 5
        return R, Rin, Rmid, rc, lens_r

    def _ensure_cache(self, W: float, H: float, dpr: float) -> None:
        key = (W, H, dpr, self._backdrop_ver, len(self.items), id(self.items))
        if key != self._cache_key:
            self.invalidate()
            self._cache_key = key
        if self._static is None:
            self._static = self._render_static(W, H, dpr)
            self._lens_brush = self._render_lens(W, H)

    def prepare(self, W: float, H: float, dpr: float) -> None:
        """Build the cached layers now (before the window shows) so the first frame doesn't stall."""
        self._ensure_cache(W, H, dpr)

    def prewarm(self, dpr: float) -> None:
        """Work out the glass geometry once at idle time, so even the first opening is instant."""
        W = H = self.size
        gw = max(2, int(W * dpr) // 2)
        saved, saved_ver = self._backdrop, self._backdrop_ver
        self._backdrop = liquid.Backdrop(np.zeros((gw, gw, 3), np.float32), gw / W, 0.3)
        self._render_static(W, H, dpr)
        self._render_lens(W, H)
        self._backdrop, self._backdrop_ver = saved, saved_ver
        self._cache_key = None

    def _ring_paths(self) -> tuple[QPainterPath, QPainterPath]:
        R, Rin, Rmid, rc, lens_r = self._geom()
        ring = QPainterPath()
        ring.addEllipse(QPointF(0, 0), R, R)
        ring.addEllipse(QPointF(0, 0), Rin, Rin)
        ring.setFillRule(Qt.FillRule.OddEvenFill)
        return ring, circle(0, 0, rc)

    def _render_static(self, W: float, H: float, dpr: float) -> QPixmap:
        """Shadow, then the glass ring and centre disc: refracted backdrop, tint, sheen."""
        R, Rin, Rmid, rc, lens_r = self._geom()
        pm = _canvas(W, H, dpr)
        p = QPainter(pm)
        _hq(p)
        p.translate(W / 2, H / 2)
        O = QPointF(0, 0)
        hc = self.high_contrast
        bd = self._backdrop
        ring, disc = self._ring_paths()

        soft_shadow(p, O, R, 50, 0.22, dy=16)
        soft_shadow(p, O, rc, 10, 0.10, dy=4)
        lum = 0.5
        if bd is not None and not hc:
            img = liquid.render(bd, [liquid.Annulus(0, 0, Rin, R, bevel=(R - Rin) * 0.36, bend=0.8, magnify=1.03),
                                     liquid.Circle(0, 0, rc, bevel=rc * 0.24, bend=0.75, magnify=1.07)],
                                origin=(-W / 2, -H / 2))
            b = liquid.brush(img, bd.f, (-W / 2, -H / 2))
            p.fillPath(ring, b)
            p.fillPath(disc, b)
            lum = bd.lum
        # Slightly see-through: a light tint that darkens only as much as the backdrop's brightness needs.
        p.fillPath(ring, QColor(10, 10, 14, 205) if hc else qcolor("#0e0e14", liquid.tint_alpha(lum, 0.12, 0.36)))
        lg = QLinearGradient(0, -R, 0, R)
        lg.setColorAt(0.0, white(0.13))
        lg.setColorAt(0.5, white(0.03))
        lg.setColorAt(1.0, white(0.07))
        p.fillPath(ring, lg)
        p.strokePath(circle(0, 0, R + 0.8), QPen(black(0.18), 1.0))
        p.fillPath(disc, QColor(6, 6, 10, 230) if hc else qcolor("#0c0c12", liquid.tint_alpha(lum, 0.30, 0.56)))
        glass_disc(p, O, rc, QColor(0, 0, 0, 0), sheen=0.6)
        stroke_rim(p, circle(0, 0, R), O, 1.4, 1.0)
        stroke_rim(p, circle(0, 0, Rin), O, 1.1, 0.7, light_deg=305)
        stroke_rim(p, disc, O, 1.3, 0.85)
        p.end()
        return pm

    def _render_lens(self, W: float, H: float) -> QBrush | None:
        """The selection lens: a thick magnifying drop sitting on the ring at 12 o'clock."""
        bd = self._backdrop
        if bd is None or self.high_contrast:
            return None
        R, Rin, Rmid, rc, lens_r = self._geom()
        img = liquid.render(bd, [liquid.Circle(0, -Rmid, lens_r, bevel=lens_r * 0.6, bend=0.7, magnify=1.22)],
                            origin=(-W / 2, -H / 2), dispersion=0.1, highlight=0.8)
        return liquid.brush(img, bd.f, (-W / 2, -H / 2))

    def _glow(self, tint_name: str, dpr: float) -> QPixmap:
        key = (tint_name, dpr)
        pm = self._glows.get(key)
        if pm is None:
            R = self._geom()[0]
            G = R + 90
            tint = QColor(tint_name)
            pm = _canvas(2 * G, 2 * G, dpr)
            p = QPainter(pm)
            _hq(p)
            p.translate(G, G)
            g = QRadialGradient(QPointF(0, 0), G)
            k = R / G
            g.setColorAt(k * 0.86, qcolor(tint, 0.0))
            g.setColorAt(k, qcolor(tint, 0.26))
            g.setColorAt(1.0, qcolor(tint, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(0, 0), G, G)
            p.end()
            self._glows[key] = pm
        return pm

    def _platter_pm(self, i: int, dpr: float) -> QPixmap:
        it = self.items[i]
        key = (i, dpr, it.icon, it.glyph, it.tint, it.kind, self.high_contrast)
        pm = self._platters.get(key)
        if pm is None:
            r = self.PLATTER_R
            box = 2 * (r + self.PLATTER_PAD)
            pm = _canvas(box, box, dpr)
            p = QPainter(pm)
            _hq(p)
            self._draw_platter(p, QPointF(box / 2, box / 2), r, it)
            self._decorate(p, QPointF(box / 2, box / 2), r, it)
            p.end()
            self._platters[key] = pm
        return pm

    # ------------------------------------------------------------- paint
    def paint(self, p: QPainter, W: float, H: float) -> None:
        if not self.items:
            return
        _hq(p)
        a = self.appear.value
        opacity = max(0.0, min(1.0, a * 1.25))
        if opacity <= 0.002:
            return
        dev = p.device()
        dpr = dev.devicePixelRatioF() if dev is not None else 1.0
        self._ensure_cache(W, H, dpr)

        scale = 1.0 + 0.08 * (1.0 - a) if self.exiting else 0.84 + 0.16 * a
        if self.reduce_motion:
            scale = 1.0
        scale *= 1.0 - 0.07 * self.level_kick.value
        if abs(scale - 1.0) < 0.004:
            scale = 1.0           # pixel-aligned: the cached layers blit straight through, no resampling
        p.setTransform(QTransform().translate(W / 2, H / 2).scale(scale, scale) * p.transform())

        n = len(self.items)
        R, Rin, Rmid, rc, lens_r = self._geom()
        step = 360.0 / n
        st = self.state
        O = QPointF(0, 0)

        # ---- colour glow of the selected item (cross-faded), then the static glass body
        t = max(0.0, min(1.0, self.title.value))
        G = R + 90
        grect = QRectF(-G, -G, 2 * G, 2 * G)
        if t < 1.0:
            p.setOpacity(opacity * (1 - t))
            p.drawPixmap(grect, self._glow(self.items[self._prev_sel % n].tint, dpr), QRectF())
        p.setOpacity(opacity * t)
        p.drawPixmap(grect, self._glow(self.items[self._cur_sel % n].tint, dpr), QRectF())
        p.setOpacity(opacity)
        p.drawPixmap(QRectF(-W / 2, -H / 2, W, H), self._static, QRectF())
        self._light(p, R, Rin, rc)

        # ---- bezel ticks that turn with the hand
        rot_deg = -self.rot.value * step
        dim = QPainterPath()
        for j in range(120):
            ang = j * 3.0 + rot_deg
            d = abs(_wrap180(ang))
            if d < 42:
                self._tick(p, ang, R - 9, 4.5, 0.13 + 0.55 * (1 - d / 42), 1.0)
            else:
                a_ = math.radians(ang)
                s_, c_ = math.sin(a_), -math.cos(a_)
                dim.moveTo(s_ * (R - 13.5), c_ * (R - 13.5))
                dim.lineTo(s_ * (R - 9), c_ * (R - 9))
        p.strokePath(dim, QPen(white(0.13), 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(n):
            ang = (i + 0.5) * step + rot_deg
            d = abs(_wrap180(ang))
            self._tick(p, ang, R - 9, 9.0, 0.28 + 0.5 * max(0.0, 1 - d / 42), 1.4)

        self._gauge(p, R)

        # ---- the lens (fixed at 12 o'clock): body first, highlights after the icons
        v = self.rot.velocity
        sx = 1.0 if self.reduce_motion else 1 + min(abs(v) * 0.055, 0.38)
        sy = 1.0 if self.reduce_motion else 1 - min(abs(v) * 0.028, 0.14)
        pulse = 1.0 - 0.07 * max(0.0, self.push_vis.value)          # pressed in by a finger push
        if self.exec_t is not None:
            pulse = 1 + 0.2 * math.sin(math.pi * min(self.exec_t / 0.3, 1.0))
        Lc = QPointF(0, -Rmid)
        lens = QPainterPath()
        lens.addEllipse(Lc, lens_r * sx * pulse, lens_r * sy * pulse)
        soft_shadow(p, Lc, lens_r * sy, 12, 0.20, dy=6)
        if self._lens_brush is not None:
            p.fillPath(lens, self._lens_brush)
        p.fillPath(lens, qcolor(self.tint, 0.18))
        p.fillPath(lens, white(0.05))
        le = QRadialGradient(Lc, lens_r * max(sx, sy) * pulse)
        le.setColorAt(0.70, white(0.0))
        le.setColorAt(1.0, white(0.24))
        p.fillPath(lens, le)

        # ---- items around the ring (cached platters, scaled under the lens)
        sel = st.selected
        r0 = self.PLATTER_R
        box0 = 2 * (r0 + self.PLATTER_PAD)
        for i in range(n):
            rel = _wrap180((i - self.rot.value) * step)
            pos = angle_point(Rmid, rel)
            f = smoothstep(max(0.0, 1 - abs(rel) / step))
            order = min((i - sel) % n, (sel - i) % n)
            si = 1.0 if self.reduce_motion else ease_out_cubic((self.open_t - 0.035 * order) / 0.42)
            if si <= 0:
                continue
            s = (1 + 0.30 * f) * (0.55 + 0.45 * si)
            bw = box0 * (27 * s / r0)
            p.setOpacity(opacity * (0.70 + 0.30 * f) * si)
            p.drawPixmap(QRectF(pos.x() - bw / 2, pos.y() - bw / 2, bw, bw), self._platter_pm(i, dpr), QRectF())
        p.setOpacity(opacity)

        # ---- lens highlights over the icons (so they read as "inside" the glass)
        p.save()
        p.setClipPath(lens)
        hl = QRadialGradient(QPointF(Lc.x() - lens_r * 0.35, Lc.y() - lens_r * 0.62), lens_r * 0.95)
        hl.setColorAt(0.0, white(0.34))
        hl.setColorAt(1.0, white(0.0))
        p.fillPath(lens, hl)
        bl = QRadialGradient(QPointF(Lc.x() + lens_r * 0.3, Lc.y() + lens_r * 0.9), lens_r * 0.8)
        bl.setColorAt(0.0, white(0.16))
        bl.setColorAt(1.0, white(0.0))
        p.fillPath(lens, bl)
        if self.exec_t is not None:
            p.fillPath(lens, white(max(0.0, 0.55 * (1 - self.exec_t / 0.35))))
        p.restore()
        stroke_rim(p, lens, Lc, 1.6, 1.0)
        pv = self.push_vis.value
        if pv > 0.01 and self.exec_t is None:
            r = lens_r + 7
            rect = QRectF(Lc.x() - r, Lc.y() - r, 2 * r, 2 * r)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(white(0.16 * self.point_vis.value), 3.0))
            p.drawEllipse(rect)
            p.setPen(QPen(qcolor(self.tint.lighter(135), 0.95), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 90 * 16, int(-360 * 16 * min(1.0, pv)))
        if self.exec_t is not None and self.exec_t < 0.6 and not self.reduce_motion:
            tt = self.exec_t / 0.6
            rr = lens_r * (1 + 1.6 * ease_out_cubic(tt))
            p.strokePath(circle(Lc.x(), Lc.y(), rr), QPen(qcolor(self.tint, 0.85 * (1 - tt)), 2.0))

        # ---- grip glow around the centre disc
        g = self.grip_vis.value
        if g > 0.01:
            gg = QRadialGradient(O, rc + 26)
            kk = rc / (rc + 26)
            gg.setColorAt(kk * 0.9, qcolor(self.tint, 0.0))
            gg.setColorAt(kk, qcolor(self.tint, 0.45 * g))
            gg.setColorAt(1.0, qcolor(self.tint, 0.0))
            band = QPainterPath()
            band.addEllipse(O, rc + 26, rc + 26)
            band.addEllipse(O, rc * 0.88, rc * 0.88)
            band.setFillRule(Qt.FillRule.OddEvenFill)
            p.fillPath(band, gg)
            p.strokePath(circle(0, 0, rc + 1.5), QPen(qcolor(self.tint.lighter(130), 0.95 * g), 2.4))

        # ---- dwell progress
        if st.dwell > 0.001 and self.exec_t is None:
            r = rc + 9
            rect = QRectF(-r, -r, 2 * r, 2 * r)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(white(0.14), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawEllipse(rect)
            p.setPen(QPen(white(0.95), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(rect, 90 * 16, int(-360 * 16 * st.dwell))

        # ---- finger mode: a small glass fingertip that follows the index finger
        pv = self.point_vis.value
        if pv > 0.01:
            cpos = QPointF(self.px.value * rc * 0.55, self.py.value * rc * 0.55)
            cr = 9.0 * (0.6 + 0.4 * pv)
            p.save()
            p.setOpacity(p.opacity() * pv)
            soft_shadow(p, cpos, cr, 6, 0.25, dy=2)
            dot = circle(cpos.x(), cpos.y(), cr)
            p.fillPath(dot, qcolor(self.tint, 0.55))
            glass_disc(p, cpos, cr, QColor(255, 255, 255, 40), sheen=1.4)
            stroke_rim(p, dot, cpos, 1.2, 1.0)
            p.restore()

        self._texts(p, rc)

    # ------------------------------------------------------------- pieces
    def _light(self, p: QPainter, R: float, Rin: float, rc: float) -> None:
        """Reflections that live: while the ring turns, a glint runs along its rim in the direction of
        travel and settles back into the resting highlight; a sheen sweeps across the glass as it opens."""
        if self.reduce_motion or self.high_contrast:
            return
        v = self.rot.velocity
        lean = max(-1.0, min(1.0, v / 4.0))
        if abs(lean) > 0.02:
            # Qt angles: counter-clockwise from 3 o'clock; the resting highlight sits at the upper left.
            centre = 125.0 - 34.0 * lean
            for r, w in ((R - 0.6, 2.2), (Rin + 0.6, 1.6)):
                rect = QRectF(-r, -r, 2 * r, 2 * r)
                for span, a in ((56.0, 0.10), (30.0, 0.20), (12.0, 0.42)):
                    p.setPen(QPen(white(a * abs(lean)), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    p.drawArc(rect, int((centre - span / 2) * 16), int(span * 16))
        if self.open_t > 0.95:
            return
        u = ease_out_cubic(self.open_t / 0.95)
        x = -1.5 * R + 3.0 * R * u
        g = QLinearGradient(x - 0.35 * R, -0.6 * R, x + 0.35 * R, 0.6 * R)
        a = 0.20 * (1 - u)
        g.setColorAt(0.0, white(0.0))
        g.setColorAt(0.5, white(a))
        g.setColorAt(1.0, white(0.0))
        ring, disc = self._ring_paths()
        p.fillPath(ring.united(disc), g)

    def _gauge(self, p: QPainter, R: float) -> None:
        """360° gauge just outside the ring (primary ring only): how far it has turned since it opened.
        A thin track with a tinted arc from 12 o'clock, a full lap per 360°, and the angle above the top."""
        g = self.gauge_vis.value
        if g <= 0.01 or self.crumb:
            return
        deg = self.turned
        r = R + 11
        rect = QRectF(-r, -r, 2 * r, 2 * r)
        p.save()
        p.setOpacity(p.opacity() * min(1.0, g))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(white(0.10 if not self.high_contrast else 0.3), 3.0))
        p.drawEllipse(rect)
        laps, rest = divmod(abs(deg), 360.0)
        col = self.tint.lighter(135)
        if laps >= 1:            # a full lap underneath what's left of the next one
            p.setPen(QPen(qcolor(col, 0.38), 3.0))
            p.drawEllipse(rect)
        sign = 1.0 if deg >= 0 else -1.0
        p.setPen(QPen(qcolor(col, 0.95), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90 * 16, int(-sign * rest * 16))
        # the needle: a bright dot at the current angle
        tip = angle_point(r, sign * rest)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(white(0.95))
        p.drawEllipse(tip, 3.4, 3.4)
        # the 0° mark
        self._tick(p, 0.0, r + 5, 10, 0.55, 1.6)
        lf, fm = self._font("display", 14 * self.text_scale, QFont.Weight.DemiBold)
        p.setFont(lf)
        text = f"{deg:+.0f}°" if abs(deg) >= 0.5 else "0°"
        tw = fm.horizontalAdvance(text) + 8
        y = -(r + 12 + fm.height())
        p.setPen(black(0.30))
        p.drawText(QRectF(-tw / 2, y + 1.2, tw, fm.height()), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(white(0.92))
        p.drawText(QRectF(-tw / 2, y, tw, fm.height()), Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def _font(self, which: str, px: float, weight: QFont.Weight) -> tuple[QFont, QFontMetricsF]:
        key = (which, px, weight)
        got = self._fonts.get(key)
        if got is None:
            f = font(DISPLAY if which == "display" else TEXT, px, weight)
            got = self._fonts[key] = (f, QFontMetricsF(f))
        return got

    @staticmethod
    def _tick(p: QPainter, deg: float, r_out: float, length: float, alpha: float, width: float) -> None:
        a = math.radians(deg)
        s, c = math.sin(a), -math.cos(a)
        p.setPen(QPen(white(alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * (r_out - length), c * (r_out - length)), QPointF(s * r_out, c * r_out))

    def _decorate(self, p: QPainter, c: QPointF, r: float, it: Item) -> None:
        if self.high_contrast:
            p.strokePath(circle(c.x(), c.y(), r + 0.5), QPen(white(0.95), 2.0))
        if it.kind == "quicknav":          # a small chevron badge: this opens more
            bc = QPointF(c.x() + r * 0.72, c.y() + r * 0.72)
            br = r * 0.36
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(22, 22, 28, 240))
            p.drawEllipse(bc, br, br)
            p.strokePath(circle(bc.x(), bc.y(), br), QPen(white(0.75), 1.0))
            p.setFont(font(ICONS, br * 1.05))
            p.setPen(white(1.0))
            p.drawText(QRectF(bc.x() - br, bc.y() - br, 2 * br, 2 * br), Qt.AlignmentFlag.AlignCenter, "\uE76C")

    @staticmethod
    def _draw_platter(p: QPainter, c: QPointF, r: float, it: Item) -> None:
        tint = QColor(it.tint)
        soft_shadow(p, c, r, 6, 0.22, dy=3)
        path = circle(c.x(), c.y(), r)
        dev = p.device()
        icon = app_icon(it.icon, int(r * 2 * (dev.devicePixelRatioF() if dev else 1.0))) if it.icon else None
        if icon is not None:
            # Real app icon on a frosted white platter, tinted at the rim.
            base = QLinearGradient(c.x(), c.y() - r, c.x(), c.y() + r)
            base.setColorAt(0.0, white(0.92))
            base.setColorAt(1.0, QColor(226, 228, 236, 235))
            p.fillPath(path, base)
            p.fillPath(path, qcolor(tint, 0.10))
            s_ = r * 1.18
            p.drawPixmap(QRectF(c.x() - s_ / 2, c.y() - s_ / 2, s_, s_), icon, QRectF(icon.rect()))
            gloss = QRadialGradient(QPointF(c.x(), c.y() - r * 0.7), r * 0.9)
            gloss.setColorAt(0.0, white(0.30))
            gloss.setColorAt(1.0, white(0.0))
            p.fillPath(path, gloss)
            stroke_rim(p, path, c, 1.0, 0.85)
            return
        base = QLinearGradient(c.x(), c.y() - r, c.x(), c.y() + r)
        base.setColorAt(0.0, qcolor(tint.lighter(128), 0.95))
        base.setColorAt(1.0, qcolor(tint.darker(112), 0.95))
        p.fillPath(path, base)
        gloss = QRadialGradient(QPointF(c.x(), c.y() - r * 0.62), r * 1.05)
        gloss.setColorAt(0.0, white(0.42))
        gloss.setColorAt(0.55, white(0.10))
        gloss.setColorAt(1.0, white(0.0))
        p.fillPath(path, gloss)
        bounce = QRadialGradient(QPointF(c.x(), c.y() + r * 0.95), r * 0.85)
        bounce.setColorAt(0.0, white(0.22))
        bounce.setColorAt(1.0, white(0.0))
        p.fillPath(path, bounce)
        stroke_rim(p, path, c, 1.0, 0.75)
        p.setFont(font(ICONS, r * 0.92))
        rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        p.setPen(black(0.22))
        p.drawText(rect.translated(0, 1.2), Qt.AlignmentFlag.AlignCenter, it.glyph_char)
        p.setPen(white(1.0))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, it.glyph_char)

    def _texts(self, p: QPainter, rc: float) -> None:
        st = self.state
        n = len(self.items)
        k = self.text_scale
        hc = self.high_contrast
        width = 2 * (rc - 22)
        t = 1.0 if self.reduce_motion else max(0.0, min(1.0, self.title.value))
        tf, fm_t = self._font("display", 27 * k, QFont.Weight.DemiBold)
        sf, fm_s = self._font("text", 14 * k, QFont.Weight.Medium if hc else QFont.Weight.Normal)
        th, sh = fm_t.height(), fm_s.height()

        def draw_title(idx: int, alpha: float, dy: float) -> None:
            if alpha <= 0.01:
                return
            it = self.items[idx % n]
            p.setFont(tf)
            name = fm_t.elidedText(it.name, Qt.TextElideMode.ElideRight, width)
            p.setPen(black(0.28 * alpha))
            p.drawText(QRectF(-width / 2, -th + 3.2 + dy, width, th), Qt.AlignmentFlag.AlignCenter, name)
            p.setPen(white(0.98 * alpha))
            p.drawText(QRectF(-width / 2, -th + 2 + dy, width, th), Qt.AlignmentFlag.AlignCenter, name)
            p.setFont(sf)
            p.setPen(white((0.9 if hc else 0.6) * alpha))
            sub = "Opening…" if self.exec_t is not None else it.subtitle
            p.drawText(QRectF(-width / 2, 4 + dy, width, sh + 2), Qt.AlignmentFlag.AlignCenter,
                       fm_s.elidedText(sub, Qt.TextElideMode.ElideRight, width))

        d = 0.0 if self.reduce_motion else self._title_dir * 12
        if t < 1.0:
            draw_title(self._prev_sel, 1 - t, d * t)
        draw_title(self._cur_sel, t, -d * (1 - t))

        # breadcrumb inside a Quick nav ring, and position dots
        top_y = -rc * 0.52
        if self.crumb:
            cf, fm_c = self._font("text", 11.5 * k, QFont.Weight.DemiBold)
            p.setFont(cf)
            p.setPen(white(0.85 if hc else 0.55))
            p.drawText(QRectF(-width / 2, top_y - 14 - 12 * k, width, 14 * k + 4), Qt.AlignmentFlag.AlignCenter,
                       fm_c.elidedText(self.crumb.upper(), Qt.TextElideMode.ElideRight, width * 0.8))
        if n <= 16:
            gap = 9.0
            x0 = -gap * (n - 1) / 2
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(n):
                on = i == st.selected
                p.setBrush(white(0.95 if on else (0.5 if hc else 0.28)))
                r = 3.0 if on else 2.2
                p.drawEllipse(QPointF(x0 + i * gap, top_y), r, r)

        # hint + tracking dot
        hint = self.hint()
        hf, fm_h = self._font("text", 12.5 * k, QFont.Weight.Medium if hc else QFont.Weight.Normal)
        hint = fm_h.elidedText(hint, Qt.TextElideMode.ElideRight, width - 16)
        hw = fm_h.horizontalAdvance(hint)
        hy = rc * 0.47 + (k - 1.0) * 10
        p.setFont(hf)
        p.setPen(white(0.88 if hc else 0.55))
        p.drawText(QRectF(-width / 2 + 8, hy - fm_h.height() / 2, width, fm_h.height()),
                   Qt.AlignmentFlag.AlignCenter, hint)
        dot = QColor("#30D158") if (self.tracked_vis.value > 0.5 or self.keyboard) else QColor("#FF9F0A")
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(dot, 0.95))
        p.drawEllipse(QPointF(-hw / 2 - 2, hy), 3.0 * k, 3.0 * k)

    def hint(self) -> str:
        st = self.state
        c = self.controls or {}
        style = c.get("turn_style", "tilt")
        if self.exec_t is not None:
            return "Launching"
        if self.keyboard:
            return "Scroll or ← → to turn · Click or Enter to open · Esc to close"
        if not (st.hand_present and st.facing):
            return "Raise your hand to continue" if c.get("either_side") else "Show your palm to continue"
        if st.scrolling:
            return "Scrolling — " + ("back to the middle to stop" if style == "move" else "straighten to stop")
        if st.pointing:
            return "Move aside to scroll · push to open" if c.get("finger_push", True) else "Move aside to scroll"
        verb = {"tilt": "Tilt", "move": "Move", "direct": "Turn"}.get(style, "Tilt")
        if st.grip_mode:
            if st.gripping:
                return "Point your finger to open" if st.interacted else "Tilt your fist to turn"
            return "Close your hand to keep turning · point to open"
        if st.dwell > 0.02:
            return "Hold still to open" + (" · or pinch" if c.get("pinch_click", True) else "")
        if not st.interacted:
            return {"tilt": "Tilt your hand to choose", "move": "Move your hand sideways to choose",
                    "direct": "Turn your hand to choose"}.get(style, "Tilt your hand to choose")
        ways = []
        if c.get("pinch_click", True):
            ways.append("pinch")
        if float(c.get("dwell_seconds", 1.6)) > 0:
            ways.append("hold still")
        if c.get("finger_push", True):
            ways.append("point and push")
        if not ways:
            return "Close your hand, tilt, then point"
        text = ways[0] if len(ways) == 1 else ", ".join(ways[:-1]) + " or " + ways[-1]
        return text[0].upper() + text[1:] + " to open"


class DialWindow(QWidget):
    """The rotary on screen. Opened by a gesture it lets every click through; opened from the notch or the
    keyboard it also takes the mouse: scroll or drag the ring to turn it, click an item to choose it,
    click it again (or the centre) to open it, right-click to go back or close."""
    mouse = Signal(str, int)        # ("turn", ±n) | ("select", index) | ("open", 0) | ("back", 0)

    def __init__(self, items: list[Item], size: int = 600, live_glass: bool = False):
        super().__init__(None)
        overlay_flags(self)
        self.setWindowTitle("Gesture Rotary")
        self.setMouseTracking(True)
        self.painter_ = DialPainter(items, size)
        self.resize(self.painter_.size, self.painter_.size)
        self.live_glass = live_glass
        self.interactive = False
        self._excluded = False
        self._drag: dict | None = None
        self._wheel = 0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._last = time.perf_counter()
        self._glass_timer = QTimer(self)
        self._glass_timer.setInterval(250)
        self._glass_timer.timeout.connect(self._refresh_glass)

    def set_items(self, items: list[Item]) -> None:
        self.painter_.set_items(items)

    def prewarm(self) -> None:
        if not self.isVisible():
            screen = QGuiApplication.primaryScreen()
            self.painter_.prewarm(screen.devicePixelRatio() if screen else 1.0)

    def set_level(self, items: list[Item], crumb: str, state: EngineSnapshot) -> None:
        self.painter_.set_level(items, crumb, state)
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def set_dial_size(self, size: int) -> None:
        if size != self.painter_.D and not self.isVisible():
            self.painter_.set_size(size)
            self.resize(self.painter_.size, self.painter_.size)

    def _set_interactive(self, on: bool) -> None:
        """Only while hidden: changing window flags recreates the native window."""
        if on == self.interactive:
            return
        self.interactive = on
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not on)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not on)
        self._excluded = False

    def open(self, state: EngineSnapshot, interactive: bool = False) -> None:
        dp = self.painter_
        if self.isVisible() and interactive != self.interactive:
            self._timer.stop()
            self._glass_timer.stop()
            self.hide()
        if not self.isVisible():
            self._set_interactive(interactive)
            self._drag = None
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            g = screen.availableGeometry()
            self.move(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)
            raw = grab_behind(self)
            dp.backdrop = liquid.Backdrop.from_pixmap(raw)
            hz = screen.refreshRate() or 60.0          # one frame per screen refresh, no more
            self._timer.setInterval(max(4, int(1000.0 / max(30.0, min(hz, 165.0)))))
            dp.prepare(self.width(), self.height(), screen.devicePixelRatio())
            self.show()
            want = bool(self.live_glass)
            if want != self._excluded:          # also undo it when live glass gets switched off
                ok = exclude_from_capture(self, want)
                self._excluded = want and ok
            if self.live_glass and self._excluded:
                self._glass_timer.start()
        dp.begin(state)
        self._last = time.perf_counter()
        self._timer.start()

    def set_state(self, state: EngineSnapshot) -> None:
        self.painter_.set_state(state)

    def close_dial(self) -> None:
        self.painter_.close()

    def play_execute(self) -> None:
        self.painter_.execute()

    def _refresh_glass(self) -> None:
        bd = liquid.Backdrop.from_pixmap(grab_behind(self))
        if bd is not None:
            self.painter_.backdrop = bd

    def _tick(self) -> None:
        now = time.perf_counter()
        dt, self._last = now - self._last, now
        if not self.painter_.tick(dt):
            self._timer.stop()
            self._glass_timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self.painter_.paint(p, self.width(), self.height())
        p.end()

    # ------------------------------------------------------------- mouse
    def _local(self, pt) -> tuple[float, float, float, float]:
        """(x, y, radius, clockwise-from-top angle) of a point relative to the dial centre."""
        x, y = pt.x() - self.width() / 2, pt.y() - self.height() / 2
        return x, y, math.hypot(x, y), math.degrees(math.atan2(x, -y))

    def hit(self, pt) -> tuple[str, int]:
        """What's under the mouse: ("item", index) | ("centre", 0) | ("ring", 0) | ("", 0)."""
        dp = self.painter_
        n = len(dp.items)
        if not n or dp.exiting:
            return "", 0
        x, y, r, _a = self._local(pt)
        R, Rin, Rmid, rc, lens_r = dp._geom()
        step = 360.0 / n
        best, best_d = -1, 1e9
        for i in range(n):
            rel = _wrap180((i - dp.rot.value) * step)
            c = angle_point(Rmid, rel)
            f = smoothstep(max(0.0, 1 - abs(rel) / step))
            d = math.hypot(x - c.x(), y - c.y())
            if d <= 27 * (1 + 0.30 * f) + 5 and d < best_d:
                best, best_d = i, d
        if best >= 0:
            return "item", best
        if r <= rc:
            return "centre", 0
        if Rin - 4 <= r <= R + 6:
            return "ring", 0
        return "", 0

    def mousePressEvent(self, ev) -> None:
        if not self.interactive:
            return
        if ev.button() == Qt.MouseButton.RightButton:
            self.mouse.emit("back", 0)
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        kind, idx = self.hit(ev.position())
        _x, _y, _r, a = self._local(ev.position())
        self._drag = {"kind": kind, "idx": idx, "angle": a, "acc": 0.0, "moved": 0.0, "dragging": False}
        if kind == "ring":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, ev) -> None:
        if not self.interactive:
            return
        d = self._drag
        if d is not None and d["kind"] in ("item", "ring"):
            _x, _y, _r, a = self._local(ev.position())
            da = _wrap180(a - d["angle"])
            d["angle"] = a
            d["acc"] += da
            d["moved"] += abs(da)
            if d["moved"] > 6:
                d["dragging"] = True
            step = 360.0 / max(1, len(self.painter_.items))
            while d["dragging"] and abs(d["acc"]) >= step * 0.75:
                # turning the ring clockwise brings the previous item under the lens
                sgn = 1 if d["acc"] > 0 else -1
                d["acc"] -= sgn * step
                self.mouse.emit("turn", -sgn)
            return
        kind, _idx = self.hit(ev.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if kind in ("item", "centre")
                       else (Qt.CursorShape.OpenHandCursor if kind == "ring" else Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, ev) -> None:
        d, self._drag = self._drag, None
        if not self.interactive or d is None or ev.button() != Qt.MouseButton.LeftButton or d["dragging"]:
            return
        kind, idx = self.hit(ev.position())
        if kind == "centre" and d["kind"] == "centre":
            self.mouse.emit("open", 0)
        elif kind == "item" and d["kind"] == "item" and idx == d["idx"]:
            n = max(1, len(self.painter_.items))
            if idx == self.painter_.state.selected % n:
                self.mouse.emit("open", 0)
            else:
                self.mouse.emit("select", idx)

    def wheelEvent(self, ev) -> None:
        if not self.interactive:
            return
        dlt = ev.angleDelta()
        self._wheel += dlt.y() if abs(dlt.y()) >= abs(dlt.x()) else -dlt.x()
        while abs(self._wheel) >= 120:
            step = 1 if self._wheel < 0 else -1          # wheel down = next item
            self._wheel += 120 if self._wheel < 0 else -120
            self.mouse.emit("turn", step)
        ev.accept()

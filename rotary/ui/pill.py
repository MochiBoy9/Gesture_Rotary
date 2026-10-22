"""Status capsule pinned to the top of the screen (Dynamic-Island style)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QLinearGradient,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QWidget

from . import liquid
from .glass import ICONS, TEXT, Spring, font, grab_behind, overlay_flags, qcolor, stroke_rim, white

GREEN, AMBER, RED, BLUE, GRAY = "#30D158", "#FF9F0A", "#FF453A", "#0A84FF", "#8E8E93"


class PillWindow(QWidget):
    W, H, CAP_H = 560, 84, 40

    def __init__(self):
        super().__init__(None)
        overlay_flags(self)
        self.resize(self.W, self.H)
        self.text = ""
        self.prev_text = ""
        self.kind = "dot"
        self.accent = QColor(GRAY)
        self.progress: float | None = None
        self.collapsed = False
        self.hidden_ = True
        self.width_s = Spring(self.CAP_H, 300.0, 30.0)
        self.vis = Spring(0.0, 220.0, 26.0)
        self.fade = Spring(1.0, 260.0, 30.0)
        self.prog_s = Spring(0.0, 400.0, 40.0)
        self._t0 = time.perf_counter()
        self._last = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(12)
        self._timer.timeout.connect(self._tick)
        self._bd: liquid.Backdrop | None = None
        self._glass = None
        self._glass_key = None
        self._tf = font(TEXT, 13.5, QFont.Weight.DemiBold)
        self._fm = QFontMetricsF(self._tf)

    # ----------------------------------------------------------------- api
    def set_status(self, text: str, kind: str = "dot", accent: str = GRAY, progress: float | None = None,
                   collapsed: bool = False, hidden: bool = False) -> None:
        changed = False
        if text != self.text:
            self.prev_text, self.text = self.text, text
            self.fade.snap(0.0)
            self.fade.target = 1.0
            changed = True
        if kind != self.kind or QColor(accent) != self.accent:
            self.kind, self.accent = kind, QColor(accent)
            changed = True
        if (progress is None) != (self.progress is None):
            changed = True
        self.progress = progress
        if progress is not None:
            self.prog_s.target = progress
            changed = True
        self.collapsed = collapsed
        self.hidden_ = hidden
        self.vis.target = 0.0 if hidden else 1.0
        self.width_s.target = self._target_width()
        if not self.isVisible() and not hidden:
            self._place()
            self._bd = liquid.Backdrop.from_pixmap(grab_behind(self))     # what's behind, before we cover it
            self._glass_key = None
            self.show()
        if changed or not self.width_s.settled or not self.vis.settled or kind == "pulse":
            self._wake()

    def _target_width(self) -> float:
        if self.collapsed or not self.text:
            return self.CAP_H
        return min(self.W - 24, 12 + 24 + 10 + self._fm.horizontalAdvance(self.text) + 18)

    def _place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.center().x() - self.W // 2, g.top() + 6)

    def _wake(self) -> None:
        if not self._timer.isActive():
            self._last = time.perf_counter()
            self._timer.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt, self._last = min(now - self._last, 1 / 30), now
        for s in (self.width_s, self.vis, self.fade, self.prog_s):
            s.step(dt)
        self.update()
        idle = all(s.settled for s in (self.width_s, self.vis, self.fade, self.prog_s)) and self.kind != "pulse"
        if idle:
            self._timer.stop()
            if self.hidden_:
                self.hide()

    # --------------------------------------------------------------- paint
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        v = max(0.0, min(1.0, self.vis.value))
        if v <= 0.01:
            p.end()
            return
        p.setOpacity(v * (0.72 if self.collapsed else 1.0))
        w = max(self.CAP_H, self.width_s.value)
        h = self.CAP_H
        cx = self.W / 2
        top = 10 - (1 - v) * 14
        rect = QRectF(cx - w / 2, top, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, h / 2, h / 2)

        # shadow
        for i, a in ((10, 0.05), (6, 0.07), (3, 0.09)):
            sp = QPainterPath()
            sp.addRoundedRect(rect.adjusted(-i, -i + 4, i, i + 4), h / 2 + i, h / 2 + i)
            p.fillPath(sp, QColor(0, 0, 0, int(255 * a)))
        bd = self._bd
        lum = 0.5
        if bd is not None:
            key = (round(w / 4), round(top / 2))          # quantised: the slide-in reuses most of the work
            if key != self._glass_key:
                shape = liquid.RoundRect(rect.left(), rect.top(), rect.right(), rect.bottom(), h / 2,
                                         bevel=h * 0.45, bend=0.85)
                self._glass = liquid.brush(liquid.render(bd, [shape]), bd.f)
                self._glass_key = key
            p.fillPath(path, self._glass)
            lum = bd.lum
        p.fillPath(path, qcolor("#121216", liquid.tint_alpha(lum, 0.58, 0.76)))
        lg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        lg.setColorAt(0.0, white(0.13))
        lg.setColorAt(0.5, white(0.03))
        lg.setColorAt(1.0, white(0.06))
        p.fillPath(path, lg)
        stroke_rim(p, path, rect.center(), 1.1, 0.75)

        # indicator
        ic = QPointF(rect.left() + h / 2, rect.center().y())
        self._indicator(p, ic)

        # text (cross-fade)
        if not self.collapsed and w > h + 20:
            p.save()
            p.setClipRect(QRectF(rect.left() + h - 2, rect.top(), w - h - 10, h))
            p.setFont(self._tf)
            tx = rect.left() + h - 2
            f = max(0.0, min(1.0, self.fade.value))
            if self.prev_text and f < 1:
                p.setPen(white(0.92 * (1 - f)))
                p.drawText(QRectF(tx, rect.top() - 6 * f, 520, h), Qt.AlignmentFlag.AlignVCenter, self.prev_text)
            p.setPen(white(0.94 * f))
            p.drawText(QRectF(tx, rect.top() + 6 * (1 - f), 520, h), Qt.AlignmentFlag.AlignVCenter, self.text)
            p.restore()
        p.end()

    def _indicator(self, p: QPainter, c: QPointF) -> None:
        acc = self.accent
        if self.progress is not None:
            r = 10.5
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(white(0.16), 2.6))
            p.drawEllipse(c, r, r)
            p.setPen(QPen(acc, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 90 * 16,
                      int(-360 * 16 * max(0.0, min(1.0, self.prog_s.value))))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qcolor(acc, 0.9))
            p.drawEllipse(c, 3.2, 3.2)
            return
        if self.kind == "warning":                  # a small warning sign, no words
            p.setFont(font(ICONS, 15, QFont.Weight.Normal))
            p.setPen(acc)
            p.drawText(QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter, "")
            return
        if self.kind in ("done", "error"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(acc)
            p.drawEllipse(c, 11, 11)
            p.setFont(font(ICONS, 12, QFont.Weight.Bold))
            p.setPen(white(1.0))
            p.drawText(QRectF(c.x() - 11, c.y() - 11, 22, 22), Qt.AlignmentFlag.AlignCenter,
                       "" if self.kind == "done" else "")
            return
        a = 1.0
        if self.kind == "pulse":
            a = 0.45 + 0.55 * (0.5 + 0.5 * math.sin((time.perf_counter() - self._t0) * 5))
        glow = qcolor(acc, 0.28 * a)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, 8, 8)
        p.setBrush(qcolor(acc, a))
        p.drawEllipse(c, 4.6, 4.6)

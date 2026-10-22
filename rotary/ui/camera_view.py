"""Live camera view: the feed, the tracked hand skeleton, face zones and status chips."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..gestures import EngineSnapshot, HandFeatures, HandFrame, Phase
from .glass import TEXT, font, white

CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
               (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]

STYLE = """
QWidget#root { background: #0e0e12; }
QLabel { color: rgba(255,255,255,0.86); font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }
QLabel#title { font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 20px; font-weight: 600; color: white; }
QLabel#muted { color: rgba(255,255,255,0.5); font-size: 12px; }
QFrame#card { background: rgba(255,255,255,0.055); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; }
QComboBox, QPushButton {
  color: white; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12);
  border-radius: 9px; padding: 7px 12px; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }
QPushButton:hover, QComboBox:hover { background: rgba(255,255,255,0.13); }
QPushButton:pressed { background: rgba(255,255,255,0.18); }
QPushButton#accent { background: #0A84FF; border: none; font-weight: 600; }
QPushButton#accent:hover { background: #2a95ff; }
QComboBox QAbstractItemView { background: #1c1c22; color: white; selection-background-color: #0A84FF;
  border: 1px solid rgba(255,255,255,0.12); }
QCheckBox { color: rgba(255,255,255,0.86); font-size: 13px; spacing: 8px; }
"""


class VideoView(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 360)
        self.image: QImage | None = None
        self.hands: list[HandFrame] = []
        self.feats: list[HandFeatures] = []
        self.chosen = -1
        self.snap = EngineSnapshot()
        self.faces: list = []
        self.still_seconds = 3.0
        self.message = "Waiting for camera…"

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 16, 16)
        p.setClipPath(clip)
        p.fillRect(r, QColor("#050507"))
        if self.image is None:
            p.setPen(white(0.5))
            p.setFont(font(TEXT, 14))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.message)
            return
        iw, ih = self.image.width(), self.image.height()
        s = min(r.width() / iw, r.height() / ih)
        dw, dh = iw * s, ih * s
        img_r = QRectF((r.width() - dw) / 2, (r.height() - dh) / 2, dw, dh)
        p.drawImage(img_r, self.image)

        for fx0, fy0, fx1, fy1 in self.faces:
            fw, fh = fx1 - fx0, fy1 - fy0
            fr = QRectF(img_r.left() + fx0 * dw, img_r.top() + fy0 * dh, fw * dw, fh * dh)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 214, 10, 200), 1.6))
            p.drawRoundedRect(fr, 8, 8)
            zone = QRectF(img_r.left() + (fx0 - 0.15 * fw) * dw, img_r.top() + (fy0 + 0.45 * fh) * dh,
                          1.3 * fw * dw, 1.35 * fh * dh)
            p.setPen(QPen(QColor(255, 214, 10, 110), 1.2, Qt.PenStyle.DashLine))
            p.drawRoundedRect(zone, 10, 10)

        for hi, hand in enumerate(self.hands):
            f = self.feats[hi] if hi < len(self.feats) else None
            chosen = hi == self.chosen
            if f is None or f.facing <= 0.06:
                col = QColor("#FF453A")
            elif chosen and self.snap.gripping:
                col = QColor("#FF9F0A")
            else:
                col = QColor("#30D158")
            if not chosen:
                col.setAlphaF(0.45)
            pts = [QPointF(img_r.left() + x * dw, img_r.top() + y * dh) for x, y, _ in hand.landmarks]
            p.setPen(QPen(col, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for a, b in CONNECTIONS:
                p.drawLine(pts[a], pts[b])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 230))
            for q in pts:
                p.drawEllipse(q, 2.6, 2.6)
            if chosen and f is not None:
                c = QPointF(img_r.left() + f.center[0] / hand.aspect * dw, img_r.top() + f.center[1] * dh)
                L = f.scale * dh * 1.3
                p.setPen(QPen(QColor(255, 255, 255, 200), 2, Qt.PenStyle.DashLine))
                p.drawLine(c, QPointF(c.x() + math.cos(f.angle) * L, c.y() + math.sin(f.angle) * L))

        # chips
        chips = []
        st = self.snap
        if st.hand_present and st.at_face:
            chips.append(("Near your face — ignored", "#FFD60A"))
        chips.append(("Palm" if st.facing else ("Back of hand" if st.hand_present else "No hand"),
                      "#30D158" if st.facing else "#FF453A" if st.hand_present else "#8E8E93"))
        if st.hand_present:
            chips.append(("Fist" if st.gripping else ("Pointing" if st.pointing else "Open hand"),
                          "#FF9F0A" if st.gripping else ("#64D2FF" if st.pointing else "#8E8E93")))
            if st.pinching:
                chips.append(("Pinch", "#0A84FF"))
        chips.append(({"idle": "Waiting", "open": "Rotary open", "executing": "Launching"}.get(st.phase.value, ""),
                      "#0A84FF" if st.phase == Phase.OPEN else "#8E8E93"))
        if st.hand_present and st.presented and st.phase == Phase.IDLE:
            chips.append(("Ready", "#30D158"))
        if st.phase == Phase.IDLE and st.arming > 0:
            chips.append((f"Opening in {max(0.0, (1 - st.arming) * self.still_seconds):.1f}s", "#0A84FF"))
        x = img_r.left() + 12
        y = img_r.bottom() - 40
        p.setFont(font(TEXT, 12, QFont.Weight.DemiBold))
        for text, colr in chips:
            w = p.fontMetrics().horizontalAdvance(text) + 28
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, y, w, 26), 13, 13)
            p.fillPath(path, QColor(0, 0, 0, 150))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(colr))
            p.drawEllipse(QPointF(x + 12, y + 13), 3.5, 3.5)
            p.setPen(white(0.92))
            p.drawText(QRectF(x + 20, y, w - 22, 26), Qt.AlignmentFlag.AlignVCenter, text)
            x += w + 6

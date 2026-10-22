"""Liquid glass, computed with numpy from a grab of the screen behind a window.

What makes it read as glass rather than frosted plastic:
  * a light frost only (you can still make out what's behind it), with a little extra vibrancy;
  * refraction: near its edges the glass bends the backdrop inward like a thick bevel, while the middle
    stays flat and clear;
  * a touch of colour separation where the bend is strongest;
  * light: a bright bevel where the edge faces the light (top left), a softer bounce opposite, and a
    faint shade along the bottom for thickness.

Everything runs on a half-resolution grid (the backdrop is soft anyway) and comes back as a QImage that
callers paint through an anti-aliased path with `brush()`. Shapes are given in the window's logical px.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QImage, QPixmap, QTransform

LIGHT = np.array([-0.5, -0.866], np.float32)        # where the light comes from (up and to the left)


# --------------------------------------------------------------------------- image <-> numpy
def to_rgb(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, : w * 3]
    return arr.reshape(h, w, 3).copy()


def to_qimage(rgb: np.ndarray) -> QImage:
    a = np.ascontiguousarray(np.clip(rgb, 0, 255).astype(np.uint8))
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format.Format_RGB888).copy()


def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Box blur along one axis (edge-clamped), via a cumulative sum."""
    if r <= 0:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def frost(img: QImage, scale: int = 2, radius: int = 2, passes: int = 2,
          saturation: float = 1.3, lift: float = 1.03) -> np.ndarray:
    """A light frost on a grid `scale`× smaller than `img`: Qt does the resampling (area-averaged down,
    bilinear back up), numpy blurs at a further 2× reduction (stacked box blurs ≈ gaussian) and adds
    vibrancy. Returns float32 H×W×3."""
    smooth, keep = Qt.TransformationMode.SmoothTransformation, Qt.AspectRatioMode.IgnoreAspectRatio
    gw, gh = max(2, img.width() // scale), max(2, img.height() // scale)
    small = img.scaled(max(1, gw // 2), max(1, gh // 2), keep, smooth)
    a = to_rgb(small).astype(np.float32)
    for _ in range(passes):
        a = _box(_box(a, radius, 0), radius, 1)
    lum = a @ np.array([0.299, 0.587, 0.114], np.float32)
    a = np.clip((lum[..., None] + (a - lum[..., None]) * saturation) * lift, 0, 255)
    return to_rgb(to_qimage(a).scaled(gw, gh, keep, smooth)).astype(np.float32)


@dataclass
class Backdrop:
    """A frosted grab of what's behind a window, on a grid `1 / f` the size of the window in logical px."""
    img: np.ndarray            # float32 H×W×3
    f: float                   # grid px per logical px
    lum: float                 # mean brightness 0..1 (to pick how dark the glass tint should be)

    @classmethod
    def from_pixmap(cls, pix: QPixmap | None, scale: int = 2, radius: int = 2) -> "Backdrop | None":
        if pix is None or pix.isNull() or pix.width() < 4 or pix.height() < 4:
            return None
        dpr = pix.devicePixelRatio() or 1.0
        img = frost(pix.toImage(), scale, radius)
        return cls(img, img.shape[1] / (pix.width() / dpr), float(img.mean()) / 255.0)

    def pixmap(self) -> QPixmap:
        return QPixmap.fromImage(to_qimage(self.img))


# --------------------------------------------------------------------------- shapes (signed distance)
@dataclass
class Circle:
    cx: float
    cy: float
    r: float
    bevel: float = 16.0          # how wide the curved edge is (logical px)
    bend: float = 0.9            # how far the edge pulls the backdrop in, as a share of the bevel
    magnify: float = 1.0         # extra magnification of the whole body (a lens)

    def sdf(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        rr = np.hypot(dx, dy) + 1e-6
        return rr - self.r, dx / rr, dy / rr

    def bounds(self):
        return self.cx - self.r, self.cy - self.r, self.cx + self.r, self.cy + self.r

    def center(self):
        return self.cx, self.cy


@dataclass
class Annulus:
    cx: float
    cy: float
    r_in: float
    r_out: float
    bevel: float = 16.0
    bend: float = 0.9
    magnify: float = 1.0

    def sdf(self, x, y):
        dx, dy = x - self.cx, y - self.cy
        rr = np.hypot(dx, dy) + 1e-6
        d_out, d_in = rr - self.r_out, self.r_in - rr
        outer = d_out >= d_in
        sign = np.where(outer, 1.0, -1.0)
        return np.maximum(d_out, d_in), sign * dx / rr, sign * dy / rr

    def bounds(self):
        return self.cx - self.r_out, self.cy - self.r_out, self.cx + self.r_out, self.cy + self.r_out

    def center(self):
        return self.cx, self.cy


@dataclass
class RoundRect:
    x0: float
    y0: float
    x1: float
    y1: float
    radius: float
    bevel: float = 14.0
    bend: float = 0.9
    magnify: float = 1.0

    def sdf(self, x, y):
        cx, cy = (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2
        r = min(self.radius, (self.x1 - self.x0) / 2, (self.y1 - self.y0) / 2)
        px, py = x - cx, y - cy
        qx = np.abs(px) - ((self.x1 - self.x0) / 2 - r)
        qy = np.abs(py) - ((self.y1 - self.y0) / 2 - r)
        mx, my = np.maximum(qx, 0), np.maximum(qy, 0)
        out_len = np.hypot(mx, my)
        d = out_len + np.minimum(np.maximum(qx, qy), 0) - r
        corner = (qx > 0) & (qy > 0)
        sx, sy = np.sign(px), np.sign(py)
        nx = np.where(corner, mx / (out_len + 1e-6), np.where(qx > qy, 1.0, 0.0)) * sx
        ny = np.where(corner, my / (out_len + 1e-6), np.where(qx > qy, 0.0, 1.0)) * sy
        return d, nx, ny

    def bounds(self):
        return self.x0, self.y0, self.x1, self.y1

    def center(self):
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2


# --------------------------------------------------------------------------- rendering
@dataclass
class _Map:
    """Where each glass pixel samples the backdrop from, and how much light it catches. Depends only on
    the geometry, so it's built once and reused every time the window opens over a new backdrop."""
    idx: np.ndarray                     # flat grid indices of the pixels inside the shape
    taps: list                          # per tap set: (flat index of the top-left neighbour, fx, fy)
    hl: np.ndarray                      # highlight strength 0..1
    shade: np.ndarray                   # multiplier for the thickness shade


_maps: dict = {}


def _build_map(s, w: int, h: int, f: float, ox: float, oy: float, dispersion: float,
               highlight: float) -> _Map | None:
    bx0, by0, bx1, by1 = s.bounds()
    gx0 = max(0, int((bx0 - ox) * f) - 1)
    gy0 = max(0, int((by0 - oy) * f) - 1)
    gx1 = min(w, int((bx1 - ox) * f) + 2)
    gy1 = min(h, int((by1 - oy) * f) + 2)
    if gx1 <= gx0 or gy1 <= gy0:
        return None
    gy, gx = np.mgrid[gy0:gy1, gx0:gx1].astype(np.float32)
    x = (gx + 0.5) / f + ox                     # grid → logical
    y = (gy + 0.5) / f + oy
    d, nx, ny = s.sdf(x, y)
    inside = d < 0.5
    if not inside.any():
        return None
    x, y, d, nx, ny = x[inside], y[inside], d[inside], nx[inside], ny[inside]
    idx = gy[inside].astype(np.int64) * w + gx[inside].astype(np.int64)
    bevel = max(1.0, s.bevel)
    t = np.clip(1.0 + d / bevel, 0.0, 1.0)          # 0 deep inside → 1 at the edge
    pull = s.bend * bevel * (1.0 - np.sqrt(np.maximum(0.0, 1.0 - t * t)))
    cx, cy = s.center()
    mx = cx + (x - cx) / s.magnify
    my = cy + (y - cy) / s.magnify
    taps = []
    for k in ((1.0 - dispersion, 1.0, 1.0 + dispersion) if dispersion else (1.0,)):
        sx = np.clip((mx - nx * pull * k - ox) * f - 0.5, 0, w - 1.001)
        sy = np.clip((my - ny * pull * k - oy) * f - 0.5, 0, h - 1.001)
        x0, y0 = sx.astype(np.int64), sy.astype(np.int64)
        taps.append((y0 * w + x0, (sx - x0).astype(np.float32)[:, None], (sy - y0).astype(np.float32)[:, None]))
    dot = nx * LIGHT[0] + ny * LIGHT[1]
    hl = highlight * t ** 2.4 * (0.38 * np.clip(dot, 0, 1) ** 1.6 + 0.16 * np.clip(-dot, 0, 1) ** 1.6 + 0.04)
    shade = 1.0 - 0.10 * t ** 3 * np.clip(ny, 0, 1)
    return _Map(idx, taps, hl.astype(np.float32)[:, None], shade.astype(np.float32)[:, None])


def _bilinear(flat: np.ndarray, w: int, tap) -> np.ndarray:
    i, fx, fy = tap
    a, b = flat[i], flat[i + 1]
    c, d = flat[i + w], flat[i + w + 1]
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


def render(bd: Backdrop, shapes: list, origin: tuple[float, float] = (0.0, 0.0),
           dispersion: float = 0.0, highlight: float = 1.0) -> QImage:
    """Refract the backdrop through `shapes`. `origin` is where the backdrop's top-left sits in the
    shapes' coordinate system. Pixels outside every shape are left as plain frost. `dispersion` splits
    the colours slightly where the edge bends the most (costs three samples instead of one)."""
    src = bd.img
    h, w = src.shape[:2]
    out = src.copy()
    flat_out = out.reshape(-1, 3)
    flat_src = src.reshape(-1, 3)
    for s in shapes:
        key = (repr(s), w, h, round(bd.f, 5), origin, dispersion, highlight)
        m = _maps.get(key)
        if m is None:
            m = _build_map(s, w, h, bd.f, origin[0], origin[1], dispersion, highlight)
            if len(_maps) > 12:
                _maps.pop(next(iter(_maps)))
            _maps[key] = m
        if m is None:
            continue
        if len(m.taps) == 1:
            res = _bilinear(flat_src, w, m.taps[0])
        else:
            res = np.empty((m.idx.shape[0], 3), np.float32)
            for c, tap in enumerate(m.taps):
                res[:, c:c + 1] = _bilinear(src[:, :, c].reshape(-1, 1), w, tap)
        res += (255.0 - res) * m.hl
        res *= m.shade
        flat_out[m.idx] = res
    return to_qimage(out)


def brush(img: QImage, f: float, origin: QPointF | tuple[float, float] = (0.0, 0.0)) -> QBrush:
    """A brush that lays a grid-resolution glass image over logical coordinates starting at `origin`."""
    ox, oy = (origin.x(), origin.y()) if isinstance(origin, QPointF) else origin
    b = QBrush(img)
    b.setTransform(QTransform().translate(ox, oy).scale(1.0 / f, 1.0 / f))
    return b


def tint_alpha(lum: float, lo: float, hi: float) -> float:
    """Darker glass over bright backdrops (keeps white text readable), clearer over dark ones."""
    return lo + (hi - lo) * max(0.0, min(1.0, (lum - 0.15) / 0.6))

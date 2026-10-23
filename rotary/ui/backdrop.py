"""What the settings window's glass sits on: your desktop wallpaper, blurred and dimmed (like macOS
26's window tinting), or a soft colourful 'aurora' when the wallpaper can't be read.

Everything is computed once on a tiny canvas (the backdrop is meant to be soft) and scaled up smoothly
when painted, so resizing the window costs nothing."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient

log = logging.getLogger(__name__)

STYLES = [("wallpaper", "Wallpaper"), ("aurora", "Aurora"), ("plain", "Plain")]
_W, _H = 160, 100                 # the canvas everything is drawn on; scaled up smoothly when painted


def wallpaper_path() -> Path | None:
    """The desktop picture's file, if this platform says where it is (best effort, never raises)."""
    try:
        if sys.platform == "win32":
            buf = ctypes.create_unicode_buffer(520)
            if ctypes.windll.user32.SystemParametersInfoW(0x73, len(buf), buf, 0):     # SPI_GETDESKWALLPAPER
                if buf.value and Path(buf.value).is_file():
                    return Path(buf.value)
            cached = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
            return cached if cached.is_file() else None
        if sys.platform == "darwin":
            from AppKit import NSScreen, NSWorkspace
            url = NSWorkspace.sharedWorkspace().desktopImageURLForScreen_(NSScreen.mainScreen())
            path = Path(str(url.path())) if url is not None else None
            return path if path is not None and path.is_file() else None
        for key in ("picture-uri-dark", "picture-uri"):                              # GNOME and friends
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.background", key],
                                 capture_output=True, text=True, timeout=1.5).stdout.strip().strip("'")
            if out:
                path = Path(unquote(urlparse(out).path)) if out.startswith("file:") else Path(out)
                if path.is_file():
                    return path
    except Exception as e:                      # no gsettings, no AppKit, an odd wallpaper setup…
        log.debug("wallpaper: %s", e)
    return None


def _from_wallpaper() -> QImage | None:
    path = wallpaper_path()
    if path is None:
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    smooth = Qt.TransformationMode.SmoothTransformation
    img = img.scaled(_W * 3, _H * 3, Qt.AspectRatioMode.KeepAspectRatioByExpanding, smooth)
    img = img.copy((img.width() - _W * 3) // 2, (img.height() - _H * 3) // 2, _W * 3, _H * 3)
    # Down to a few dozen pixels and back: a wide, cheap blur.
    img = img.scaled(24, 15, Qt.AspectRatioMode.IgnoreAspectRatio, smooth)
    return img.scaled(_W, _H, Qt.AspectRatioMode.IgnoreAspectRatio, smooth).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)


def _aurora() -> QImage:
    img = QImage(_W, _H, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, _W, _H)
    g.setColorAt(0, QColor("#101a3d"))
    g.setColorAt(0.55, QColor("#2a1640"))
    g.setColorAt(1, QColor("#3a1f2c"))
    p.fillRect(0, 0, _W, _H, g)
    p.setPen(Qt.PenStyle.NoPen)
    for x, y, r, c in ((0.12, 0.18, 0.55, "#1f5fd6"), (0.85, 0.85, 0.6, "#c2366f"), (0.62, 0.05, 0.4, "#7a3cd6"),
                       (0.3, 0.95, 0.45, "#0f8a8a")):
        rg = QRadialGradient(QPointF(x * _W, y * _H), r * _W)
        col = QColor(c)
        col.setAlphaF(0.75)
        rg.setColorAt(0, col)
        rg.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(rg)
        p.drawEllipse(QPointF(x * _W, y * _H), r * _W, r * _W)
    p.end()
    return img


def make(style: str) -> tuple[QImage | None, str]:
    """The backdrop for `style` and the style it really is ("wallpaper" falls back to "aurora").
    "plain" gives None: the window's flat colour."""
    if style == "plain":
        return None, "plain"
    img = _from_wallpaper() if style == "wallpaper" else None
    if img is None:
        img, style = _aurora(), "aurora"
    # Dim it so white text always reads, the way a dark window tints the desktop behind it.
    p = QPainter(img)
    p.fillRect(QRectF(0, 0, _W, _H), QColor(10, 10, 14, 120 if style == "wallpaper" else 70))
    shade = QLinearGradient(0, 0, 0, _H)
    shade.setColorAt(0, QColor(0, 0, 0, 0))
    shade.setColorAt(1, QColor(0, 0, 0, 70))
    p.fillRect(QRectF(0, 0, _W, _H), shade)
    p.end()
    return img, style

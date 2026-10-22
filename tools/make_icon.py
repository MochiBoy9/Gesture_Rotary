"""Render the app icon to assets/icon.ico (Windows, multi-size), assets/icon.icns (macOS) and assets/icon.png."""
import io, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication
from rotary.app import _icon_pixmap

app = QApplication([])
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)


def render(px):
    buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly)
    _icon_pixmap(px).toImage().save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data())))


img = render(256)
img.save(out / "icon.png")
img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
render(1024).save(out / "icon.icns")       # Pillow scales it to every size macOS asks for
print("icon ok")

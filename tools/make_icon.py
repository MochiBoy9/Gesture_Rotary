"""Render the app icon to assets/icon.ico (multi-size) and assets/icon.png."""
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
buf = QBuffer(); buf.open(QIODevice.OpenModeFlag.WriteOnly)
_icon_pixmap(256).toImage().save(buf, "PNG")
img = Image.open(io.BytesIO(bytes(buf.data())))
img.save(out / "icon.png")
img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon ok")

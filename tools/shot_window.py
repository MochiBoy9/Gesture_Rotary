"""Dev tool: boot the app and save screenshots of the window's pages (never the camera page)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rotary import app as appmod

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
qapp = QApplication([]); qapp.setQuitOnLastWindowClosed(False)
r = appmod.RotaryApp(qapp, show_window=True)
r.window.resize(1160, 780)
pages = [k for k in r.window._keys if k != "camera"]
def shoot(i=0):
    if i >= len(pages):
        print("camera:", r.cam_status.state, r.cam_status.camera.label() if r.cam_status.camera else None)
        r.quit(save=False); return
    r.window.show_page(pages[i])
    QTimer.singleShot(1200, lambda: (r.window.grab().save(str(out / f"win_{pages[i]}.png")), shoot(i + 1)))
QTimer.singleShot(3000, shoot)
qapp.exec()

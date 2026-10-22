"""Dev tool: render the dial over a synthetic wallpaper to PNGs (no camera needed)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap, QRadialGradient, QFont
from PySide6.QtWidgets import QApplication
from rotary.actions import DEFAULT_CONFIG, build_items
from rotary.gestures import EngineSnapshot, Phase
from rotary.ui.dial import DialPainter
from rotary.ui.glass import blur_backdrop

def wallpaper(w, h):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, w, h); g.setColorAt(0, QColor("#1b2a6b")); g.setColorAt(0.5, QColor("#7a2d6e")); g.setColorAt(1, QColor("#e2803a"))
    p.fillRect(0, 0, w, h, g)
    for (x, y, r, c) in [(0.25, 0.3, 0.22, "#38bdf8"), (0.75, 0.65, 0.25, "#f472b6"), (0.6, 0.2, 0.12, "#fde047")]:
        rg = QRadialGradient(QPointF(x*w, y*h), r*w); rg.setColorAt(0, QColor(c)); rg.setColorAt(1, QColor(0,0,0,0))
        p.setBrush(rg); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QPointF(x*w, y*h), r*w, r*w)
    p.setPen(QColor(255,255,255,200)); f = QFont("Segoe UI", 22); p.setFont(f)
    for i in range(14): p.drawText(40, 60 + i*56, "Lorem ipsum dolor sit amet, consectetur adipiscing elit — window text " * 2)
    p.end(); return img

def render(dp, state, t_open, out, settle=1.2, exec_t=None):
    S = dp.size
    bg = wallpaper(S, S)
    dp.backdrop = blur_backdrop(QPixmap.fromImage(bg))
    dp.begin(state); dp.set_state(state)
    tt = 0
    while tt < settle: dp.tick(1/60); tt += 1/60
    if exec_t is not None:
        dp.execute(); tt = 0
        while tt < exec_t: dp.tick(1/60); tt += 1/60
    img = bg.copy(); p = QPainter(img); dp.paint(p, S, S); p.end()
    img.save(str(out))

app = QApplication([])
items = build_items(DEFAULT_CONFIG)
dp = DialPainter(items, 600)
outdir = Path(sys.argv[1]); outdir.mkdir(parents=True, exist_ok=True)
base = dict(phase=Phase.OPEN, hand_present=True, facing=True)
render(dp, EngineSnapshot(**base, position=0, selected=0), 1, outdir/"a_open.png")
render(dp, EngineSnapshot(**base, position=2.3, selected=2, interacted=True, dwell=0.55), 1, outdir/"b_dwell.png")
render(dp, EngineSnapshot(**base, position=4, selected=4, gripping=True, grip_turned=True, interacted=True), 1, outdir/"c_grip.png")
render(dp, EngineSnapshot(**base, position=6, selected=6), 1, outdir/"d_exec.png", exec_t=0.12)
from rotary.actions import default_browser
items[0].icon = default_browser() or ""
dp2 = DialPainter(items, 600)
render(dp2, EngineSnapshot(**base, position=0, selected=0, pointing=True, push=0.6, pointer=(0.9, -0.4),
                           interacted=True), 1, outdir/"e_point.png")
print("ok")

# ---- Quick nav: the Steam ring (breadcrumb + Back), badges on the main ring, and accessibility looks
from rotary import integrations
from rotary.actions import back_item, item_from
integrations.detect()
integrations.refresh_dynamic("steam", {}, None)
import time as _t
_t.sleep(0.5)
steam = [back_item("")] + [i for i in (item_from(d) for d in integrations.quicknav("steam")) if i]
dp3 = DialPainter(steam, 600)
render(dp3, EngineSnapshot(**base, position=1, selected=1), 1, outdir / "f_quicknav.png")
dp3.set_level(steam, "Steam", EngineSnapshot(**base, position=7, selected=7))
img = wallpaper(dp3.size, dp3.size); p = QPainter(img)
for _ in range(80): dp3.tick(1 / 60)
dp3.paint(p, dp3.size, dp3.size); p.end(); img.save(str(outdir / "f_quicknav.png"))
main = items[:6] + [item_from(integrations.quicknav_item(a)) for a in ("discord", "obs")]
dp4 = DialPainter(main, 600)
dp4.set_accessibility(1.35, True, True)
render(dp4, EngineSnapshot(**base, position=6, selected=6), 1, outdir / "g_contrast.png")
print("extra ok")

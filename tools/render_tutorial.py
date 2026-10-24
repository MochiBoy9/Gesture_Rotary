"""Dev tool: render every card of the first-run tour into one PNG (no camera needed).

    uv run python tools/render_tutorial.py out [--mouse]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rotary import tutorial  # noqa: E402
from rotary.ui.glass import load_fonts, set_text_font  # noqa: E402
from rotary.ui.tutorial import TutorialWindow  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "out")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    load_fonts()
    set_text_font("")
    mouse = "--mouse" in sys.argv
    steps = tutorial.steps_for(tutorial.Context(camera=not mouse, notch=mouse))
    win = TutorialWindow(steps, {"assist": ["Win", "Alt", "A"]}, reduce_motion=True)
    cols = 2
    rows = (len(steps) + cols - 1) // cols
    pad = 20
    sheet = QImage(cols * (win.W + pad) + pad, rows * (win.H + pad) + pad, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(sheet)
    g = QLinearGradient(0, 0, sheet.width(), sheet.height())
    g.setColorAt(0, QColor("#1b2a6b"))
    g.setColorAt(1, QColor("#e2803a"))
    p.fillRect(sheet.rect(), g)
    for i in range(len(steps)):
        win.tour.go(i)
        win._show_step()
        if steps[i].goal and i % 3 == 2:
            win.tour.reached.add(steps[i].key)       # show the ticked state on a few
            win._reached()
            win._advance.stop()
        win.adjustSize()
        win.layout().activate()
        win.render(p, QPoint(pad + (i % cols) * (win.W + pad), pad + (i // cols) * (win.H + pad)))
    p.end()
    path = out / ("tutorial-mouse.png" if mouse else "tutorial.png")
    sheet.save(str(path))
    print(path)
    app.quit()


if __name__ == "__main__":
    main()

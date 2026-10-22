"""Boot the full app against the real camera for a few seconds and report health."""
import sys, time, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rotary import app as appmod


logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
qapp = QApplication([]); qapp.setQuitOnLastWindowClosed(False)
r = appmod.RotaryApp(qapp)
stats = {"results": 0, "hand": 0, "events": []}
orig_handle = r._handle
def handle(evs):
    stats["events"] += [e for e in evs]; orig_handle(evs)
r._handle = handle
r.tracker.result.connect(lambda res: (stats.__setitem__("results", stats["results"] + 1),
                                      stats.__setitem__("hand", stats["hand"] + (1 if res.hands else 0))))
def step1():
    st = r.cam_status
    print("CAMERA", st.state, st.camera.label() if st.camera else None, "cap", round(st.capture_fps), "trk", round(st.infer_fps))
    r.pill.grab().save(str(out / "pill.png"))
    r.manual_open()
def step2():
    print("DIAL visible", r.dial.isVisible(), "phase", r.engine.phase, "geom", r.dial.geometry().getRect())
    r._handle(r.engine.force_close(time.monotonic()))
def step3():
    print("DIAL visible after close", r.dial.isVisible(), "phase", r.engine.phase)
    print("RESULTS", stats["results"], "frames-with-hand", stats["hand"], "events", stats["events"])
    r.quit()
QTimer.singleShot(9000, step1); QTimer.singleShot(11000, step2); QTimer.singleShot(12500, step3)
qapp.exec()

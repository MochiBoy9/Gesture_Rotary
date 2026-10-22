import sys
import wave

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication

from rotary import feedback, tracker
from rotary.actions import DEFAULT_CONFIG, build_items
from rotary.gestures import EngineSnapshot, Phase
from rotary.ui import liquid
from rotary.ui.dial import DialWindow, angle_point
from rotary.ui.notch import NotchWindow
from rotary.ui.settings import input_mode, set_input_mode

app = QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ liquid glass
def _stripes(w=200, h=200) -> QPixmap:
    """A left-to-right ramp: any sideways bend shows up as a change in brightness."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    for x in range(w):
        v = int(255 * x / (w - 1))
        for y in range(h):
            img.setPixelColor(x, y, QColor(v, v, v))
    return QPixmap.fromImage(img)


def test_backdrop_is_half_size_and_knows_its_brightness():
    bd = liquid.Backdrop.from_pixmap(_stripes())
    assert bd.img.shape == (100, 100, 3)
    assert bd.f == pytest.approx(0.5)
    assert 0.35 < bd.lum < 0.65
    assert liquid.Backdrop.from_pixmap(QPixmap()) is None


def test_glass_bends_the_edge_but_not_the_middle():
    bd = liquid.Backdrop.from_pixmap(_stripes())
    flat = liquid.render(bd, [liquid.Circle(100, 100, 80, bevel=20, bend=0.9)], highlight=0.0)
    arr = liquid.to_rgb(flat).astype(int)
    src = bd.img.astype(int)
    assert np.abs(arr[50, 50] - src[50, 50]).max() <= 2           # centre: clear, undistorted
    assert np.abs(arr[2, 2] - src[2, 2]).max() == 0                # outside the glass: untouched
    rim = (slice(46, 54), slice(10, 16))                           # just inside the left edge
    pulled = arr[rim] - src[rim]
    assert pulled.min() >= 0 and pulled.max() > 8                  # the bevel pulls the backdrop in (from the right)


def test_glass_geometry_is_reused():
    bd = liquid.Backdrop.from_pixmap(_stripes())
    shape = liquid.Annulus(100, 100, 40, 80)
    liquid.render(bd, [shape])
    n = len(liquid._maps)
    liquid.render(bd, [shape])
    assert len(liquid._maps) == n


def test_tint_darkens_over_bright_backdrops():
    assert liquid.tint_alpha(0.9, 0.2, 0.6) > liquid.tint_alpha(0.1, 0.2, 0.6)


# ------------------------------------------------------------------ notch
def _settle(n: NotchWindow):
    for _ in range(90):
        for sp in n._springs:
            sp.step(1 / 60)


def test_notch_grows_for_status_and_hover_then_rests():
    n = NotchWindow()
    _settle(n)
    rest = n.body_rect().width()
    n.set_status("Opening a fairly long application name", "done", "#30D158")
    _settle(n)
    assert n.body_rect().width() > rest + 100
    n.set_status("", hidden=True)
    n.hovered = True
    n._retarget()
    _settle(n)
    assert n.body_rect().width() > rest
    n.hovered = False
    n.set_peek(True)
    _settle(n)
    assert n.body_rect().height() < 8


def test_notch_click_and_wheel():
    n = NotchWindow()
    got = []
    n.clicked.connect(lambda: got.append("click"))
    n.scrolled.connect(lambda s: got.append(s))
    n.mousePressEvent(type("E", (), {"button": lambda self: Qt.MouseButton.LeftButton,
                                     "position": lambda self: QPointF(5, 5)})())
    for dy in (-120, -60, -60, 120):
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        n.wheelEvent(ev)
    assert got == ["click", 1, 1, -1]          # wheel down = next; half notches add up


@pytest.mark.parametrize("mode,camera,notch", [("camera", True, "auto"), ("notch", False, "on"),
                                               ("both", True, "on")])
def test_input_modes_round_trip(mode, camera, notch):
    gen = {}
    set_input_mode(gen, mode)
    assert (gen["camera"], gen["notch"]) == (camera, notch)
    assert input_mode(gen) == mode


# ------------------------------------------------------------------ the rotary under the mouse
def test_dial_hit_test_finds_items_and_centre():
    d = DialWindow(build_items(DEFAULT_CONFIG), 600)
    dp = d.painter_
    dp.begin(EngineSnapshot(phase=Phase.OPEN, selected=0, position=0))
    R, Rin, Rmid, rc, lens_r = dp._geom()
    cx, cy = d.width() / 2, d.height() / 2
    assert d.hit(QPointF(cx, cy)) == ("centre", 0)
    top = angle_point(Rmid, 0)
    assert d.hit(QPointF(cx + top.x(), cy + top.y())) == ("item", 0)
    n = len(dp.items)
    p2 = angle_point(Rmid, 2 * 360 / n)
    assert d.hit(QPointF(cx + p2.x(), cy + p2.y())) == ("item", 2)
    gap = angle_point(Rmid, 0.5 * 360 / n)
    assert d.hit(QPointF(cx + gap.x(), cy + gap.y()))[0] == "ring"
    assert d.hit(QPointF(2, 2)) == ("", 0)


def test_dial_ignores_the_mouse_when_opened_by_a_gesture():
    d = DialWindow(build_items(DEFAULT_CONFIG), 600)
    got = []
    d.mouse.connect(lambda k, v: got.append(k))
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    d.wheelEvent(ev)
    assert got == []
    d._set_interactive(True)
    d.wheelEvent(ev)
    assert got == ["turn"]


# ------------------------------------------------------------------ sounds & the slim MediaPipe import
def test_sound_volume_is_baked_into_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback.tempfile, "gettempdir", lambda: str(tmp_path))

    def peak(v):
        s = feedback.Sounds(True, v)
        with wave.open(s.files["tick"]) as w:
            return np.abs(np.frombuffer(w.readframes(w.getnframes()), "<i2")).max()
    assert peak(0.2) < peak(0.8)


def test_mediapipe_gets_stand_ins_for_what_we_leave_out():
    tracker._install_stubs()
    tracker._install_stubs()
    assert sum(isinstance(f, tracker._StubFinder) for f in sys.meta_path) == 1
    import importlib
    mod = importlib.import_module("mediapipe.tasks.python.vision.drawing_utils")
    assert not hasattr(mod, "plt")

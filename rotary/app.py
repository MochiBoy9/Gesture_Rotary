"""Application wiring: tracker → gesture engine → overlay UI → actions."""
from __future__ import annotations

import ctypes
import logging
import math
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QFileSystemWatcher, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QGuiApplication, QIcon, QLinearGradient, QPainter, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from . import DATA_DIR, MAC, T0, WIN, assist, integrations, system, winapi
from .actions import (CONFIG_PATH, back_item, build_items, cleanup_scripts, execute, item_from, load_config,
                      save_config)
from .feedback import Sounds, Speaker
from .live import LiveWatcher
from .gestures import GestureEngine, GestureSettings, HandednessTracker, HandFeatures, Phase, extract_features
from .tracker import CameraStatus, TrackerThread, TrackResult
from .ui.dial import DialWindow
from .ui.glass import load_fonts
from .ui.notch import NotchWindow
from .ui.pill import AMBER, BLUE, GRAY, GREEN, RED, PillWindow

log = logging.getLogger(__name__)
INSTANCE_KEY = "GestureRotary.single-instance"
APP_ID = "GestureRotary.App"


def fullscreen_state() -> int:
    """Windows' own 'busy' signal, as used to hold back notifications: 2 = something is full screen
    (borderless games, videos), 3 = a Direct3D game owns the screen exclusively, 4 = presentation mode;
    anything else = normal desktop."""
    if sys.platform != "win32":
        return 0
    state = ctypes.c_int(0)
    try:
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
            return 0
    except Exception:
        return 0
    return state.value


def fullscreen_app_running() -> bool:
    return fullscreen_state() in (2, 3, 4)


# --------------------------------------------------------------------------- global hotkeys
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
HOTKEYS = {"ctrl+alt+space": (MOD_CONTROL | MOD_ALT, 0x20), "ctrl+shift+space": (MOD_CONTROL | MOD_SHIFT, 0x20),
           "ctrl+alt+r": (MOD_CONTROL | MOD_ALT, 0x52), "win+alt+space": (MOD_WIN | MOD_ALT, 0x20)}
HOTKEY_LABELS = {"ctrl+alt+space": "Ctrl + Alt + Space", "ctrl+shift+space": "Ctrl + Shift + Space",
                 "ctrl+alt+r": "Ctrl + Alt + R", "win+alt+space": "Win + Alt + Space"}
if MAC:
    HOTKEY_LABELS = {"ctrl+alt+space": "⌃⌥Space", "ctrl+shift+space": "⌃⇧Space", "ctrl+alt+r": "⌃⌥R",
                     "win+alt+space": "⌥⌘Space"}
elif not WIN:
    HOTKEY_LABELS["win+alt+space"] = "Super + Alt + Space"
HK_TOGGLE = 1
HK_ASSIST = 2
ASSIST_HOTKEYS = {"win+alt+a": (MOD_WIN | MOD_ALT, 0x41), "ctrl+alt+a": (MOD_CONTROL | MOD_ALT, 0x41),
                  "ctrl+shift+a": (MOD_CONTROL | MOD_SHIFT, 0x41)}
NAV = {11: (0x25, -1), 12: (0x27, 1), 13: (0x26, -1), 14: (0x28, 1), 15: (0x0D, 0), 16: (0x1B, 0)}  # ← → ↑ ↓ ⏎ Esc


class HotkeyWindow(QWidget):
    """An invisible native window that receives RegisterHotKey messages. On macOS (Carbon hotkeys) and
    Linux (an X11 key grab) the same calls go to posix.py, and `triggered` fires all the same."""
    triggered = Signal(int)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.active: set[int] = set()
        self.backend = None
        if WIN:
            self.hwnd = int(self.winId())
        else:
            from . import posix
            self.backend = posix.hotkeys(self.triggered.emit)   # a queued signal when it fires off-thread

    def register(self, hid: int, mods: int, vk: int) -> bool:
        if not WIN:
            ok = self.backend is not None and self.backend.register(hid, mods & ~MOD_NOREPEAT, vk)
        else:
            ok = bool(winapi.user32.RegisterHotKey(self.hwnd, hid, mods, vk))
        if ok:
            self.active.add(hid)
        return ok

    def unregister(self, hid: int) -> None:
        if hid in self.active:
            if WIN:
                winapi.user32.UnregisterHotKey(self.hwnd, hid)
            elif self.backend is not None:
                self.backend.unregister(hid)
        self.active.discard(hid)

    def nativeEvent(self, event_type, message):
        if not WIN:
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312:                          # WM_HOTKEY
                self.triggered.emit(int(msg.wParam))
                return True, 0
        except Exception:
            pass
        return False, 0


# --------------------------------------------------------------------------- icons
def _icon_pixmap(px: int, active: bool = True, tile: bool = True) -> QPixmap:
    """App icon: a glass dial with the selection lens at 12 o'clock."""
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = px / 64.0
    if tile:
        g = QLinearGradient(0, 0, 0, px)
        g.setColorAt(0, QColor("#2a2d3a"))
        g.setColorAt(1, QColor("#0f1016"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)
        glow = QRadialGradient(QPointF(32 * s, 34 * s), 30 * s)
        glow.setColorAt(0, QColor(10, 132, 255, 90))
        glow.setColorAt(1, QColor(10, 132, 255, 0))
        p.setBrush(glow)
        p.drawEllipse(QPointF(32 * s, 34 * s), 30 * s, 30 * s)
    c = QPointF(32 * s, 33 * s)
    alpha = 235 if active else 120
    p.setPen(QPen(QColor(255, 255, 255, alpha), (5.0 if tile else 6.0) * s))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = (19 if tile else 24) * s
    p.drawEllipse(c, r, r)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#0A84FF") if active else QColor("#8E8E93"))
    p.drawEllipse(QPointF(c.x(), c.y() - r), 7.5 * s, 7.5 * s)
    p.setBrush(QColor(255, 255, 255, alpha))
    p.drawEllipse(c, 5.5 * s, 5.5 * s)
    p.end()
    return pm


def brand_icon() -> QIcon:
    icon = QIcon()
    for px in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_icon_pixmap(px))
    return icon


def tray_icon(active: bool = True) -> QIcon:
    return QIcon(_icon_pixmap(64, active, tile=False))


# --------------------------------------------------------------------------- face test & hand choice
def hand_at_face(bbox: tuple[float, float, float, float], faces: list) -> bool:
    """Is the hand resting on / covering the face or propping up the chin?
    A hand raised beside the head is *not* at the face."""
    hx0, hy0, hx1, hy1 = bbox
    ha = max((hx1 - hx0) * (hy1 - hy0), 1e-6)
    cx, cy = (hx0 + hx1) / 2, (hy0 + hy1) / 2
    for fx0, fy0, fx1, fy1 in faces:
        fw, fh = fx1 - fx0, fy1 - fy0
        if fx0 <= cx <= fx1 and fy0 <= cy <= fy1:
            return True
        zx0, zx1 = fx0 - 0.15 * fw, fx1 + 0.15 * fw
        zy0, zy1 = fy0 + 0.45 * fh, fy1 + 0.8 * fh
        ix = max(0.0, min(hx1, zx1) - max(hx0, zx0))
        iy = max(0.0, min(hy1, zy1) - max(hy0, zy0))
        if ix * iy / ha > 0.35:
            return True
    return False


def pick_hand(feats: list[HandFeatures], faces: list, prev: tuple[float, float] | None) -> tuple[int, bool]:
    """Which hand to follow: the one being held up on purpose, preferring the one we already follow.
    Returns (index, is_same_hand_as_before)."""
    if not feats:
        return -1, False
    best, best_score, same = -1, -1e9, False
    for i, f in enumerate(feats):
        near_prev = prev is not None and math.hypot(f.center[0] - prev[0], f.center[1] - prev[1]) < 0.25
        score = (f.scale * 4 + (1.5 if f.facing > 0.2 else 0.0) + (1.0 if f.upright_dev < 60 else 0.0)
                 - (2.5 if hand_at_face(f.bbox, faces) else 0.0) + (1.2 if near_prev else 0.0))
        if score > best_score:
            best, best_score, same = i, score, near_prev
    return best, same


# --------------------------------------------------------------------------- app
class RotaryApp(QObject):
    action_done = Signal(str, bool, str)   # item name, ok, error
    dynamic_ready = Signal(str)            # an app's games / scenes / projects were refreshed
    assist_done = Signal(object, str)      # screen assist: the Answer (or None), error

    def __init__(self, app: QApplication, show_window: bool | None = None):
        super().__init__()
        self.app = app
        self.quitting = False
        load_fonts()                             # the bundled icon font on macOS / Linux
        self.app_icon = brand_icon()
        app.setWindowIcon(self.app_icon)
        self.cfg = load_config()
        install_changed = system.refresh_install(self.cfg)
        self.items = build_items(self.cfg)       # the top-level ring
        self.level_items = self.items            # what the ring shows right now
        self.levels: list[tuple[list, int, str]] = []
        self.crumb = ""
        self._qn_app = ""
        self.settings = GestureSettings.from_dict(self.cfg.get("gestures"))
        self.engine = GestureEngine(len(self.items), self.settings)
        self.hands = HandednessTracker()
        ap = self.cfg.get("appearance", {})
        self.sounds = Sounds(bool(ap.get("sounds", True)), float(ap.get("volume", 0.6)))
        self.speaker = Speaker()
        self.dial = DialWindow(self.items, int(ap.get("dial_size", 600)), bool(ap.get("live_glass", False)))
        self.dial.mouse.connect(self._on_dial_mouse)
        self.pill_enabled = bool(ap.get("status_pill", True))
        self.pill = PillWindow()
        self.notch = NotchWindow()
        self.notch.clicked.connect(self._on_notch_click)
        self.notch.scrolled.connect(self._on_notch_scroll)
        self.notch.customize.connect(lambda: self.show_window("notch"))
        self.notch.timer_done.connect(self._on_timer_done)
        self.notch.assist.connect(self.start_assist)
        self._assist_busy = False
        self._assist_until = 0.0           # keeps the notch up for a screen-assist message
        self.live = LiveWatcher(self)
        self.live.state.connect(self.notch.set_live)
        self.live.event.connect(self._on_live_event)
        self.notch.media_command.connect(self.live.control)
        self.notch.call_command.connect(self._on_call_command)
        self._fs_state = 0
        self._alert_until = 0.0            # a clip / timer alert may show the notch over a full-screen game
        self._fullscreen = False
        self._fs_checked = 0.0
        self.hotkeys = HotkeyWindow()
        self.hotkeys.triggered.connect(self._on_hotkey)
        if not WIN:
            from . import posix
            posix.prepare_keyboard()           # macOS: has to happen on this (the main) thread
        self._hotkey_now = None
        self._assist_hotkey_now = None
        self.keyboard_session = False      # opened from the keyboard or the notch: mouse + arrow keys work
        self._kb_fg = 0                    # the window that was in front when it opened

        gen = self.cfg.get("general", {})
        self.camera_on = bool(gen.get("camera", True))
        self.cam_status = CameraStatus("searching" if self.camera_on else "off",
                                       message="Starting…" if self.camera_on else "Camera gestures are off")
        self._no_cam_since: float | None = None if self.camera_on else time.monotonic() - 60
        self._prev_center: tuple[float, float] | None = None
        self._last_result_t = time.monotonic()
        self._last_hand_t = 0.0
        self._last_dbg = 0.0
        self._cam_lost_t = time.monotonic()
        self._flash: tuple[str, str, str, float] | None = None  # text, kind, accent, until
        self._calib: list[float] | None = None
        self._calib_until = 0.0

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._save_cfg)
        self._speak_timer = QTimer(self)
        self._speak_timer.setSingleShot(True)
        self._speak_timer.setInterval(260)
        self._speak_timer.timeout.connect(self._speak_current)

        prefer = (self.cfg.get("camera") or {}).get("preferred") or None
        self.tracker = TrackerThread(prefer_camera=prefer)
        self.tracker.result.connect(self.on_result)
        self.tracker.status.connect(self.on_status)
        self.action_done.connect(self._on_action_done)
        self.dynamic_ready.connect(self._on_dynamic)
        self.assist_done.connect(self._on_assist_done)

        from .ui.settings import MainWindow
        self.window = MainWindow(self)

        self._build_tray()
        self._watch_config()
        self.apply_config(save=install_changed)

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(100)
        self._heartbeat.timeout.connect(self._on_heartbeat)
        self._heartbeat.start()

        app.commitDataRequest.connect(self._session_ending)
        app.aboutToQuit.connect(self._shutdown)
        app.primaryScreenChanged.connect(lambda _s: self.notch.place())
        if self.camera_on:
            self.tracker.start()
        else:
            self.engine.paused = True
        threading.Thread(target=self.refresh_apps, daemon=True, name="apps").start()
        threading.Thread(target=cleanup_scripts, daemon=True).start()
        self._update_notch()
        self._update_pill()
        onboarded = self.cfg.get("general", {}).get("onboarded", False)
        if show_window is None:
            show_window = (not onboarded) or not self.cfg.get("general", {}).get("start_minimized", True)
        if show_window:
            self.show_window()
        else:
            self.window.showMinimized()   # lives on the taskbar
        QTimer.singleShot(2500, self.dial.prewarm)
        log.info("ready in %.0f ms (camera %s)", (time.perf_counter() - T0) * 1000, "on" if self.camera_on else "off")

    # ------------------------------------------------------------ window / tray
    def show_window(self, page: str | None = None) -> None:
        if page:
            self.window.show_page(page)
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(tray_icon(True), self)
        self.tray.setToolTip("Gesture Rotary")
        m = QMenu()
        m.addAction("Open Gesture Rotary", self.show_window)
        m.addAction("Open rotary now", self.manual_open)
        m.addSeparator()
        self.cam_menu = m.addMenu("Camera")
        self._fill_camera_menu()
        m.addAction("Calibrate palm direction", self.start_calibration)
        self.pause_action = QAction("Pause (camera off)", m, checkable=True)
        self.pause_action.toggled.connect(self.set_paused)
        self.pause_action.setEnabled(self.camera_on)
        m.addAction(self.pause_action)
        m.addSeparator()
        m.addAction("Quit", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_window()
                                    if r in (QSystemTrayIcon.ActivationReason.Trigger,
                                             QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self._menu = m
        self.tray.show()

    def _fill_camera_menu(self) -> None:
        self.cam_menu.clear()
        group = QActionGroup(self.cam_menu)
        cur = self.cam_status.camera.key if self.cam_status.camera else None
        for c in self.cam_status.cameras:
            a = QAction(c.label(), self.cam_menu, checkable=True)
            a.setChecked(c.key == cur)
            a.triggered.connect(lambda _=False, k=c.key: self.tracker.select_camera(k))
            group.addAction(a)
            self.cam_menu.addAction(a)
        if not self.cam_status.cameras:
            a = self.cam_menu.addAction("No cameras found")
            a.setEnabled(False)
        self.cam_menu.addSeparator()
        self.cam_menu.addAction("Rescan cameras", self.tracker.rescan)

    def set_paused(self, paused: bool) -> None:
        self.engine.paused = paused or not self.camera_on
        if self.tracker.isRunning():
            self.tracker.set_paused(paused or not self.camera_on)
        cam = self.window.page("camera")
        for sw in (self.pause_action,) + ((cam.pause,) if cam is not None else ()):
            if sw.isChecked() != paused:
                if hasattr(sw, "set_silent"):
                    sw.set_silent(paused)
                else:
                    sw.blockSignals(True)
                    sw.setChecked(paused)
                    sw.blockSignals(False)
        self.tray.setIcon(tray_icon(not paused))
        if paused and self.engine.phase == Phase.OPEN:
            self._handle(self.engine.force_close(time.monotonic(), "paused"))
        self._update_pill()

    def _set_camera(self, on: bool) -> None:
        """Camera gestures on or off. Off, the camera and the hand-tracking model are never loaded."""
        if on == self.camera_on:
            return
        self.camera_on = on
        paused = self.pause_action.isChecked()
        self.pause_action.setEnabled(on)
        if on:
            self.engine.paused = paused
            self._no_cam_since = None
            self.cam_status = CameraStatus("searching", message="Starting…")
            if self.tracker.isRunning():
                self.tracker.set_paused(paused)
            else:
                self.tracker.start()
        else:
            self.engine.paused = True
            if self.tracker.isRunning():
                self.tracker.set_paused(True)        # lets go of the camera; the light goes off
            self.cam_status = CameraStatus("off", message="Camera gestures are off")
            self._no_cam_since = time.monotonic() - 60
        log.info("camera gestures %s", "on" if on else "off")

    def manual_open(self) -> None:
        self.open_manual()

    def test_item(self, item) -> None:
        if item.kind == "quicknav":
            if self.engine.phase != Phase.OPEN:
                self.manual_open()
            self._enter_quicknav(item)
            return
        if item.kind == "back":
            return
        if item.kind == "assist":
            self.start_assist()
            return
        self._flash_msg(f"Testing {item.name}…", "dot", BLUE, 1.0)
        self._run_action(item)

    # ------------------------------------------------------------ config
    def _watch_config(self) -> None:
        self.watcher = QFileSystemWatcher([str(CONFIG_PATH)], self)
        self.watcher.fileChanged.connect(lambda _p: QTimer.singleShot(300, self.reload_config))

    def apply_config(self, save: bool = True) -> None:
        """Apply self.cfg (edited in the window) right away; save shortly after."""
        self.items = build_items(self.cfg)
        if not self.levels:
            self.level_items = self.items
            if self.engine.n != len(self.items):
                self.engine.set_item_count(len(self.items))
            self.dial.set_items(self.items)
        self.settings = GestureSettings.from_dict(self.cfg.get("gestures"))
        self.engine.s = self.settings
        ap = self.cfg.get("appearance", {})
        self.dial.set_dial_size(int(ap.get("dial_size", 600)))
        self.dial.live_glass = bool(ap.get("live_glass", False))
        self.dial.painter_.set_accessibility(ap.get("text_scale", 1.0), ap.get("high_contrast", False),
                                             ap.get("reduce_motion", False))
        self.dial.painter_.controls = self.settings.to_dict()
        self.sounds.enabled = bool(ap.get("sounds", True))
        self.sounds.set_volume(float(ap.get("volume", 0.6)))
        self.speaker.enabled = bool(ap.get("speak", False))
        self.pill_enabled = bool(ap.get("status_pill", True))
        if not self.pill_enabled:
            self.pill.set_status("", hidden=True)
            self.notch.set_status("", hidden=True)
        gen = self.cfg.get("general", {})
        self._set_camera(bool(gen.get("camera", True)))
        self.notch.set_accessibility(ap.get("text_scale", 1.0), ap.get("high_contrast", False),
                                     ap.get("reduce_motion", False))
        self.notch.set_peek(bool(gen.get("notch_peek", False)))
        island = self.cfg.get("island", {})
        self.notch.set_options(island)
        self.live.configure(island)
        self.notch.set_hotkey(HOTKEY_LABELS.get(gen.get("hotkey", "ctrl+alt+space"), ""))
        self._register_hotkey()
        self._update_notch()
        self._update_pill()
        if save:
            self._save_timer.start()

    def reload_config(self) -> None:
        """config.json was edited outside the app."""
        if str(CONFIG_PATH) not in self.watcher.files() and CONFIG_PATH.exists():
            self.watcher.addPath(str(CONFIG_PATH))
        self.cfg = load_config()
        self.apply_config(save=False)
        if self.window.built:
            self.window.rotary.reload(self.window.rotary.list.currentRow())
            self.window.gestures.refresh()
            self.window.apps.sync_switches()
            self.window.notch.refresh()
            self.window.assist.refresh()
        self._flash_msg(f"Loaded {len(self.items)} items", "done", GREEN)
        log.info("config reloaded: %d items", len(self.items))

    def _save_cfg(self) -> None:
        self.watcher.removePath(str(CONFIG_PATH))
        try:
            save_config(self.cfg)
        except OSError:
            log.exception("couldn't save settings")
        QTimer.singleShot(600, lambda: self.watcher.addPath(str(CONFIG_PATH)))

    def refresh_apps(self, force: bool = False) -> None:
        """Detect installed apps and warm their games / projects / scenes (background-safe)."""
        try:
            integrations.detect(force=force)
            for a in integrations.installed():
                if a.spec.dynamic is not None:
                    integrations.refresh_dynamic(a.id, self.cfg, self.dynamic_ready.emit, force=force)
        except Exception:
            log.exception("app detection failed")

    # ------------------------------------------------------------ hotkeys
    def _register_hotkey(self) -> None:
        want = self.cfg.get("general", {}).get("hotkey", "ctrl+alt+space")
        if want != self._hotkey_now:
            self.hotkeys.unregister(HK_TOGGLE)
            self._hotkey_now = want
            if want in HOTKEYS:
                mods, vk = HOTKEYS[want]
                if not self.hotkeys.register(HK_TOGGLE, mods | MOD_NOREPEAT, vk):
                    self._flash_msg(f"{want.replace('+', ' + ').title()} is used by another app", "error", AMBER, 4.0)
        want = assist.settings(self.cfg)["hotkey"]
        if want != self._assist_hotkey_now:
            self.hotkeys.unregister(HK_ASSIST)
            self._assist_hotkey_now = want
            if want in ASSIST_HOTKEYS:
                mods, vk = ASSIST_HOTKEYS[want]
                if not self.hotkeys.register(HK_ASSIST, mods | MOD_NOREPEAT, vk):
                    self._flash_msg(f"{want.replace('+', ' + ').title()} is used by another app", "error", AMBER, 4.0)

    def _nav_keys(self, on: bool) -> None:
        for hid, (vk, _d) in NAV.items():
            if on:
                self.hotkeys.register(hid, 0, vk)
            else:
                self.hotkeys.unregister(hid)

    def _end_keyboard(self) -> None:
        if self.keyboard_session:
            self.keyboard_session = False
            self.dial.painter_.keyboard = False
            self._nav_keys(False)
        self.notch.set_active(False)

    def open_manual(self) -> None:
        """Open the rotary for the mouse and keyboard (shortcut, notch, tray, window button)."""
        now = time.monotonic()
        if self.engine.phase == Phase.OPEN:
            return
        self.keyboard_session = True
        self._kb_fg = winapi.user32.GetForegroundWindow() if sys.platform == "win32" else 0
        ev = self.engine.force_open(now)
        if ev:
            self._nav_keys(True)
            self.notch.set_active(True)
        else:
            self.keyboard_session = False
        self._handle(ev)

    def _close_manual(self, reason: str) -> None:
        self._handle(self.engine.force_close(time.monotonic(), reason))

    def _on_hotkey(self, hid: int) -> None:
        now = time.monotonic()
        if hid == HK_ASSIST:
            self.start_assist()
            return
        if hid == HK_TOGGLE:
            if self.engine.phase == Phase.OPEN:
                self._close_manual("keyboard")
            else:
                self.open_manual()
            return
        if hid in NAV and self.engine.phase == Phase.OPEN:
            vk, delta = NAV[hid]
            if vk == 0x0D:
                self._handle(self.engine.key_execute(now))
            elif vk == 0x1B:
                if self.levels:
                    self._go_back()
                else:
                    self._close_manual("keyboard")
            else:
                self._handle(self.engine.key_step(delta, now))
            self.dial.set_state(self.engine.snapshot())

    # ------------------------------------------------------------ notch & mouse
    def _on_notch_click(self) -> None:
        if self.engine.phase == Phase.OPEN:
            self._close_manual("notch")
        else:
            self.open_manual()

    def _on_notch_scroll(self, steps: int) -> None:
        if self.engine.phase != Phase.OPEN:
            self.open_manual()
        elif self.keyboard_session:
            self._handle(self.engine.key_step(steps, time.monotonic()))
            self.dial.set_state(self.engine.snapshot())

    def _on_dial_mouse(self, kind: str, n: int) -> None:
        if self.engine.phase != Phase.OPEN:
            return
        now = time.monotonic()
        if kind == "turn":
            self._handle(self.engine.key_step(n, now))
        elif kind == "select":
            count = len(self.level_items)
            d = (n - self.engine.selected) % count
            self._handle(self.engine.key_step(d - count if d > count / 2 else d, now))
        elif kind == "open":
            self._handle(self.engine.key_execute(now))
        elif kind == "back":
            if self.levels:
                self._go_back()
            else:
                self._close_manual("mouse")
        if self.engine.phase == Phase.OPEN:
            self.dial.set_state(self.engine.snapshot())

    def _alert(self, text: str, kind: str, accent: str, seconds: float = 3.5) -> None:
        """A moment worth a glance. Over a borderless full-screen game the notch pops up briefly to show it
        (never over an exclusive full-screen one — that could knock the game out of full screen)."""
        island = self.cfg.get("island", {})
        if (self._fullscreen and self.notch.isHidden() and self._notch_wanted()
                and island.get("alerts_over_games", True) and self._fs_state == 2):
            self._alert_until = time.monotonic() + seconds
            self._update_notch()
            QTimer.singleShot(int(seconds * 1000) + 300, self._update_notch)
        self._flash_msg(text, kind, accent, seconds)

    def _on_live_event(self, name: str, data: dict) -> None:
        island = self.cfg.get("island", {})
        if name == "clip" and island.get("clips", True):
            what = "Screenshot saved" if data.get("kind") == "screenshot" else "Clip saved"
            self.sounds.play("confirm")
            self._alert(f"{what} · {data.get('who', '')}", "clip", GREEN)
        elif name == "power" and island.get("battery", True):
            pct = data.get("percent", 0)
            self._alert(f"Charging · {pct}%" if data.get("plugged") else f"On battery · {pct}%", "power",
                        GREEN if data.get("plugged") else GRAY, 2.5)
        elif name == "battery_low" and island.get("battery", True):
            pct = data.get("percent", 0)
            self._alert(f"Battery low · {pct}%", "power", RED if pct <= 10 else AMBER, 5.0)

    CALL_KEYS = {("Discord", "mute"): ("discord", "ctrl+shift+m", ""),
                 ("Discord", "deafen"): ("discord", "ctrl+shift+d", ""),
                 ("Teams", "mute"): ("teams", "ctrl+shift+m", ""),
                 ("Zoom", "mute"): ("zoom", "alt+a", "Meeting")}

    def _on_call_command(self, app_name: str, what: str) -> None:
        """Mute / deafen from the notch's call card: the app's own shortcut, sent to its window."""
        app_id, keys, title = self.CALL_KEYS.get((app_name, what), ("", "", ""))
        a = integrations.get(app_id) if app_id else None
        if a is None:
            return
        action = a.keys(keys, prefer_title=title)
        label = {"mute": "Mute", "deafen": "Deafen"}.get(what, what)

        def work():
            try:
                execute(action, self.cfg)
                self.action_done.emit(f"{app_name} · {label}", True, "")
            except Exception as e:
                self.action_done.emit(f"{app_name} · {label}", False, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_timer_done(self) -> None:
        self.sounds.play("confirm")
        QTimer.singleShot(450, lambda: self.sounds.play("confirm"))
        self._say("Timer done")
        self._alert("Timer done", "timer", AMBER, 6.0)

    def _notch_wanted(self) -> bool:
        mode = self.cfg.get("general", {}).get("notch", "auto")
        if mode == "off":
            return False
        if mode == "on" or self._assist_showing():
            return True
        # auto: when there's no camera to use (switched off, or none found for a few seconds)
        return self._no_cam_since is not None and time.monotonic() - self._no_cam_since > 4.0

    def _update_notch(self) -> None:
        gen = self.cfg.get("general", {})
        wanted = self._notch_wanted()
        # Alerts and screen-assist answers may show over a borderless full-screen game, never an exclusive one.
        alert = time.monotonic() < self._alert_until or (self._assist_showing() and self._fs_state != 3)
        show = wanted and (alert or not (self._fullscreen and gen.get("notch_hide_fullscreen", True)))
        # The live activities keep watching while a game hides the notch, so a saved clip can still pop up.
        if wanted and not self.live.isRunning():
            self.live.start()
        elif not wanted and self.live.isRunning():
            self.live.stop()
        if show != self.notch.isVisible():
            why = ("on" if show else "off") + f" (setting {gen.get('notch', 'auto')!r}, camera "
            why += f"{'off' if not self.camera_on else self.cam_status.state}, full screen {self._fullscreen})"
            log.info("notch %s", why)
        if show and not self.notch.isVisible():
            self.notch.place()
            self.notch.show()
            self.pill.set_status("", hidden=True)
            self._update_pill()
        elif not show and self.notch.isVisible():
            self.notch.hide()
            self._update_pill()

    # ------------------------------------------------------------ screen assist
    def _assist_showing(self) -> bool:
        return self._assist_busy or self.notch.answer is not None or time.monotonic() < self._assist_until

    def _assist_message(self, text: str, kind: str, accent: str, seconds: float) -> None:
        self._assist_until = time.monotonic() + seconds
        self._update_notch()
        self._flash_msg(text, kind, accent, seconds)

    def start_assist(self) -> None:
        """Screen assist (hotkey, rotary item, notch menu): grab the screen, ask the AI, answer on the notch."""
        if self._assist_busy:
            return
        missing = assist.ready(self.cfg)
        if missing:
            self._assist_message(missing, "error", AMBER, 6.0)
            self.show_window("assist")
            return
        self._assist_busy = True
        self.notch.clear_answer()
        if self.engine.phase == Phase.OPEN:
            self._close_manual("assist")
        QTimer.singleShot(150, self._assist_capture)

    def _assist_capture(self, tries: int = 0) -> None:
        if self.dial.isVisible() and tries < 20:          # wait for the rotary to get out of the picture
            QTimer.singleShot(120, lambda: self._assist_capture(tries + 1))
            return
        try:
            shot = assist.capture()
        except assist.AssistError as e:
            self._assist_busy = False
            self._assist_message(str(e), "error", RED, 5.0)
            return
        self._update_notch()
        self._flash_msg("Looking at your screen…", "pulse", BLUE, assist.TIMEOUT + 5)
        cfg = self.cfg

        def work():
            try:
                self.assist_done.emit(assist.solve(shot, cfg), "")
            except assist.AssistError as e:
                self.assist_done.emit(None, str(e))
            except Exception:
                log.exception("screen assist failed")
                self.assist_done.emit(None, "Screen assist failed (details in the log)")
        threading.Thread(target=work, daemon=True, name="assist").start()

    def _on_assist_done(self, ans, err: str) -> None:
        self._assist_busy = False
        self._flash = None
        if err:
            self._assist_message(err[:110], "error", RED, 6.0)
            return
        if not ans.found:
            self._assist_message("No question or problem on screen", "dot", GRAY, 3.5)
            return
        seconds = float(assist.settings(self.cfg).get("seconds", 20))
        self._assist_until = time.monotonic() + 1.0
        self._update_notch()
        self.sounds.play("confirm")
        self._say(ans.spoken())
        if self.notch.isVisible():
            self.notch.show_answer(ans.choice, ans.answer, ans.detail, seconds)
            self._update_pill()
        else:                                            # the notch is switched off: the status pill says it
            self._flash_msg(ans.headline(), "done", GREEN, seconds)

    # ------------------------------------------------------------ quick nav levels
    def _enter_quicknav(self, item) -> None:
        app_id = str(item.action.get("app", ""))
        a = integrations.get(app_id)
        children = [i for i in (item_from(d) for d in integrations.quicknav(app_id)) if i is not None]
        integrations.refresh_dynamic(app_id, self.cfg, self.dynamic_ready.emit)
        if a is None or not a.installed or not children:
            self._flash_msg(f"{item.name} isn't installed", "error", RED, 3.0)
            self._handle(self.engine.force_close(time.monotonic(), "missing"))
            return
        self.levels.append((self.level_items, self.engine.selected, self.crumb))
        self._qn_app = app_id
        self.crumb = item.name
        self.level_items = [back_item("")] + children
        self.engine.enter_level(len(self.level_items), time.monotonic(), selected=1)
        self.dial.set_level(self.level_items, item.name, self.engine.snapshot())
        self.sounds.play("open")
        self._say(f"{item.name}. {self.level_items[1].name}")

    def _go_back(self) -> None:
        if not self.levels:
            return
        items, sel, crumb = self.levels.pop()
        self.level_items, self.crumb = items, crumb
        self._qn_app = ""
        self.engine.enter_level(len(items), time.monotonic(), selected=sel)
        self.dial.set_level(items, crumb, self.engine.snapshot())
        self.sounds.play("tick")
        self._say(f"Back. {items[sel % len(items)].name}")

    def _reset_levels(self) -> None:
        if self.levels:
            root_sel = self.levels[0][1]
            self.levels.clear()
            self.level_items = self.items
            self.engine.set_item_count(len(self.items))
            self.engine.sel_raw = root_sel % max(1, len(self.items))
            self.engine.position = float(self.engine.sel_raw)
        self.crumb = ""
        self._qn_app = ""

    def _on_dynamic(self, app_id: str) -> None:
        """Games / scenes arrived while their Quick nav ring is open and untouched: show them."""
        if not (self.levels and app_id == self._qn_app and self.engine.phase == Phase.OPEN):
            return
        if self.engine.snapshot().interacted:
            return
        children = [i for i in (item_from(d) for d in integrations.quicknav(app_id)) if i is not None]
        new = [self.level_items[0]] + children
        if [i.name for i in new] == [i.name for i in self.level_items]:
            return
        self.level_items = new
        self.engine.enter_level(len(new), time.monotonic(), selected=min(1, len(new) - 1))
        self.dial.set_level(new, self.crumb, self.engine.snapshot())

    # ------------------------------------------------------------ tracking
    def on_result(self, res: TrackResult) -> None:
        self._last_result_t = time.monotonic()
        flip = self.settings.flip_handedness
        feats = [extract_features(h, flip) for h in res.hands]
        idx, same = pick_hand(feats, res.faces, self._prev_center)
        f = None
        if idx >= 0:
            if not same:
                self.hands.reset()          # a different hand: forget its left/right vote
            h = res.hands[idx]
            label, conf = self.hands.update(h.handedness, h.score, feats[idx].grip, res.t)
            f = extract_features(h, flip, handedness=label, handed_conf=conf)
            f.at_face = hand_at_face(f.bbox, res.faces)
            feats[idx] = f
            self._prev_center = f.center
            self._last_hand_t = time.monotonic()
            if self._calib is not None:
                self._calib.append(f.raw_facing)
        else:
            self._prev_center = None
        self._handle(self.engine.update(f, res.t))
        snap = self.engine.snapshot()
        if f is not None and log.isEnabledFor(logging.DEBUG) and res.t - self._last_dbg > 0.5:
            self._last_dbg = res.t
            log.debug("hand %s(%.2f) facing=%+.2f grip=%.2f curls=%s pinch=%.2f roll=%+.0f fs=%.2f face=%s "
                      "frame=%s presented=%s point=%s phase=%s arming=%.2f pos=%.2f",
                      f.handedness, f.handed_conf, f.facing, f.grip, "/".join(f"{c:.1f}" for c in f.curls), f.pinch,
                      math.degrees(f.angle), f.index_fs, f.at_face, f.in_frame, snap.presented, snap.pointing,
                      snap.phase.value, snap.arming, snap.position)
        if self.dial.isVisible():
            self.dial.set_state(snap)
        want = self.window.wants_frames()
        self.tracker.want_preview = want
        if want:
            self.window.camera.set_frame(res.preview, res.hands, feats, idx, snap, res.faces)
        self._update_pill(snap)

    def _on_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_result_t > 0.25:
            self._handle(self.engine.update(None, now))
            snap = self.engine.snapshot()
            if self.dial.isVisible():
                self.dial.set_state(snap)
            self._update_pill(snap)
        if self._calib is not None and now >= self._calib_until:
            self._finish_calibration()
        self.tracker.want_preview = self.window.wants_frames()
        # A mouse / keyboard session ends when you click into another window.
        if self.keyboard_session and self.engine.phase == Phase.OPEN and sys.platform == "win32":
            fg = winapi.user32.GetForegroundWindow()
            if fg and fg != self._kb_fg and fg != int(self.window.winId()):
                self._close_manual("focus")
        if now - self._fs_checked > 1.0:
            self._fs_checked = now
            self._fs_state = fullscreen_state()
            fs = self._fs_state in (2, 3, 4)
            if fs != self._fullscreen:
                self._fullscreen = fs
                log.info("full-screen app %s", "started" if fs else "ended")
            self._update_notch()

    def on_status(self, st: CameraStatus) -> None:
        changed = (st.state != self.cam_status.state
                   or [c.key for c in st.cameras] != [c.key for c in self.cam_status.cameras]
                   or (st.camera and self.cam_status.camera and st.camera.key != self.cam_status.camera.key))
        if not self.camera_on:
            return                       # a last message from a camera that's being switched off
        self.cam_status = st
        if st.state == "running":
            self._no_cam_since = None
        elif st.state in ("none", "error") and self._no_cam_since is None:
            self._no_cam_since = time.monotonic()
        if changed:
            self._fill_camera_menu()
            if st.state == "running" and st.camera:
                cam_cfg = self.cfg.setdefault("camera", {})
                if cam_cfg.get("preferred") != st.camera.name:
                    cam_cfg["preferred"] = st.camera.name
                    self._save_timer.start()
        self._sync_camera_ui(changed)
        self._update_notch()
        self._update_pill()

    def _sync_camera_ui(self, cameras_changed: bool = True) -> None:
        st = self.cam_status
        cam = self.window.page("camera")
        if cam is not None and cameras_changed:
            cam.set_cameras(st.cameras, st.camera.key if st.camera else None)
        if st.state == "running" and st.camera:
            if cam is not None:
                cam.stats.setText(f"{st.camera.width}×{st.camera.height} · {st.camera.backend_name}\n"
                                  f"capture {st.capture_fps:.0f} fps · tracking {st.infer_fps:.0f} fps")
            self.window.set_status(f"● {st.camera.name}")
        else:
            if cam is not None:
                cam.stats.setText(st.message or st.state)
                cam.view.message = st.message or "Waiting for camera…"
                cam.view.update()
                if not self.camera_on:
                    cam.refresh()
            self.window.set_status(st.message or "")

    def window_built(self) -> None:
        """The settings window just made its pages: bring them up to date."""
        self._sync_camera_ui(True)

    # ------------------------------------------------------------ events
    def _handle(self, events: list) -> None:
        for name, payload in events:
            log.debug("event %s %s", name, payload)
            if name == "open":
                self._reset_levels()
                self.dial.set_items(self.level_items)
                self.dial.painter_.crumb = ""
                self.dial.painter_.keyboard = self.keyboard_session
                self.dial.open(self.engine.snapshot(), interactive=self.keyboard_session)
                self.sounds.play("open")
                self._say("Rotary. " + self.level_items[self.engine.selected % len(self.level_items)].name)
            elif name == "select":
                self.sounds.play("tick")
                self._speak_timer.start()
            elif name == "execute":
                item = self.level_items[payload % len(self.level_items)]
                if item.kind == "quicknav":
                    self._enter_quicknav(item)
                    continue
                if item.kind == "back":
                    self._go_back()
                    continue
                self.dial.set_state(self.engine.snapshot())
                self.dial.play_execute()
                self.sounds.play("confirm")
                self._say(item.name)
                if item.kind == "assist":
                    self.start_assist()
                else:
                    self._run_action(item)
                self._end_keyboard()
            elif name in ("close", "closed"):
                if name == "close":
                    self.dial.close_dial()
                self._reset_levels()
                self._end_keyboard()

    def _run_action(self, item) -> None:
        cfg = self.cfg

        def work():
            try:
                execute(item.action, cfg)
                self.action_done.emit(item.name, True, "")
            except Exception as e:
                log.exception("action %s failed", item.name)
                self.action_done.emit(item.name, False, str(e))
        QTimer.singleShot(140, lambda: threading.Thread(target=work, daemon=True).start())

    def _on_action_done(self, name: str, ok: bool, err: str) -> None:
        if ok:
            self._flash_msg(name, "done", GREEN)
        else:
            self._flash_msg(f"Couldn't run {name}: {err}"[:96], "error", RED, 4.5)
            self._say(f"Couldn't run {name}")

    def _say(self, text: str) -> None:
        self.speaker.say(text)

    def _speak_current(self) -> None:
        if self.engine.phase == Phase.OPEN and self.level_items:
            self._say(self.level_items[self.engine.selected % len(self.level_items)].name)

    # ------------------------------------------------------------ calibration
    def start_calibration(self) -> None:
        self._calib = []
        self._calib_until = time.monotonic() + 2.5
        self._update_pill()

    def _finish_calibration(self) -> None:
        samples, self._calib = self._calib or [], None
        good = [s for s in samples if abs(s) > 0.12]
        if len(good) < 10:
            self._flash_msg("Calibration failed — no palm seen", "error", RED, 3.0)
            return
        flip = float(np.median(good)) < 0
        self.cfg.setdefault("gestures", {})["flip_handedness"] = flip
        self.apply_config()
        if self.window.built:
            self.window.gestures.refresh()
        self._flash_msg("Palm calibrated", "done", GREEN)
        log.info("calibrated flip_handedness=%s from %d samples", flip, len(good))

    # ------------------------------------------------------------ pill
    def _flash_msg(self, text: str, kind: str, accent: str, seconds: float = 1.8) -> None:
        self._flash = (text, kind, accent, time.monotonic() + seconds)
        self._update_pill()

    def _update_pill(self, snap=None) -> None:
        if not self.pill_enabled:
            return
        if self.notch.isVisible() and self.pill.isVisible():
            self.pill.set_status("", hidden=True)
        snap = snap or self.engine.snapshot()
        now = time.monotonic()
        st = self.cam_status
        if st.state not in ("none", "error"):
            self._cam_lost_t = now
        if self._flash and now < self._flash[3]:
            text, kind, accent, _ = self._flash
            args = dict(text=text, kind=kind, accent=accent)
        elif self._calib is not None:
            prog = 1 - max(0.0, self._calib_until - now) / 2.5
            args = dict(text="Hold your palm toward the camera…", accent=BLUE, progress=prog)
        elif not self.camera_on:
            args = dict(text="", hidden=True)
        elif self.engine.paused:
            args = dict(text="Paused — camera off", accent=GRAY, collapsed=now - self._last_hand_t > 6)
        elif st.state == "searching":
            args = dict(text="", hidden=True)        # usually over in a second; nothing to say yet
        elif st.state in ("none", "error"):
            # No words, just a small warning sign (hover the notch, or open Camera, for the details).
            args = dict(text="", kind="warning", accent=AMBER, collapsed=True)
        elif snap.phase != Phase.IDLE:
            args = dict(text="", hidden=True)
        elif not snap.presented:
            # Quiet unless a hand is held up on purpose; gone entirely when nobody's around.
            if not snap.hand_present and now - self._last_hand_t > 4.0:
                args = dict(text="", hidden=True)
            else:
                args = dict(text="Ready", accent=GREEN if snap.hand_present and not snap.at_face else GRAY,
                            collapsed=True)
        elif snap.cooling:
            args = dict(text="", accent=GRAY, collapsed=True)
        elif snap.rearm_needed:
            args = dict(text="Move your hand to re-arm" + (" · or grab" if self.settings.grip_summon else ""),
                        accent=GRAY)
        elif snap.arming > 0.08:
            args = dict(text="Hold still to open", accent=BLUE, progress=snap.arming)
        else:
            ways = (["hold still"] if self.settings.still_summon else []) + \
                   (["close your hand"] if self.settings.grip_summon else [])
            text = " or ".join(ways) or "use the keyboard shortcut"
            args = dict(text=text[0].upper() + text[1:], accent=GREEN)
        if self.notch.isVisible():
            self.notch.set_status(**args)
            tip = (st.message or "No camera found") if args.get("kind") == "warning" else ""
            if self.notch.toolTip() != tip:
                self.notch.setToolTip(tip)
        else:
            self.pill.set_status(**args)

    # ------------------------------------------------------------ lifecycle
    def uninstall(self, delete_settings: bool) -> None:
        self.quitting = True
        system.uninstall(delete_settings)
        self.quit(save=not delete_settings)

    def _session_ending(self, *_):
        """Windows is signing out / shutting down: don't block it."""
        self.quitting = True
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_cfg()

    def _shutdown(self) -> None:
        if self.live.isRunning():
            self.live.stop()
            self.live.wait(2000)
        if self.tracker.isRunning():
            self.tracker.stop()
            self.tracker.wait(3000)

    def quit(self, save: bool = True) -> None:
        self.quitting = True
        if save and self._save_timer.isActive():
            self._save_timer.stop()
            self._save_cfg()
        self.hotkeys.unregister(HK_TOGGLE)
        self.hotkeys.unregister(HK_ASSIST)
        self._nav_keys(False)
        self._shutdown()
        self.tray.hide()
        self.window.close()
        self.app.quit()


# --------------------------------------------------------------------------- entry
def _single_instance(app: QApplication) -> QLocalServer | None:
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return None
    QLocalServer.removeServer(INSTANCE_KEY)
    server = QLocalServer(app)
    server.listen(INSTANCE_KEY)
    return server


def _run_python_file(path: str, err_file: str | None) -> int:
    """`--run-python file.py`: the packaged app doubling as a Python interpreter for code actions."""
    import runpy
    import traceback
    sys.argv = [path]
    try:
        runpy.run_path(path, run_name="__main__")
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except BaseException:
        if err_file:
            Path(err_file).write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def main(argv: list[str] | None = None) -> int:
    import argparse
    args_in = sys.argv[1:] if argv is None else argv
    # A windowed .exe has no console: give print() and friends somewhere harmless to go.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    ap = argparse.ArgumentParser(prog="gesture-rotary", add_help=False)
    ap.add_argument("--show", "--preview", dest="show", action="store_true")
    ap.add_argument("--minimized", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--run-python", dest="run_python")
    ap.add_argument("--error-file", dest="error_file")
    args, _unknown = ap.parse_known_args(args_in)
    if args.run_python:
        return _run_python_file(args.run_python, args.error_file)

    logdir = DATA_DIR / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    from logging.handlers import RotatingFileHandler
    handlers: list[logging.Handler] = [RotatingFileHandler(logdir / "rotary.log", maxBytes=1_000_000, backupCount=2,
                                                           encoding="utf-8")]
    if getattr(sys.stderr, "name", "") != os.devnull:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("matplotlib", "PIL", "absl", "websocket"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.excepthook = lambda t, v, tb: log.error("unhandled error", exc_info=(t, v, tb))
    threading.excepthook = lambda a: log.error("unhandled error in %s", a.thread.name if a.thread else "thread",
                                               exc_info=(a.exc_type, a.exc_value, a.exc_traceback))

    if sys.platform == "win32":
        try:  # own taskbar identity (icon + grouping) instead of python.exe's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(["gesture-rotary"])
    app.setApplicationName("Gesture Rotary")
    app.setApplicationDisplayName("Gesture Rotary")
    app.setQuitOnLastWindowClosed(False)
    server = _single_instance(app)
    if server is None:
        log.info("already running — brought the existing window forward")
        return 0
    show = True if args.show else (False if args.minimized else None)
    rotary = RotaryApp(app, show_window=show)

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(lambda: rotary.show_window())
    server.newConnection.connect(on_conn)
    return app.exec()

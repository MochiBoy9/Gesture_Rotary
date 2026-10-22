"""Gesture Rotary — a rotary launcher you turn with your hand, the mouse or the keyboard."""
import os
import sys
import time
from pathlib import Path

T0 = time.perf_counter()          # for the "ready in … ms" line in the log
__version__ = "1.3.0"

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # Packaged .exe: bundled resources next to the exe, user data in %APPDATA%.
    ROOT = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "GestureRotary"
else:
    ROOT = Path(__file__).resolve().parent.parent
    DATA_DIR = ROOT
DATA_DIR.mkdir(parents=True, exist_ok=True)

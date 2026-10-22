"""Entry point for the packaged app (PyInstaller) and `python gesture_rotary.py`."""
import sys

from rotary.app import main

if __name__ == "__main__":
    sys.exit(main())

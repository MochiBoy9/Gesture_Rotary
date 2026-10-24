"""Copy a PyInstaller build to %USERPROFILE%\\Apps\\Gesture Rotary and put a shortcut on the Desktop.

(The exe adds its own Start menu entry the first time it runs.)"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

src = Path(sys.argv[1])
dest = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(os.environ["USERPROFILE"]) / "Apps" / "Gesture Rotary"
exe = dest / "Gesture Rotary.exe"

import time

# Replace a running copy: stop it, then wait until Windows has really let go of its files.
subprocess.run(["taskkill", "/IM", "Gesture Rotary.exe", "/F"], capture_output=True)
for _ in range(50):
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Gesture Rotary.exe", "/NH"], capture_output=True,
                         text=True).stdout
    if "Gesture Rotary.exe" not in out:
        break
    time.sleep(0.2)
for attempt in range(10):
    try:
        if dest.exists():
            shutil.rmtree(dest)
        break
    except PermissionError:
        if attempt == 9:
            raise
        time.sleep(0.5)
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(src, dest)

desktop = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                         capture_output=True, text=True).stdout.strip() or str(Path.home() / "Desktop")
lnk = Path(desktop) / "RotaryUI.lnk"
ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{exe}';"
      f"$s.WorkingDirectory='{dest}';$s.IconLocation='{exe},0';$s.Description='RotaryUI';$s.Save()")
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
print(f"installed: {exe}")
print(f"shortcut:  {lnk}")

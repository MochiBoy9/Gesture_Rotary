"""Install-level housekeeping: start with Windows, Start menu / Desktop shortcuts, uninstall.

All of it targets the packaged .exe; running from source only manages the Run key."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import DATA_DIR, FROZEN, ROOT

log = logging.getLogger(__name__)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GestureRotary"
LNK_NAME = "Gesture Rotary.lnk"


def launcher_command() -> str:
    if FROZEN:
        return f'"{sys.executable}" --minimized'
    return f'wscript.exe "{ROOT / "dev" / "Gesture Rotary.vbs"}"'


def _run_value() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return str(winreg.QueryValueEx(k, RUN_NAME)[0])
    except OSError:
        return None


def run_at_login() -> bool:
    return _run_value() is not None


def set_run_at_login(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, launcher_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


def start_menu_lnk() -> Path:
    return Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs" / LNK_NAME


def desktop_lnk() -> Path:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                             capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW).stdout.strip()
    except Exception:
        out = ""
    return Path(out or Path.home() / "Desktop") / LNK_NAME


def make_shortcut(lnk: Path, exe: str) -> None:
    q = lambda s: str(s).replace("'", "''")  # noqa: E731
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');$s.TargetPath='{q(exe)}';"
          f"$s.WorkingDirectory='{q(Path(exe).parent)}';$s.IconLocation='{q(exe)},0';"
          f"$s.Description='Gesture Rotary';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=15, creationflags=_NO_WINDOW,
                   capture_output=True)


def refresh_install(cfg: dict) -> bool:
    """Packaged app: add the Start menu entry on first run, and repair it (and the
    start-with-Windows entry) if the app folder was moved. Returns True if cfg changed."""
    if not FROZEN:
        return False
    exe = sys.executable
    gen = cfg.setdefault("general", {})
    moved = gen.get("exe_path") not in (None, exe)
    try:
        lnk = start_menu_lnk()
        if moved or not lnk.exists():
            make_shortcut(lnk, exe)
            log.info("Start menu shortcut %s", "updated" if moved else "added")
        if moved:
            d = desktop_lnk()
            if d.exists():
                make_shortcut(d, exe)
        if run_at_login() and _run_value() != launcher_command():
            set_run_at_login(True)
    except Exception:
        log.warning("couldn't refresh shortcuts", exc_info=True)
    if gen.get("exe_path") != exe:
        gen["exe_path"] = exe
        return True
    return False


def install_folder() -> Path | None:
    """The packaged app's own folder, only if it unmistakably is one (safety for uninstall)."""
    if not FROZEN:
        return None
    folder = Path(sys.executable).parent
    if (folder / "Gesture Rotary.exe").is_file() and (folder / "_internal").is_dir() \
            and folder.name.lower() == "gesture rotary":
        return folder
    return None


def uninstall(delete_settings: bool) -> None:
    """Remove shortcuts, the start-with-Windows entry and (after we exit) the app folder."""
    try:
        set_run_at_login(False)
    except OSError:
        pass
    for lnk in (start_menu_lnk(), desktop_lnk()):
        try:
            if lnk.exists():
                lnk.unlink()
        except OSError:
            pass
    if delete_settings and FROZEN and DATA_DIR.name == "GestureRotary":
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    folder = install_folder()
    if folder is not None:
        # Wait for this process to exit, then remove the folder.
        cmd = f'ping 127.0.0.1 -n 4 >nul & rmdir /s /q "{folder}"'
        subprocess.Popen(["cmd.exe", "/c", cmd], cwd=str(folder.parent),
                         creationflags=_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))

"""Install-level housekeeping: start at login, Start menu / Desktop shortcuts (the Linux apps menu), uninstall.

Most of it targets the packaged app; running from source only manages starting at login.
  Windows  start with Windows through the Run key; the Start menu entry is added on first run
  macOS    a LaunchAgent opens the app at login; the app is the .app bundle (usually in /Applications)
  Linux    an autostart .desktop file; the apps-menu entry is added on first run"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import DATA_DIR, FROZEN, LINUX, MAC, ROOT, WIN

log = logging.getLogger(__name__)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GestureRotary"
LNK_NAME = "Gesture Rotary.lnk"
LINUX_ID = "gesture-rotary"


def launcher_command() -> str:
    if FROZEN:
        return f'"{sys.executable}" --minimized'
    return f'wscript.exe "{ROOT / "dev" / "Gesture Rotary.vbs"}"'


def login_command() -> list[str]:
    """macOS / Linux: what starts the app minimised at login."""
    if FROZEN:
        return [sys.executable, "--minimized"]
    return [sys.executable, "-m", "rotary", "--minimized"]


def _run_value() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return str(winreg.QueryValueEx(k, RUN_NAME)[0])
    except OSError:
        return None


def run_at_login() -> bool:
    if not WIN:
        from . import posix
        return posix.login_item_command() is not None
    return _run_value() is not None


def set_run_at_login(on: bool) -> None:
    if not WIN:
        from . import posix
        posix.set_login_item(login_command() if on else None, "" if FROZEN else str(ROOT))
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, launcher_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


def _login_item_stale() -> bool:
    if WIN:
        return _run_value() != launcher_command()
    from . import posix
    return posix.login_item_command() != login_command()


# --------------------------------------------------------------------------- Windows shortcuts
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


# --------------------------------------------------------------------------- Linux apps menu
def _xdg_data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def linux_menu_entry() -> Path:
    return _xdg_data() / "applications" / f"{LINUX_ID}.desktop"


def linux_icon() -> Path:
    return _xdg_data() / "icons" / "hicolor" / "256x256" / "apps" / f"{LINUX_ID}.png"


def make_linux_menu_entry(exe: str) -> None:
    from . import posix
    icon = ""
    src = ROOT / "assets" / "icon.png"
    if src.exists():
        linux_icon().parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, linux_icon())
        icon = LINUX_ID
    posix.write_desktop_file(linux_menu_entry(), [exe], icon=icon)


# --------------------------------------------------------------------------- install
def refresh_install(cfg: dict) -> bool:
    """Packaged app: add the Start menu (Linux: apps menu) entry on first run, and repair it (and the
    start-at-login entry) if the app was moved. Returns True if cfg changed."""
    if not FROZEN:
        return False
    exe = sys.executable
    gen = cfg.setdefault("general", {})
    moved = gen.get("exe_path") not in (None, exe)
    try:
        if WIN:
            lnk = start_menu_lnk()
            if moved or not lnk.exists():
                make_shortcut(lnk, exe)
                log.info("Start menu shortcut %s", "updated" if moved else "added")
            if moved:
                d = desktop_lnk()
                if d.exists():
                    make_shortcut(d, exe)
        elif LINUX and (moved or not linux_menu_entry().exists()):
            make_linux_menu_entry(exe)
            log.info("apps menu entry %s", "updated" if moved else "added")
        if run_at_login() and _login_item_stale():
            set_run_at_login(True)
    except Exception:
        log.warning("couldn't refresh shortcuts", exc_info=True)
    if gen.get("exe_path") != exe:
        gen["exe_path"] = exe
        return True
    return False


def install_folder() -> Path | None:
    """The packaged app's own folder (macOS: its .app bundle), only if it unmistakably is one
    (safety for uninstall)."""
    if not FROZEN:
        return None
    exe = Path(sys.executable)
    if MAC:
        bundle = exe.parents[2] if len(exe.parents) > 2 else exe.parent
        if bundle.suffix == ".app" and bundle.name.startswith("Gesture Rotary") \
                and (bundle / "Contents" / "Info.plist").is_file():
            return bundle
        return None
    folder = exe.parent
    if WIN:
        if (folder / "Gesture Rotary.exe").is_file() and (folder / "_internal").is_dir() \
                and folder.name.lower() == "gesture rotary":
            return folder
        return None
    if (folder / LINUX_ID).is_file() and (folder / "_internal").is_dir() and folder.name == LINUX_ID:
        return folder
    return None


def uninstall(delete_settings: bool) -> None:
    """Remove shortcuts, the start-at-login entry and (after we exit) the app itself."""
    try:
        set_run_at_login(False)
    except OSError:
        pass
    if WIN:
        links = [start_menu_lnk(), desktop_lnk()]
    elif LINUX:
        links = [linux_menu_entry(), linux_icon()]
        launcher = Path.home() / ".local" / "bin" / LINUX_ID
        if launcher.is_symlink():
            links.append(launcher)
    else:
        links = []
    for lnk in links:
        try:
            if lnk.exists() or lnk.is_symlink():
                lnk.unlink()
        except OSError:
            pass
    if delete_settings and FROZEN and DATA_DIR.name == "GestureRotary":
        shutil.rmtree(DATA_DIR, ignore_errors=True)
    folder = install_folder()
    if folder is None:
        return
    if WIN:
        uninstaller = folder / "unins000.exe"          # installed by the setup program: let it clean up
        if uninstaller.is_file():
            cmd = f'ping 127.0.0.1 -n 4 >nul & "{uninstaller}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
        else:
            cmd = f'ping 127.0.0.1 -n 4 >nul & rmdir /s /q "{folder}"'
        # Wait for this process to exit, then remove the folder.
        subprocess.Popen(["cmd.exe", "/c", cmd], cwd=str(folder.parent),
                         creationflags=_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        subprocess.Popen(["/bin/sh", "-c", 'sleep 3; rm -rf "$0"', str(folder)], cwd=str(folder.parent),
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)

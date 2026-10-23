"""Automatic updates: when GitHub has a newer release, download it, check it and swap it in.

  1. check    ask GitHub for the latest release (pre-releases and drafts never count) and compare its version
              with __version__
  2. download fetch this system's file from that release and check it against the release's SHA256SUMS.txt
  3. prepare  unpack it next to the installed app (Windows Setup.exe needs nothing unpacked)
  4. apply    hand over to a small script that waits for this process to exit, puts the new version in place
              of the old (putting the old one back if that fails), and starts the app again

Only the packaged app updates itself, and only from a folder that unmistakably is its own install
(system.install_folder()). Running from source, it just says that a newer version is out.
  Windows  the Setup.exe when the app was installed with it (it upgrades in place, silently), otherwise the
           portable .zip
  macOS    the .dmg's Gesture Rotary.app replaces the installed one
  Linux    the .tar.gz's gesture-rotary folder replaces the installed one"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import DATA_DIR, FROZEN, MAC, WIN, __version__, system

log = logging.getLogger(__name__)
REPO = "MochiBoy9/Gesture_Rotary"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
SUMS = "SHA256SUMS.txt"
CHECK_HOURS = 6
WORK = DATA_DIR / "updates"            # downloads and unpacking; emptied before each update
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Updates come only from GitHub, over https (release downloads redirect to its file servers, which have
# changed name over the years: objects., release-assets., github-releases.githubusercontent.com).
TRUSTED_HOSTS = ("github.com", "api.github.com")
TRUSTED_DOMAIN = ".githubusercontent.com"
MAX_DOWNLOAD = 1_500_000_000          # bytes: far more than any release file


class UpdateError(Exception):
    """Something the person can read: why this update didn't happen."""


@dataclass
class Release:
    version: str                                        # "1.6.0" (the tag without its v)
    page: str                                           # the release's GitHub page
    assets: dict[str, str] = field(default_factory=dict)    # file name → download address


@dataclass
class Staged:
    """A downloaded update, ready to apply once the app quits."""
    version: str
    kind: str          # setup (Windows Setup.exe) | swap (replace the install folder with new)
    path: Path         # the Setup.exe, or the new app folder / .app bundle
    folder: Path       # the installed app folder / .app bundle


# --------------------------------------------------------------------------- versions
def parse_version(v: str) -> tuple:
    """"v1.10.2" → (1, 10, 2, 1); a pre-release ("1.6.0-beta.1") sorts before its release (… 0)."""
    v = str(v).strip().lstrip("vV")
    main, _, pre = v.partition("-")
    nums = [int(n) for n in re.findall(r"\d+", main)[:3]]
    nums += [0] * (3 - len(nums))
    return (*nums, 0 if pre else 1)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


# --------------------------------------------------------------------------- GitHub
def trusted(url: str) -> bool:
    u = urllib.parse.urlsplit(str(url))
    host = (u.hostname or "").lower()
    return u.scheme == "https" and (host in TRUSTED_HOSTS or host.endswith(TRUSTED_DOMAIN))


def _get(url: str, timeout: float, accept: str = "application/octet-stream"):
    from .assist import _ssl_context
    if not trusted(url):
        raise UpdateError(f"Refused to download from {urllib.parse.urlsplit(str(url)).hostname or url}")
    req = urllib.request.Request(url, headers={"User-Agent": f"GestureRotary/{__version__}", "Accept": accept})
    r = urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
    if not trusted(r.geturl()):                      # where a redirect ended up
        r.close()
        raise UpdateError(f"Refused to download from {urllib.parse.urlsplit(r.geturl()).hostname}")
    return r


def parse_release(data: dict) -> Release:
    tag = str(data.get("tag_name") or "")
    if not tag or data.get("draft") or data.get("prerelease"):
        raise UpdateError("GitHub has no finished release yet")
    assets = {str(a.get("name")): str(a.get("browser_download_url"))
              for a in data.get("assets") or []
              if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")}
    return Release(tag.lstrip("vV"), str(data.get("html_url") or RELEASES_PAGE), assets)


def fetch_latest(timeout: float = 15) -> Release:
    try:
        with _get(LATEST_URL, timeout, "application/vnd.github+json") as r:
            data = json.loads(r.read(5_000_000).decode("utf-8"))
        if not isinstance(data, dict):
            raise UpdateError("GitHub sent a release it couldn't read")
        return parse_release(data)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Couldn't reach GitHub to check for updates ({getattr(e, 'reason', e)})") from None


def parse_sums(text: str) -> dict[str, str]:
    """SHA256SUMS.txt (sha256sum's format) → file name → checksum."""
    out = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            out[parts[1].lstrip("*").strip()] = parts[0].lower()
    return out


# --------------------------------------------------------------------------- this install
def _arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)


def setup_installed(folder: Path) -> bool:
    """Windows: installed with the Setup.exe (which left its uninstaller), not unzipped from the portable .zip."""
    return (folder / "unins000.exe").is_file()


def asset_name(version: str, folder: Path | None = None, win: bool = WIN, mac: bool = MAC) -> str:
    """The release file that updates this copy (the names tools/build.py gives them)."""
    if win:
        kind = "Setup.exe" if folder is not None and setup_installed(folder) else "Portable.zip"
        return f"GestureRotary-{version}-Windows-{kind}"
    if mac:
        return f"GestureRotary-{version}-macOS.dmg"
    return f"GestureRotary-{version}-Linux-{_arch()}.tar.gz"


def unsupported() -> str:
    """Why this copy can't update itself ('' = it can)."""
    if not FROZEN:
        return "Running from source: update it with git pull"
    folder = system.install_folder()
    if folder is None:
        return "This copy isn't in a folder it can update"
    if not os.access(folder.parent, os.W_OK):
        return f"No permission to change {folder.parent}"
    return ""


# --------------------------------------------------------------------------- download + unpack
def download(release: Release, folder: Path | None, progress=None) -> Path:
    """Fetch this system's file from the release into WORK and check its SHA-256. Blocking."""
    name = asset_name(release.version, folder)
    if name not in release.assets:
        raise UpdateError(f"Version {release.version} has no download for this {system_name()}")
    if SUMS not in release.assets:
        raise UpdateError(f"Version {release.version} has no checksums, so it can't be checked")
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        with _get(release.assets[SUMS], 30) as r:
            want = parse_sums(r.read(1_000_000).decode("utf-8", "replace")).get(name)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"Couldn't download the update ({getattr(e, 'reason', e)})") from None
    if not want:
        raise UpdateError(f"{SUMS} doesn't list {name}")
    dest = WORK / name
    h = hashlib.sha256()
    try:
        with _get(release.assets[name], 60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            if total > MAX_DOWNLOAD:
                raise UpdateError("The update is far bigger than it should be, so it wasn't downloaded")
            done = 0
            while chunk := r.read(1 << 16):
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done > MAX_DOWNLOAD:
                    raise UpdateError("The update is far bigger than it should be, so it was thrown away")
                if progress and total:
                    progress(min(1.0, done / total))
    except UpdateError:
        dest.unlink(missing_ok=True)
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise UpdateError(f"Couldn't download the update ({getattr(e, 'reason', e)})") from None
    if h.hexdigest() != want:
        dest.unlink(missing_ok=True)
        raise UpdateError("The downloaded update didn't match its checksum, so it was thrown away")
    log.info("downloaded %s (%.0f MB, checksum ok)", name, dest.stat().st_size / 1e6)
    return dest


def system_name() -> str:
    return "PC" if WIN else "Mac" if MAC else "computer"


def staging_path(folder: Path) -> Path:
    """Where the new version is unpacked: next to the install, so the swap is a rename on the same disk."""
    return folder.parent / f".{folder.name}.update"


def _find(root: Path, name: str) -> Path:
    for p in [root, *sorted(root.iterdir())]:
        if p.name == name and p.is_dir():
            return p
        if p.is_dir() and (p / name).is_dir():
            return p / name
    raise UpdateError(f"The update doesn't contain {name}")


def prepare(file: Path, version: str, folder: Path) -> Staged:
    """Unpack the downloaded file next to the installed app. Blocking."""
    if file.suffix == ".exe":
        return Staged(version, "setup", file, folder)
    new = staging_path(folder)
    shutil.rmtree(new, ignore_errors=True)
    unpacked = WORK / "unpacked"
    shutil.rmtree(unpacked, ignore_errors=True)
    unpacked.mkdir(parents=True)
    try:
        if file.name.endswith(".zip"):
            with zipfile.ZipFile(file) as zf:
                zf.extractall(unpacked)
            src = _find(unpacked, folder.name)
        elif file.name.endswith(".tar.gz"):
            with tarfile.open(file, "r:gz") as tf:
                tf.extractall(unpacked, filter="data")
            src = _find(unpacked, folder.name)
        elif file.suffix == ".dmg":
            mount = WORK / "mount"
            mount.mkdir()
            subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint",
                            str(mount), str(file)], check=True, capture_output=True, timeout=120)
            try:
                app = mount / "Gesture Rotary.app"
                if not app.is_dir():
                    raise UpdateError("The update doesn't contain Gesture Rotary.app")
                # ditto keeps the bundle's symlinks and signature
                subprocess.run(["ditto", str(app), str(new)], check=True, capture_output=True, timeout=300)
            finally:
                subprocess.run(["hdiutil", "detach", "-force", str(mount)], capture_output=True, timeout=60)
            return Staged(version, "swap", new, folder)
        else:
            raise UpdateError(f"Don't know how to install {file.name}")
        shutil.move(str(src), str(new))
    except UpdateError:
        shutil.rmtree(new, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(new, ignore_errors=True)
        log.warning("couldn't unpack %s", file, exc_info=True)
        raise UpdateError(f"Couldn't unpack the update ({e})") from None
    finally:
        shutil.rmtree(unpacked, ignore_errors=True)
    return Staged(version, "swap", new, folder)


def cleanup() -> None:
    """At startup: the last update's download and anything a failed one left behind."""
    shutil.rmtree(WORK, ignore_errors=True)
    folder = system.install_folder()
    if folder is not None:
        for p in (staging_path(folder), folder.parent / f".{folder.name}.old"):
            shutil.rmtree(p, ignore_errors=True)


# --------------------------------------------------------------------------- apply
# macOS / Linux: $1 = this process, $2 = the install, $3 = the new version; the rest starts the app again.
SWAP_SH = r"""
pid=$1 folder=$2 new=$3
shift 3
old="$(dirname "$folder")/.$(basename "$folder").old"
i=0
while kill -0 "$pid" 2>/dev/null && [ $i -lt 120 ]; do sleep 0.5; i=$((i+1)); done
rm -rf "$old"
if mv "$folder" "$old"; then
    if mv "$new" "$folder"; then rm -rf "$old"; else mv "$old" "$folder"; fi
fi
rm -rf "$new"
"$@" >/dev/null 2>&1 &
"""


def _cmd_path(p: Path) -> str:
    """A path for a .cmd file: a % in it would otherwise be read as a variable."""
    return str(p).replace("%", "%%")


def windows_script(staged: Staged, pid: int, exe: Path, args: list[str]) -> str:
    q = _cmd_path
    folder, old = q(staged.folder), q(staged.folder.parent / f".{staged.folder.name}.old")
    path, exe = q(staged.path), q(exe)
    lines = ["@echo off",
             "chcp 65001 >nul",              # the script is UTF-8: a user folder with accents stays right
             f'powershell -NoProfile -Command "Wait-Process -Id {pid} -Timeout 60 -ErrorAction SilentlyContinue"']
    if staged.kind == "setup":
        # Inno Setup upgrades the same folder (same AppId) and keeps the tasks chosen the first time.
        lines.append(f'"{path}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL')
    else:
        lines += [f'if exist "{old}" rmdir /s /q "{old}"',
                  f'move "{folder}" "{old}" >nul || goto start',
                  f'move "{path}" "{folder}" >nul || (move "{old}" "{folder}" >nul & goto start)',
                  f'rmdir /s /q "{old}"']
    lines.append(":start")
    if staged.kind != "setup":
        lines.append(f'if exist "{path}" rmdir /s /q "{path}"')     # a swap that didn't happen
    lines.append(f'start "" "{exe}" {" ".join(args)}')
    return "\r\n".join(lines) + "\r\n"


def apply(staged: Staged, args: list[str]) -> None:
    """Start the script that installs the update once this process has exited. The caller quits right after."""
    pid = os.getpid()
    WORK.mkdir(parents=True, exist_ok=True)
    if WIN:
        script = WORK / "apply-update.cmd"
        script.write_text(windows_script(staged, pid, Path(sys.executable), args), encoding="utf-8")
        subprocess.Popen(["cmd.exe", "/c", str(script)], cwd=str(staged.folder.parent),
                         creationflags=_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))
    else:
        relaunch = ["open", "-n", str(staged.folder), "--args", *args] if MAC else \
            [str(staged.folder / system.LINUX_ID), *args]
        subprocess.Popen(["/bin/sh", "-c", SWAP_SH, "update", str(pid), str(staged.folder), str(staged.path),
                          *relaunch], cwd=str(staged.folder.parent), start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("installing %s after quitting", staged.version)


def check_and_prepare(progress=None) -> tuple[Release | None, Staged | None]:
    """The whole background part: (the latest release if it's newer, the update ready to apply).
    Raises UpdateError when something went wrong along the way. Blocking."""
    release = fetch_latest()
    if not is_newer(release.version):
        log.info("up to date (%s; latest is %s)", __version__, release.version)
        return None, None
    why = unsupported()
    if why:
        log.info("version %s is out, but this copy can't update itself: %s", release.version, why)
        return release, None
    folder = system.install_folder()
    assert folder is not None
    log.info("version %s is out: downloading it", release.version)
    file = download(release, folder, progress)
    return release, prepare(file, release.version, folder)

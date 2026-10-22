"""Build Gesture Rotary and package it for release, on the system you run it on:

    uv run python tools/build.py              # → release/
    uv run python tools/build.py --skip-package

  Windows  GestureRotary-<version>-Windows-Setup.exe   (Inno Setup; needs ISCC.exe — winget install JRSoftware.InnoSetup)
           GestureRotary-<version>-Windows-Portable.zip
  macOS    GestureRotary-<version>-macOS.dmg            (drag to Applications)
  Linux    GestureRotary-<version>-Linux-x86_64.tar.gz  (unpack, run ./install.sh)

PyInstaller's work folders live under %LOCALAPPDATA%\\GestureRotary on Windows (MediaPipe's deep paths break
Windows' 260-character limit elsewhere) and in build/ + dist/ on macOS and Linux."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rotary import __version__  # noqa: E402

WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
RELEASE = ROOT / "release"
if WIN:
    BASE = Path(os.environ["LOCALAPPDATA"]) / "GestureRotary"
    DIST, WORK = BASE / "dist", BASE / "build"
else:
    DIST, WORK = ROOT / "dist", ROOT / "build"


def run(cmd: list, **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}.get(m, m)


def pyinstaller() -> Path:
    run([sys.executable, "tools/make_icon.py"], cwd=ROOT)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", DIST, "--workpath", WORK,
         "Gesture Rotary.spec"], cwd=ROOT)
    out = DIST / ("Gesture Rotary.app" if MAC else "Gesture Rotary" if WIN else "gesture-rotary")
    if not out.exists():
        raise SystemExit(f"PyInstaller didn't produce {out}")
    if not MAC:
        # The bundle has them inside _internal/ (for the app's About card); these are the ones people see.
        shutil.copy(ROOT / "LICENSE", out / "LICENSE.txt")
        shutil.copy(ROOT / "THIRD_PARTY_NOTICES.txt", out / "THIRD_PARTY_NOTICES.txt")
    return out


# --------------------------------------------------------------------------- Windows
def find_iscc() -> str | None:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for sub in ("Inno Setup 6", r"Programs\Inno Setup 6"):
            p = Path(base or "") / sub / "ISCC.exe"
            if base and p.exists():
                return str(p)
    return None


def package_windows(app: Path) -> list[Path]:
    out = []
    iscc = find_iscc()
    if iscc:
        run([iscc, f"/DAppVersion={__version__}", f"/DBuildDir={app}", f"/O{RELEASE}",
             f"/FGestureRotary-{__version__}-Windows-Setup", ROOT / "installer" / "windows" / "GestureRotary.iss"])
        out.append(RELEASE / f"GestureRotary-{__version__}-Windows-Setup.exe")
    else:
        print("! Inno Setup not found — skipping the Setup.exe (winget install JRSoftware.InnoSetup)")
    z = RELEASE / f"GestureRotary-{__version__}-Windows-Portable.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(app.rglob("*")):
            if f.is_file():
                zf.write(f, Path("Gesture Rotary") / f.relative_to(app))
    out.append(z)
    return out


# --------------------------------------------------------------------------- macOS
def package_mac(app: Path) -> list[Path]:
    identity = os.environ.get("MACOS_SIGN_IDENTITY")
    if identity:
        run(["codesign", "--force", "--deep", "--options", "runtime", "--timestamp",
             "--entitlements", ROOT / "installer" / "macos" / "entitlements.plist", "--sign", identity, app])
    else:
        # Apple Silicon refuses to run unsigned code: sign ad hoc (users then open it once with right-click → Open).
        run(["codesign", "--force", "--deep", "--sign", "-", app])
    run(["codesign", "--verify", "--deep", "--strict", app])

    stage = WORK / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    run(["ditto", app, stage / app.name])                    # ditto keeps the bundle's symlinks and signatures
    (stage / "Applications").symlink_to("/Applications")
    shutil.copy(ROOT / "installer" / "macos" / "README.txt", stage / "Read me first.txt")
    shutil.copy(ROOT / "LICENSE", stage / "License.txt")
    dmg = RELEASE / f"GestureRotary-{__version__}-macOS.dmg"
    dmg.unlink(missing_ok=True)
    for attempt in range(3):              # hdiutil sometimes reports "Resource busy" on build machines
        try:
            run(["hdiutil", "create", "-volname", f"Gesture Rotary {__version__}", "-srcfolder", stage, "-ov",
                 "-format", "UDZO", "-fs", "HFS+", dmg])
            break
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            time.sleep(5)
    if identity:
        run(["codesign", "--sign", identity, "--timestamp", dmg])
        if os.environ.get("APPLE_ID") and os.environ.get("APPLE_TEAM_ID") and os.environ.get("APPLE_APP_PASSWORD"):
            run(["xcrun", "notarytool", "submit", dmg, "--apple-id", os.environ["APPLE_ID"],
                 "--team-id", os.environ["APPLE_TEAM_ID"], "--password", os.environ["APPLE_APP_PASSWORD"], "--wait"])
            run(["xcrun", "stapler", "staple", dmg])
    return [dmg]


# --------------------------------------------------------------------------- Linux
def package_linux(app: Path) -> list[Path]:
    name = f"GestureRotary-{__version__}-Linux-{arch()}"
    tgz = RELEASE / f"{name}.tar.gz"

    def add(tf: tarfile.TarFile, src: Path, arc: str, mode: int | None = None) -> None:
        info = tf.gettarinfo(str(src), arc)
        if mode is not None:
            info.mode = mode
        if info.isfile():
            with open(src, "rb") as f:
                tf.addfile(info, f)
        else:
            tf.addfile(info)

    with tarfile.open(tgz, "w:gz") as tf:
        add(tf, ROOT / "installer" / "linux" / "install.sh", f"{name}/install.sh", 0o755)
        add(tf, ROOT / "installer" / "linux" / "README.txt", f"{name}/README.txt")
        add(tf, ROOT / "LICENSE", f"{name}/LICENSE.txt")
        add(tf, ROOT / "assets" / "icon.png", f"{name}/gesture-rotary.png")
        for f in sorted(app.rglob("*")):
            add(tf, f, f"{name}/gesture-rotary/{f.relative_to(app)}")
    return [tgz]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-package", action="store_true", help="only run PyInstaller")
    args = ap.parse_args()
    app = pyinstaller()
    if args.skip_package:
        print(f"built {app}")
        return
    RELEASE.mkdir(exist_ok=True)
    files = package_windows(app) if WIN else package_mac(app) if MAC else package_linux(app)
    print("\nRelease files:")
    for f in files:
        print(f"  {f}  ({f.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

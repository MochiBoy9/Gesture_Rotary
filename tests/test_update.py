"""Automatic updates: versions, picking the right download, checksums, unpacking and the swap."""
import hashlib
import io
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from rotary import __version__, update

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="macOS / Linux behaviour")


def test_versions_compare_numerically():
    assert update.is_newer("1.10.0", "1.9.9")
    assert update.is_newer("v1.5.2", "1.5.1")
    assert not update.is_newer("1.5.1", "1.5.1")
    assert not update.is_newer("1.5.0", "1.5.1")
    assert update.is_newer("1.6.0", "1.6.0-beta.1")         # a release beats its pre-release
    assert not update.is_newer("1.6.0-beta.1", "1.6.0")
    assert update.parse_version("2") == (2, 0, 0, 1)


def test_release_from_github():
    rel = update.parse_release({"tag_name": "v9.0.0", "html_url": "https://example/r", "assets": [
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://example/sums"},
        {"name": "GestureRotary-9.0.0-macOS.dmg", "browser_download_url": "https://example/dmg"}]})
    assert rel.version == "9.0.0" and rel.assets["SHA256SUMS.txt"] == "https://example/sums"
    with pytest.raises(update.UpdateError):
        update.parse_release({"tag_name": "v9.0.0-rc.1", "prerelease": True})
    with pytest.raises(update.UpdateError):
        update.parse_release({"tag_name": "v9.0.0", "draft": True})


def test_asset_names_match_the_release_build(tmp_path):
    # tools/build.py names the files GestureRotary-<version>-<system>…
    assert update.asset_name("2.0.0", None, win=True, mac=False) == "GestureRotary-2.0.0-Windows-Portable.zip"
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert update.asset_name("2.0.0", tmp_path, win=True, mac=False) == "GestureRotary-2.0.0-Windows-Setup.exe"
    assert update.asset_name("2.0.0", tmp_path, win=False, mac=True) == "GestureRotary-2.0.0-macOS.dmg"
    assert update.asset_name("2.0.0", tmp_path, win=False, mac=False).startswith("GestureRotary-2.0.0-Linux-")
    build = (Path(update.__file__).parent.parent / "tools" / "build.py").read_text(encoding="utf-8")
    for part in ("-Windows-Setup", "-Windows-Portable.zip", "-macOS.dmg", "-Linux-{arch()}"):
        assert part in build


def test_checksums_file():
    h = "a" * 64
    sums = update.parse_sums(f"{h}  GestureRotary-1-macOS.dmg\n{'b' * 64} *other.zip\nnot a line\n")
    assert sums == {"GestureRotary-1-macOS.dmg": h, "other.zip": "b" * 64}


def test_source_checkout_doesnt_update_itself():
    assert "source" in update.unsupported()


class _Resp(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _fake_release(monkeypatch, tmp_path, payload: bytes, listed: bytes):
    name = update.asset_name("9.0.0", None)
    files = {"https://x/sums": f"{hashlib.sha256(listed).hexdigest()}  {name}\n".encode(), "https://x/app": payload}
    monkeypatch.setattr(update, "_get", lambda url, timeout, accept="": _Resp(files[url]))
    monkeypatch.setattr(update, "WORK", tmp_path / "updates")
    return update.Release("9.0.0", "", {name: "https://x/app", update.SUMS: "https://x/sums"}), name


def test_download_checks_the_checksum(monkeypatch, tmp_path):
    rel, name = _fake_release(monkeypatch, tmp_path, b"the new app", b"the new app")
    seen = []
    path = update.download(rel, None, seen.append)
    assert path.read_bytes() == b"the new app" and path.name == name and seen[-1] == 1.0

    rel, _ = _fake_release(monkeypatch, tmp_path, b"tampered", b"the new app")
    with pytest.raises(update.UpdateError, match="checksum"):
        update.download(rel, None)
    assert not (tmp_path / "updates" / name).exists()


def test_download_needs_this_systems_file_and_checksums(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "WORK", tmp_path / "updates")
    with pytest.raises(update.UpdateError, match="no download"):
        update.download(update.Release("9.0.0", "", {update.SUMS: "x"}), None)
    with pytest.raises(update.UpdateError, match="checksums"):
        update.download(update.Release("9.0.0", "", {update.asset_name("9.0.0", None): "x"}), None)


def _install(tmp_path: Path, name: str) -> Path:
    folder = tmp_path / "apps" / name
    (folder / "_internal").mkdir(parents=True)
    (folder / "version.txt").write_text("old")
    return folder


def test_prepare_unpacks_the_zip_next_to_the_install(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "WORK", tmp_path / "updates")
    folder = _install(tmp_path, "Gesture Rotary")
    z = tmp_path / "updates" / "GestureRotary-9.0.0-Windows-Portable.zip"
    z.parent.mkdir()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("Gesture Rotary/version.txt", "new")
        zf.writestr("Gesture Rotary/_internal/lib.dll", "x")
    staged = update.prepare(z, "9.0.0", folder)
    assert staged.kind == "swap" and staged.path == folder.parent / ".Gesture Rotary.update"
    assert (staged.path / "version.txt").read_text() == "new" and (staged.path / "_internal" / "lib.dll").exists()


def test_prepare_unpacks_the_tarball(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "WORK", tmp_path / "updates")
    folder = _install(tmp_path, "gesture-rotary")
    t = tmp_path / "updates" / "GestureRotary-9.0.0-Linux-x86_64.tar.gz"
    t.parent.mkdir()
    with tarfile.open(t, "w:gz") as tf:
        for arc, data in (("GestureRotary-9.0.0-Linux-x86_64/install.sh", b"#!/bin/sh"),
                          ("GestureRotary-9.0.0-Linux-x86_64/gesture-rotary/version.txt", b"new")):
            info = tarfile.TarInfo(arc)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    staged = update.prepare(t, "9.0.0", folder)
    assert (staged.path / "version.txt").read_text() == "new"
    assert not (tmp_path / "updates" / "unpacked").exists()


def test_setup_exe_needs_no_unpacking(tmp_path):
    staged = update.prepare(tmp_path / "GestureRotary-9.0.0-Windows-Setup.exe", "9.0.0", tmp_path)
    assert staged.kind == "setup"
    script = update.windows_script(staged, 1234, tmp_path / "Gesture Rotary.exe", ["--minimized"])
    assert "Wait-Process -Id 1234" in script and "/VERYSILENT" in script
    assert f'start "" "{tmp_path / "Gesture Rotary.exe"}" --minimized' in script


def test_windows_swap_script_puts_the_old_version_back_on_failure(tmp_path):
    folder = tmp_path / "Gesture Rotary"
    staged = update.Staged("9.0.0", "swap", update.staging_path(folder), folder)
    script = update.windows_script(staged, 1, folder / "Gesture Rotary.exe", ["--show"])
    assert f'move "{staged.path}" "{folder}" >nul || (move "{tmp_path / ".Gesture Rotary.old"}" "{folder}"' in script


def _run_swap(folder: Path, new: Path, marker: Path) -> None:
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    subprocess.run(["/bin/sh", "-c", update.SWAP_SH, "update", str(dead.pid), str(folder), str(new),
                    "touch", str(marker)], check=True, timeout=30)
    for _ in range(50):
        if marker.exists():
            return
        time.sleep(0.1)


@posix_only
def test_swap_script_installs_the_new_version_and_restarts(tmp_path):
    folder = _install(tmp_path, "gesture-rotary")
    new = update.staging_path(folder)
    new.mkdir()
    (new / "version.txt").write_text("new")
    _run_swap(folder, new, tmp_path / "started")
    assert (folder / "version.txt").read_text() == "new"
    assert not new.exists() and not (folder.parent / ".gesture-rotary.old").exists()
    assert (tmp_path / "started").exists()


@posix_only
def test_swap_script_keeps_the_old_version_when_the_new_one_is_missing(tmp_path):
    folder = _install(tmp_path, "gesture-rotary")
    _run_swap(folder, tmp_path / "nothing-here", tmp_path / "started")
    assert (folder / "version.txt").read_text() == "old"
    assert (tmp_path / "started").exists()


def test_current_version_parses():
    assert update.parse_version(__version__) >= (1, 5, 1, 1)

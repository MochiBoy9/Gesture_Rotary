
---

## Download

| System | File | How to install |
| --- | --- | --- |
| **Windows 10 / 11** (64-bit) | `RotaryUI-…-Windows-Setup.exe` | Run it. No administrator rights needed. If SmartScreen appears: *More info → Run anyway*. |
| Windows, no install | `RotaryUI-…-Windows-Portable.zip` | Unzip anywhere and run `Gesture Rotary.exe`. |
| **macOS 14+** (Apple silicon: M1 or later) | `RotaryUI-…-macOS.dmg` | Open it and drag **RotaryUI** to **Applications**. The first time, right-click the app → **Open** (or *System Settings → Privacy & Security → Open Anyway*). |
| **Linux** (x86-64, glibc 2.34+: Ubuntu 22.04+, Fedora 35+…) | `RotaryUI-…-Linux-x86_64.tar.gz` | `tar xzf RotaryUI-*.tar.gz && cd RotaryUI-*/ && ./install.sh` |

Open the rotary with **Ctrl + Alt + Space** (Mac: **⌃⌥Space**), by clicking the notch at the top of the screen,
or by raising your hand to the camera.

On a Mac, allow **Camera** when asked. The first time an item presses a keyboard shortcut, also allow
RotaryUI under **System Settings → Privacy & Security → Accessibility**.

On Linux, if hand tracking doesn't start: `sudo apt install libgles2 libegl1` (Fedora: `libglvnd-gles libglvnd-egl`).

The `GestureRotary-…` files are the same builds under the app's old name, so copies from before 2.0 can update
themselves. `SHA256SUMS.txt` lists every file's checksum.

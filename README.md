# Gesture Rotary

**Windows · macOS · Linux**

Raise your hand to any webcam and a liquid-glass rotary appears. Lean, slide or turn your hand to
choose, then launch apps, shortcuts, scripts, or the actions inside your apps (Steam games, OBS
recording, Discord mute, recent VS Code projects…). No camera? Click the notch at the top of the screen and
use the same rotary with your mouse and keyboard.

## Install

Download the file for your system from the [latest release](https://github.com/MochiBoy9/Gesture_Rotary/releases/latest).
Everything is bundled (Python, MediaPipe, the hand and face models), so there's nothing else to install.

| System | Download | Install |
| --- | --- | --- |
| **Windows 10 / 11** (64-bit) | `GestureRotary-…-Windows-Setup.exe` | Run it. No administrator rights needed. It adds Start menu (and optionally Desktop) shortcuts and can start with Windows. If SmartScreen appears: *More info → Run anyway*. A portable `.zip` is also available. |
| **macOS 14 Sonoma or later**, Apple silicon (M1 and later) | `GestureRotary-…-macOS.dmg` | Open it and drag **Gesture Rotary** to **Applications**. The first time, right-click the app → **Open** (on macOS 15+: try to open it, then *System Settings → Privacy & Security → Open Anyway*). |
| **Linux** x86-64 (Ubuntu 22.04+, Debian 12+, Fedora 35+…) | `GestureRotary-…-Linux-x86_64.tar.gz` | `tar xzf GestureRotary-*.tar.gz && cd GestureRotary-*/ && ./install.sh`. This needs no root; the app appears in your apps menu and as `gesture-rotary`. |

Settings live in `%APPDATA%\GestureRotary` (Windows), `~/Library/Application Support/GestureRotary` (macOS) or
`~/.config/GestureRotary` (Linux).

The window stays on the taskbar or Dock. Closing it minimises it, and there's also a tray (menu bar) icon.
Launching the app again brings the window forward. *General → Uninstall* removes it cleanly, as does
*Apps → Installed apps* on Windows and `./install.sh --uninstall` on Linux.

### On a Mac

- **Camera**: macOS asks the first time. Video never leaves your Mac.
- **Accessibility** (*System Settings → Privacy & Security → Accessibility*): needed for items that press
  keyboard shortcuts (Mission Control, media keys, Discord's mute…). macOS asks the first time one runs.
- **Screen Recording** is optional. It's only for *live glass*, which blurs what's behind the rotary.
- The keyboard shortcut is **⌃⌥Space** (Control + Option + Space) and needs no permission.
- App shortcuts use ⌘ where Windows uses Ctrl. A **macOS** Quick nav has Lock, Mission Control, Spotlight,
  Screenshot, Emoji, Launchpad, Activity Monitor and Sleep.
- Intel Macs aren't supported: MediaPipe, the hand tracker, has no Intel-Mac build.

### On Linux

- Hand tracking needs OpenGL ES: `sudo apt install libgles2 libegl1` (Fedora: `libglvnd-gles libglvnd-egl`).
  `install.sh` tells you if anything is missing.
- The keyboard shortcut and pressing keys work through X11. Under Wayland they only reach XWayland apps, so use
  the notch or the tray icon to open the rotary.
- Optional: `playerctl` for *now playing* on the notch, `speech-dispatcher` or `espeak-ng` for spoken item
  names, and `wmctrl` for items that press a shortcut inside another app.

## Using it (palm toward the camera)

| Do this | Result |
| --- | --- |
| Open palm, then **close it into a fist** | Opens instantly |
| **Hold your palm still** (3 s by default, as low as 0.5 s) | Opens |
| **Lean** your hand (Tilt), **slide** it (Move), or **turn** it (Follow), then hold | Keeps scrolling until you straighten or return to the middle |
| **Point** with your index finger, move it aside, hold | Scrolls; **push** toward the camera to click |
| Fist: choose, then **let go** · **pinch** · **hold still** on an item | Launches |
| Back of the hand, or lower it | Closes |
| **Ctrl + Alt + Space** (Mac: **⌃⌥Space**) | Opens from the keyboard: ← → move, Enter launches, Esc closes |

## Without a camera: the notch and the mouse

A small liquid-glass notch hangs from the top of the screen. By default it appears by itself when there's no
camera to use; the *Notch* page can show it always, never, or tuck it into a thin line until the mouse reaches
it. It hides during full-screen games and videos, shows status messages, and never appears in screenshots or
recordings. Choosing *Mouse & keyboard* there turns the camera off completely: hand tracking never loads, so
the app starts faster and uses less memory.

It's also a Dynamic Island for your desktop. Everything below can be switched on or off on the *Notch* page.
Rows marked *(Windows)* aren't available on macOS / Linux yet.

| Shows | How |
| --- | --- |
| The time | In the middle, with or without the day; 12- or 24-hour (follows the system unless you choose) |
| Now playing | YouTube and other sites in Chrome / Edge / Firefox, Spotify, Apple Music — anything Windows' media controls know (Linux: any MPRIS player, via `playerctl`; not on macOS). Album art and sound bars; hover for title, progress and ⏮ ⏯ ⏭ |
| Clips | A red REC dot while Medal records a game *(Windows)*; "Clip saved" / "Screenshot saved" from Medal, Xbox Game Bar, the NVIDIA app or OBS |
| Timers | Right-click → Timer. Counts down on the notch; hover for +1 min / Cancel; chimes when done |
| Mic & camera | An orange dot while an app uses the microphone, green for the camera (Gesture Rotary itself doesn't count) *(Windows)* |
| Battery | Plugged in, unplugged, and low-battery alerts on laptops |

Saved clips and finished timers can pop the notch up briefly over borderless full-screen games (never over
exclusive full-screen ones). *Look* switches between Dark (like a real notch) and Glass (more see-through).

| Do this | Result |
| --- | --- |
| Click the notch, or scroll on it, or press **Ctrl + Alt + Space** | Opens the rotary for the mouse and keyboard |
| Scroll, or drag around the ring | Turns it |
| Click an item | Brings it to the top; click it again (or the centre) to open it |
| Right-click · Esc | Goes back out of a Quick nav ring, or closes |
| ← → · Enter | Turn · open |
| Click into another window | Closes it |

A rotary opened by a gesture lets every click through to the windows underneath, as before.

**Quick nav**: an app item marked with a chevron opens a second ring of that app's own actions, with a Back
item. Only installed apps are offered.

| App | What's in its Quick nav |
| --- | --- |
| Steam | Your games, most recently played first, plus Library, Big Picture, Friends, Store, Downloads |
| OBS Studio | Record, pause, stream, save replay, virtual camera, mute mic, and every scene |
| Discord | Open, DMs, mute, deafen, quick switcher |
| VS Code / Cursor | Open, new window, and your recent projects |
| Claude | The Claude app, a new chat, and Claude Code in a terminal |
| Spotify / Apple Music / VLC | Play/pause, next, previous (Spotify: search) |
| Browsers | New window, private window, reopen the last tab |
| Zoom / Teams | Mute, camera |
| Roblox Studio | Play-test, stop |
| Windows | Lock, desktop, task view, snip, clipboard, emoji, quick settings, Task Manager… |
| macOS | Lock, Mission Control, Spotlight, screenshot, emoji, Launchpad, Activity Monitor, Sleep… |
| Linux | Lock, overview, screenshot, files, terminal, settings |
| Xbox Game Bar | Record that, record, screenshot, mic |

There are about 45 apps in total, including Epic, Battle.net, EA, Slack, Notion, Obsidian, Blender, Photoshop,
Figma, Unity Hub and Office. Any other installed app, including Store apps, can be added from
*Rotary → + → Any installed app*.

OBS works with no setup: if OBS is closed, choosing Record starts OBS already recording. To control OBS while it
is open, turn on *Tools → WebSocket Server Settings* in OBS and enter the password in *Apps → OBS Studio*. The
password is encrypted for your Windows account (on a Mac it goes in your Keychain).

## Accessibility

*Accessibility* offers quick setups:

- **Standard**
- **Palm only**: no fist or pinch; opens in 1 s and launches by holding still.
- **No wrist turning**: slide your hand sideways instead of tilting it.
- **Gentle**: slower and forgiving of tremor.

It also has:

- either side of the hand counts
- camera distance (near / normal / far)
- how steady you need to hold
- inactivity timeout (or never)
- text size, high contrast, reduce motion
- spoken item names
- sound volume
- a keyboard shortcut

Every control in the window works with Tab, arrow keys and screen readers.

## Accidental-open protection

The rotary ignores a hand that is:

- stretching or moving fast
- resting on your face or chin (face detection)
- tilted away or partly out of view
- a fist that never showed an open palm first
- not yet identified as left or right

After closing, it waits a moment before it can reopen. *Controls → Accidental-open protection* sets how strict
this is.

## Develop

Windows:

```
dev\setup.bat                           # one-time: Python + dependencies via uv
dev\run-debug.bat                       # run from source with logs and the window open
set UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\GestureRotary\venv
build_exe.bat                           # build and install the .exe for yourself (%USERPROFILE%\Apps\Gesture Rotary)
```

macOS / Linux:

```
dev/setup.sh                            # one-time: Python + dependencies via uv
dev/run-debug.sh                        # run from source with logs and the window open
```

Everywhere:

```
uv run pytest -q                        # gestures, glass, notch, live activities, Quick nav, OBS, macOS / Linux…
uv run python tools/render_dial.py out  # render rotary states to PNGs
uv run python tools/render_notch.py out # render the notch's states to one PNG
uv run python tools/shot_window.py out  # screenshots of the window's pages
uv run python tools/selftest.py out     # boot against the real camera, report fps
uv run python tools/build.py            # build the installer for this system into release/
```

`rotary/winapi.py` holds the Windows code and `rotary/posix.py` its macOS / Linux counterparts (Carbon
hotkeys, an X11 key grab, pynput for key presses, LaunchAgents and autostart files). Callers go through
`winapi`, which hands over to `posix` off Windows. Off Windows, icons come from `assets/rotary-icons.ttf`:
Fluent UI System Icons (MIT) placed on the Segoe Fluent Icons code points the app uses. Rebuild it with
`tools/make_icon_font.py` after using a new code point; a test checks that every one is covered.

### Releasing

1. Set the version in `rotary/__init__.py` and `pyproject.toml`, then `uv lock`, and add a section to `CHANGELOG.md`.
2. Commit to `main`, then either push a tag (`git tag v1.4.0 && git push origin v1.4.0`), or open
   *Actions → Release → Run workflow* on `main` and type the tag (e.g. `v1.4.0`).

The *Release* workflow tests and builds on Windows, macOS and Linux, then publishes a GitHub Release with
the Setup.exe, the portable .zip, the .dmg, the Linux .tar.gz and `SHA256SUMS.txt`. Its notes are the
changelog section plus `installer/RELEASE_NOTES.md`. *Run workflow* with the tag left empty builds the same
files without publishing them; download them from the run's artifacts.

The Mac app is signed ad hoc, so users right-click → Open the first time. To sign and notarise it instead, add these
repository secrets:
- `MACOS_SIGN_IDENTITY` (e.g. `Developer ID Application: Name (TEAMID)`)
- `MACOS_CERTIFICATE_P12` (base64) and `MACOS_CERTIFICATE_PASSWORD`
- `APPLE_ID`, `APPLE_TEAM_ID` and `APPLE_APP_PASSWORD`

The glass (`rotary/ui/liquid.py`) is computed with numpy from a grab of the screen behind each window: a light
frost, refraction at the bevelled edges, and highlights from a light at the upper left. The geometry is
cached, so reopening only costs the grab. OpenCV is the slim headless build, and MediaPipe's matplotlib and
sounddevice dependencies are overridden away in `pyproject.toml` (the tracker gives MediaPipe stand-ins).

On Windows, the virtual environment and build folders live under `%LOCALAPPDATA%\GestureRotary` because
MediaPipe's deep file paths break Windows' 260-character path limit in long folders.

## License

Gesture Rotary is released under the [MIT License](LICENSE). The release builds also bundle Qt / PySide6,
MediaPipe and its models, OpenCV, NumPy and other libraries, each under its own license (LGPL, Apache 2.0,
BSD, MIT and others). [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) lists them, with the full texts in
[licenses/](licenses); both ship inside every build.

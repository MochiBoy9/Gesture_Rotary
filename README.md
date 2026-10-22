# Gesture Rotary

Raise your hand to any webcam and a liquid-glass rotary appears. Lean, slide or turn your hand to
choose, then launch apps, shortcuts, scripts, or the actions inside your apps (Steam games, OBS
recording, Discord mute, recent VS Code projects…). No camera? Click the notch at the top of the screen and
use the same rotary with your mouse and keyboard.

## Install

Run **`build_exe.bat`**. It builds `Gesture Rotary.exe` (about 245 MB on disk) and installs it to
`%USERPROFILE%\Apps\Gesture Rotary\` with a Desktop shortcut. The app adds its own Start menu entry on first
launch. Everything is bundled (Python, MediaPipe, the hand and face models), and settings live in
`%APPDATA%\GestureRotary\config.json`.

The window stays on the taskbar. Closing it minimises it, and there's also a tray icon. Launching the
app again brings the window forward. *General → Uninstall* removes it cleanly.

## Using it (palm toward the camera)

| Do this | Result |
| --- | --- |
| Open palm, then **close it into a fist** | Opens instantly |
| **Hold your palm still** (3 s by default, as low as 0.5 s) | Opens |
| **Lean** your hand (Tilt), **slide** it (Move), or **turn** it (Follow), then hold | Keeps scrolling until you straighten or return to the middle |
| **Point** with your index finger, move it aside, hold | Scrolls; **push** toward the camera to click |
| Fist: choose, then **let go** · **pinch** · **hold still** on an item | Launches |
| Back of the hand, or lower it | Closes |
| **Ctrl + Alt + Space** | Opens from the keyboard: ← → move, Enter launches, Esc closes |

## Without a camera: the notch and the mouse

A small liquid-glass notch hangs from the top of the screen. By default it appears by itself when there's no
camera to use; the *Notch* page can show it always, never, or tuck it into a thin line until the mouse reaches
it. It hides during full-screen games and videos, shows status messages, and never appears in screenshots or
recordings. Choosing *Mouse & keyboard* there turns the camera off completely: hand tracking never loads, so
the app starts faster and uses less memory.

It's also a Dynamic Island for Windows. Everything below can be switched on or off on the *Notch* page.

| Shows | How |
| --- | --- |
| The time | In the middle, with or without the day; 12- or 24-hour (follows Windows unless you choose) |
| Now playing | YouTube and other sites in Chrome / Edge / Firefox, Spotify, Apple Music — anything Windows' media controls know. Album art and sound bars; hover for title, progress and ⏮ ⏯ ⏭ |
| Clips | A red REC dot while Medal records a game; "Clip saved" / "Screenshot saved" from Medal, Xbox Game Bar, the NVIDIA app or OBS |
| Timers | Right-click → Timer. Counts down on the notch; hover for +1 min / Cancel; chimes when done |
| Mic & camera | An orange dot while an app uses the microphone, green for the camera (Gesture Rotary itself doesn't count) |
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
| Xbox Game Bar | Record that, record, screenshot, mic |

There are about 45 apps in total, including Epic, Battle.net, EA, Slack, Notion, Obsidian, Blender, Photoshop,
Figma, Unity Hub and Office. Any other installed app, including Store apps, can be added from
*Rotary → + → Any installed app*.

OBS works with no setup: if OBS is closed, choosing Record starts OBS already recording. To control OBS while it
is open, turn on *Tools → WebSocket Server Settings* in OBS and enter the password in *Apps → OBS Studio*. The
password is encrypted for your Windows account.

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

```
dev\setup.bat                           # one-time: Python + dependencies via uv
dev\run-debug.bat                       # run from source with logs and the window open
set UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\GestureRotary\venv
uv run pytest -q                        # 114 tests: gestures, glass, notch, live activities, Quick nav, OBS…
uv run python tools/render_dial.py out  # render rotary states to PNGs
uv run python tools/render_notch.py out # render the notch's states to one PNG
uv run python tools/shot_window.py out  # screenshots of the window's pages
uv run python tools/selftest.py out     # boot against the real camera, report fps
```

The glass (`rotary/ui/liquid.py`) is computed with numpy from a grab of the screen behind each window: a light
frost, refraction at the bevelled edges, and highlights from a light at the upper left. The geometry is
cached, so reopening only costs the grab. OpenCV is the slim headless build, and MediaPipe's matplotlib and
sounddevice dependencies are overridden away in `pyproject.toml` (the tracker gives MediaPipe stand-ins).

The virtual environment and build folders live under `%LOCALAPPDATA%\GestureRotary` because MediaPipe's deep file
paths break Windows' 260-character path limit in long folders.

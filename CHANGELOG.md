# Changelog

## [Unreleased]

### New
- **Volume from the mouse and keyboard.** When the rotary opens from the notch, the keyboard shortcut or the
  mouse button, a liquid-glass volume button sits beside it, ringed by the current level. Click it (or press **+**
  or **−**) and the ring becomes the volume: it turns itself round to where the volume already is, with the level
  as a thin 0–360° line around it (a full turn is full, 4 % a click); scroll, drag or use the arrow keys, and
  click the button or the centre when done. It's what the two-finger slider does by hand,
  without a camera or a tracked hand.
- **The time, the date and the weather on the rotary**, in a liquid-glass capsule under the ring: *9:41 AM · Fri, Oct
  23 · ☁ 18°*. 12-hour by default; *General → Appearance → Clock on the rotary* switches to 24-hour or turns it
  off, and *Weather* turns the icon and temperature off. The weather comes from wttr.in (no account needed).

### Changed
- Hovering the notch no longer says "Rotary". Hover for a moment with no call, music, timer or clip on it and it
  says *Click to open wheel* (with your keyboard shortcut).
- Inside a Quick nav ring opened from the mouse, the app's name at the top is a *‹ Back* button.
- The two-finger slider's level beside the rotary is liquid glass now, like the ring.

## [1.8.0] — Your own AI model

### New
- **Claude in Screen assist.** Choose *Claude (Anthropic)* on the *Screen assist* page and paste an API key from
  the [Claude Platform](https://platform.claude.com/settings/keys). It uses Claude Opus 5.5 unless you pick
  another model.
- **Pick any model your account has.** *List my models* (or just saving a key) asks the service which models
  your key can use and offers the ones that can see images: Claude Opus, Sonnet and Haiku, OpenAI's GPT-6 Astra,
  Sol and Luna, Gemini's paid Pro models on a billed key, OpenRouter's models, or what you've pulled in Ollama.
  You can still type any model name.

### Changed
- *ChatGPT / OpenAI-compatible* now uses GPT-6 Astra by default (it was GPT-4o mini).
- When a paid service says you've hit your limit, the notch says so instead of mentioning a free limit.

## [1.7.0] — Volume, slides and videos

### New
- **Volume slider.** Hold up your index and middle finger (the others curled) and slide your hand up for louder,
  down for quieter, like a fader. It works whether the rotary is closed or open, in any ring, and the rotary holds
  still meanwhile. The level shows beside the rotary, or on the notch / status pill when it's closed. On Windows
  the volume changes silently, without the volume flyout appearing over a game.
- **Slides ring.** Open the rotary over PowerPoint, Google Slides (the site or its app), Keynote, LibreOffice
  Impress or another slideshow and it turns slides instead: no icons, just a cut between every two slides, a
  firm click per slide so a small wobble never changes slide, and a hard stop at the first and last slide.
  PowerPoint and Keynote say how many slides there are; elsewhere the ring simply steps forward and back.
  Slides change with Page Down / Page Up, like a presentation clicker.
- **Video ring.** Over YouTube, Netflix, Hulu, VLC or another video player, a full turn of the rotary is the
  whole video: turn it to find the moment you want. It turns by itself as the video plays and holds still
  while you turn it, and it stops at the start and the end. The time shows in the middle. Where the system's
  media controls can't move the video (or say how long it is), each click jumps the player's own seek step.
- Click the centre (or press Enter, pinch, or point) on a slides or video ring for your usual items.
- **A mouse button opens the rotary**, from any app, even a full-screen game or video: hold the middle button
  (the wheel), or pick a side button, under *Accessibility → Keyboard & mouse*. A quick middle click still
  works as usual.
- *Controls → Volume, slides and videos* switches the volume slider, the slides ring and the video ring on or off.

### Changed
- While the rotary is open from the mouse, the keyboard or the notch, the wheel turns it wherever the pointer is,
  and clicks and scrolls outside it stop at Gesture Rotary instead of reaching the app underneath (on Linux they
  still reach it). Clicking the rotary or the notch never takes the focus, so full-screen apps and videos stay
  full screen.

## [1.6.0] — Automatic updates and grip to turn

### New
- **Gesture Rotary updates itself.** It checks GitHub for a newer release a minute after it starts and every six
  hours after that. A new version downloads in the background, is checked against the release's checksums, and
  installs when the rotary isn't in use: the app restarts into it with your settings, and the notch says
  *Updated to Gesture Rotary …*.
  - Windows: the Setup.exe install upgrades silently in place; the portable folder is replaced.
  - macOS: the app in Applications is replaced. Linux: `install.sh`'s copy is replaced.
  - If anything goes wrong, the old version stays and starts again.
  - Versions before 1.6.0 can't update themselves: download 1.6.0 once and later versions arrive by themselves.
- *General → Updates*: turn *Update automatically* off, or *Check now* to update right away.
- A 360° gauge around the main rotary shows how far it has turned since it opened (not on Quick nav rings).

### Changed
- **Turn the rotary like a real knob.** Close your hand into a fist and tilt it: the ring follows with a firm
  click for every item and stays put between clicks, so it takes a deliberate turn to move on.
- **Re-grip like a ratchet.** Open your hand and close it again within 1.5 s and the ring doesn't move, so you can
  keep turning past what your wrist reaches in one go. Keep the hand open for 1.5 s to go back to palm mode.
- **Point to launch.** From the fist, stick out your index finger to open the selected item. Letting go no longer
  launches.
- The ring snaps to each item faster.

## [1.5.1] — MIT License

### New
- **Gesture Rotary is now open source under the MIT License.**
- *General → About* shows the license and the third-party software the app includes (Qt, MediaPipe, OpenCV,
  NumPy and more), with the full text of each license.
- Every download includes `LICENSE.txt`, next to the app on Windows and Linux and in the .dmg on macOS. The
  app also carries `THIRD_PARTY_NOTICES.txt` and the full license texts.

## [1.5.0] — Screen assist

### New
- **Screen assist**: press **Win + Alt + A** (Mac: **⌃⌥A**, Linux: **Super + Alt + A**), choose *Screen assist* on the rotary, or
  right-click the notch → *Solve what's on screen*. An AI looks at your screen, finds the question or problem
  on it and answers on the notch:
  - multiple choice: the option to pick (**A**, **B**, **C**…) in a badge, then its text
  - anything else (maths, puzzles, error messages, code, forms): a short answer
  - hover the answer for a sentence on why and a *Copy* button; click it to put it away
- **Free AI services**: Google Gemini (free API key from Google AI Studio, the default), Groq and OpenRouter
  (free tiers), or Ollama, which is free, private and runs on your own computer. ChatGPT and any
  OpenAI-compatible server (LM Studio…) work too. Set it up on the new *Screen assist* page: service, API key,
  model, keyboard shortcut and how long the answer stays.
- API keys are stored like the OBS password: encrypted for your Windows account, in the macOS Keychain, or in
  the Linux keyring. The screenshot goes only to the service you chose, and only when you ask.
- *Rotary → + → Screen assist* adds it to the rotary (or *Add to the rotary* on its page).
- When screen assist is in use, the notch appears even in *Auto* mode with a camera, and over borderless
  full-screen games. With the notch set to *Never*, the answer shows in the status pill instead.

## [1.4.0] — macOS and Linux

### New
- **Gesture Rotary now runs on Macs** (Apple silicon, macOS 14 Sonoma or later) **and on Linux** (x86-64), as
  well as Windows. Hand gestures, the notch, the mouse-and-keyboard rotary, Quick nav and the settings window
  all work the same way.
- **Installers for every system**:
  - Windows: `GestureRotary-<version>-Windows-Setup.exe`, with Start menu and optional Desktop shortcuts,
    an optional start-with-Windows checkbox, and an entry in *Apps → Installed apps* to uninstall it. No
    administrator rights needed. A portable `.zip` is there too.
  - macOS: `GestureRotary-<version>-macOS.dmg`. Drag the app to Applications.
  - Linux: `GestureRotary-<version>-Linux-x86_64.tar.gz`. Unpack it and run `./install.sh` (no root needed).
- On a Mac:
  - The keyboard shortcut is **⌃⌥Space** (Control + Option + Space) and needs no permission.
  - App shortcuts use ⌘ where Windows uses Ctrl (Discord's ⇧⌘M mute, Zoom's ⇧⌘A…).
  - A **macOS** Quick nav covers Lock, Mission Control, Spotlight, Screenshot, Emoji, Launchpad, Activity
    Monitor, Sleep and more.
  - *Any installed app* lists everything in your Applications folders.
  - Settings live in `~/Library/Application Support/GestureRotary`.
  - The OBS password is kept in your Keychain.
  - *Open at login* uses a LaunchAgent.
- On Linux:
  - The shortcut works through X11.
  - *Any installed app* lists your apps menu.
  - **Now playing** on the notch works through `playerctl` (any MPRIS player).
  - Spoken item names use speech-dispatcher or eSpeak.
  - The battery comes from `/sys/class/power_supply`.
  - Settings live in `~/.config/GestureRotary`.
- Battery alerts on the notch also work on Mac laptops.

### Changed
- The icons are drawn from a small bundled font (from Microsoft's MIT-licensed Fluent UI System Icons) where
  Windows' Segoe Fluent Icons isn't installed, so they look right on every system.
- Builds and releases: `tools/build.py` builds and packages for the system it runs on. Pushing a `v*` tag
  builds all three on GitHub Actions and publishes the release.

### Fixed
- `build_exe.bat` no longer fails on a fresh setup because Pillow (used to make the icons) was missing.

### Not available on macOS / Linux (yet)
- Windows-only extras: Xbox Game Bar, Windows' media controls on macOS, the microphone/camera-in-use dots,
  Medal clips, and hiding the rotary from screen capture.

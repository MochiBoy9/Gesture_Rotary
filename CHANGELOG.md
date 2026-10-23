# Changelog

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

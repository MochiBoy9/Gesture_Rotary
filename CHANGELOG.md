# Changelog

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

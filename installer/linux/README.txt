GESTURE ROTARY FOR LINUX
========================

Install (no root needed)
  ./install.sh
  Then start "Gesture Rotary" from your apps menu, or run:  gesture-rotary

  It goes to ~/.local/share/gesture-rotary, with a menu entry and ~/.local/bin/gesture-rotary.
  You can also run it straight from this folder:  ./gesture-rotary/gesture-rotary

Needs
  An x86-64 PC with glibc 2.34 or later (Ubuntu 22.04+, Debian 12+, Fedora 35+…) and an X11
  session — or Wayland with XWayland. A few system libraries hand tracking and the window use
  (install.sh checks for them):
    Debian / Ubuntu:  sudo apt install libgles2 libegl1 libxcb-cursor0 libxkbcommon-x11-0
    Fedora:           sudo dnf install libglvnd-gles libglvnd-egl xcb-util-cursor libxkbcommon-x11

Optional
  playerctl          "now playing" on the notch (Spotify, browsers, VLC…)
  speech-dispatcher  or espeak-ng: spoken item names (Accessibility)
  wmctrl             items that press a shortcut inside another app (Discord mute…)

Keyboard shortcut
  Ctrl + Alt + Space opens the rotary. On Wayland it only works while an X11/XWayland app has
  focus — click the notch at the top of the screen or the tray icon instead.

Settings live in ~/.config/GestureRotary.
Uninstall: General → Uninstall in the app, or  ./install.sh --uninstall

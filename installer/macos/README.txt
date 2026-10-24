ROTARYUI FOR MAC
======================

Install
  Drag "RotaryUI" onto the Applications folder in this window.

First launch
  This build isn't notarised by Apple, so the first time macOS says it can't check it:
    1. Open Applications, right-click (or Control-click) RotaryUI and choose Open.
    2. Click Open in the message that appears.
  On macOS 15 or later, if there's no Open button: try to open the app once, then go to
  System Settings → Privacy & Security, scroll down and click "Open Anyway".
  (Or, in Terminal:  xattr -dr com.apple.quarantine "/Applications/RotaryUI.app")

Permissions (System Settings → Privacy & Security)
  Camera         asked on first launch — for hand gestures. Video never leaves your Mac.
  Accessibility  asked the first time an item presses a keyboard shortcut (Mission Control,
                 Discord's mute, media keys…). Turn RotaryUI on, then try again.
  Screen Recording (optional)  only for "live glass", which blurs what's behind the rotary.

Keyboard shortcut
  Control + Option + Space opens the rotary (change it under General). No permission needed.

Requirements
  A Mac with Apple silicon (M1 or later) running macOS 14 Sonoma or later.

Settings live in ~/Library/Application Support/GestureRotary.
To uninstall: General → Uninstall in the app, or drag it from Applications to the Bin.

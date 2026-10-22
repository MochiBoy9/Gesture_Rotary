#!/bin/sh
# Installs Gesture Rotary for the current user (no root needed):
#   ~/.local/share/gesture-rotary/          the app
#   ~/.local/bin/gesture-rotary             a launcher on your PATH
#   ~/.local/share/applications/…desktop    the apps-menu entry
# ./install.sh --uninstall removes all of that (your settings in ~/.config/GestureRotary stay).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
DEST="$DATA/gesture-rotary"
BIN="$HOME/.local/bin"
MENU="$DATA/applications/gesture-rotary.desktop"
ICON="$DATA/icons/hicolor/256x256/apps/gesture-rotary.png"

if [ "${1:-}" = "--uninstall" ]; then
    pkill -x gesture-rotary 2>/dev/null || true
    rm -rf "$DEST"
    rm -f "$BIN/gesture-rotary" "$MENU" "$ICON" "${XDG_CONFIG_HOME:-$HOME/.config}/autostart/gesture-rotary.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" || true
    echo "Gesture Rotary removed. (Settings are still in ${XDG_CONFIG_HOME:-$HOME/.config}/GestureRotary.)"
    exit 0
fi

if [ ! -x "$HERE/gesture-rotary/gesture-rotary" ]; then
    echo "Run this from the unpacked GestureRotary folder (it should contain gesture-rotary/)." >&2
    exit 1
fi

# Libraries that come with most desktops but not every one.
missing=""
for lib in libGLESv2.so.2 libEGL.so.1 libxkbcommon-x11.so.0 libxcb-cursor.so.0; do
    if ! (ldconfig -p 2>/dev/null || true) | grep -q "$lib"; then
        missing="$missing $lib"
    fi
done
if [ -n "$missing" ]; then
    echo "Note: these system libraries weren't found:$missing"
    if command -v apt-get >/dev/null 2>&1; then
        echo "  sudo apt install libgles2 libegl1 libxkbcommon-x11-0 libxcb-cursor0"
    elif command -v dnf >/dev/null 2>&1; then
        echo "  sudo dnf install libglvnd-gles libglvnd-egl libxkbcommon-x11 xcb-util-cursor"
    elif command -v pacman >/dev/null 2>&1; then
        echo "  sudo pacman -S libglvnd libxkbcommon-x11 xcb-util-cursor"
    fi
    echo
fi

pkill -x gesture-rotary 2>/dev/null && sleep 1 || true
mkdir -p "$DATA" "$BIN" "$(dirname "$MENU")" "$(dirname "$ICON")"
rm -rf "$DEST.new"
cp -R "$HERE/gesture-rotary" "$DEST.new"
rm -rf "$DEST"
mv "$DEST.new" "$DEST"
cp "$HERE/gesture-rotary.png" "$ICON"
ln -sf "$DEST/gesture-rotary" "$BIN/gesture-rotary"

cat > "$MENU" <<EOF
[Desktop Entry]
Type=Application
Name=Gesture Rotary
Comment=A rotary launcher you turn with your hand, the mouse or the keyboard
Exec="$DEST/gesture-rotary"
Icon=gesture-rotary
Terminal=false
Categories=Utility;
StartupWMClass=gesture-rotary
EOF
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q "$DATA/icons/hicolor" 2>/dev/null || true

echo "Gesture Rotary is installed."
echo "Start it from your apps menu, or run: gesture-rotary"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "(Add $BIN to your PATH to run it by name.)" ;; esac
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && [ "${1:-}" != "--no-start" ]; then
    nohup "$DEST/gesture-rotary" >/dev/null 2>&1 &
fi

"""Build assets/rotary-icons.ttf: the app's icon glyphs for macOS and Linux, which have no Segoe Fluent Icons.

The glyphs come from Microsoft's Fluent UI System Icons (MIT licence, github.com/microsoft/fluentui-system-icons)
and are re-mapped onto the Segoe Fluent Icons code points the app already uses ("E774" = globe…), so items,
config files and the code stay the same on every system.

    uv run python tools/make_icon_font.py path/to/FluentSystemIcons-Regular.ttf path/to/FluentSystemIcons-Regular.json

The font and its JSON map are in the repository's fonts/ folder. Add a line to GLYPHS when the app starts
using a new code point (tests/test_icon_font.py checks they're all covered)."""
import json
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent.parent / "assets" / "rotary-icons.ttf"
FAMILY = "Rotary Icons"
SIZE = 20

# Segoe Fluent Icons code point → Fluent System Icons name (ic_fluent_<name>_20_regular)
GLYPHS = {
    0xE701: "wifi_1", 0xE702: "bluetooth", 0xE706: "weather_sunny", 0xE708: "weather_moon",
    0xE70D: "chevron_down", 0xE70E: "chevron_up", 0xE70F: "edit", 0xE710: "add", 0xE711: "dismiss",
    0xE713: "settings", 0xE714: "video", 0xE715: "mail", 0xE716: "people", 0xE717: "call", 0xE719: "shopping_bag",
    0xE71A: "stop", 0xE71B: "link", 0xE720: "mic", 0xE721: "search", 0xE722: "camera", 0xE72B: "arrow_left",
    0xE72C: "arrow_clockwise", 0xE72E: "lock_closed", 0xE734: "star", 0xE73E: "checkmark", 0xE74D: "delete",
    0xE74E: "save", 0xE74F: "speaker_mute", 0xE756: "window_console", 0xE767: "speaker_2", 0xE768: "play",
    0xE769: "pause", 0xE76C: "chevron_right", 0xE76E: "emoji", 0xE774: "globe", 0xE776: "accessibility",
    0xE77B: "person", 0xE77F: "clipboard_paste", 0xE787: "calendar_ltr", 0xE7A7: "arrow_undo", 0xE7BA: "warning",
    0xE7BF: "cart", 0xE7C3: "document", 0xE7C4: "window_multiple", 0xE7C8: "record", 0xE7E8: "power",
    0xE7F4: "desktop", 0xE7F8: "laptop", 0xE7FC: "games", 0xE80F: "home", 0xE815: "hand_right", 0xE81C: "history",
    0xE81D: "location", 0xE823: "clock", 0xE892: "previous", 0xE893: "next", 0xE896: "arrow_download",
    0xE897: "question_circle", 0xE8A5: "document", 0xE8A7: "open", 0xE8AB: "arrow_swap", 0xE8B7: "folder",
    0xE8B9: "image", 0xE8BD: "chat", 0xE8C8: "copy", 0xE8D6: "music_note_2", 0xE8EF: "calculator",
    0xE8F1: "library", 0xE8FB: "checkmark", 0xE909: "earth", 0xE90F: "wrench", 0xE916: "timer", 0xE93E: "live",
    0xE943: "code", 0xE945: "flash", 0xE946: "info", 0xE962: "glance_horizontal", 0xE993: "speaker_1",
    0xE995: "speaker_2", 0xE9D9: "pulse", 0xEB51: "heart", 0xEB68: "hand_wave", 0xEBB5: "battery_charge",
    0xF0E2: "apps",
}


def main(ttf: str, names_json: str) -> None:
    names = json.loads(Path(names_json).read_text(encoding="utf-8"))
    font = TTFont(ttf)
    cmap = font.getBestCmap()
    wanted: dict[int, str] = {}                         # Segoe code point → glyph name in the Fluent font
    for cp, name in GLYPHS.items():
        key = f"ic_fluent_{name}_{SIZE}_regular"
        if key not in names:
            raise SystemExit(f"{key} isn't in {names_json}")
        wanted[cp] = cmap[names[key]]

    opts = subset.Options()
    opts.glyph_names = True
    opts.layout_features = []
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(glyphs=sorted(set(wanted.values())))
    sub.subset(font)

    # Point the Segoe code points at the kept glyphs, and nothing else.
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap = dict(wanted)
    font["cmap"].tables = [t for t in font["cmap"].tables if t.isUnicode()]

    name = font["name"]
    for rec in list(name.names):
        if rec.nameID in (1, 3, 4, 6, 16, 17):
            name.removeNames(nameID=rec.nameID)
    for nid, value in ((1, FAMILY), (2, "Regular"), (3, f"{FAMILY} Regular"), (4, FAMILY),
                       (6, FAMILY.replace(" ", "") + "-Regular")):
        name.setName(value, nid, 3, 1, 0x409)
        name.setName(value, nid, 1, 0, 0)
    name.setName("Glyphs from Fluent UI System Icons, © Microsoft Corporation, MIT licence.", 0, 3, 1, 0x409)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    font.save(OUT)
    print(f"{OUT} — {len(wanted)} glyphs, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])

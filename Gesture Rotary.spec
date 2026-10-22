# PyInstaller spec — build with build_exe.bat
import json
import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

sys.path.insert(0, SPECPATH)
from rotary.actions import DEFAULT_CONFIG  # noqa: E402

# Ship clean defaults (the first run then offers Quick nav for the apps it finds).
default_cfg = os.path.join(workpath, "default_config.json")
os.makedirs(workpath, exist_ok=True)
with open(default_cfg, "w", encoding="utf-8") as f:
    json.dump(DEFAULT_CONFIG, f, indent=2)

datas = [("models/hand_landmarker.task", "models"), ("models/blaze_face_short_range.tflite", "models"),
         ("assets/icon.png", "assets"), (default_cfg, ".")]
binaries, hiddenimports = [], ["cv2_enumerate_cameras", "websocket", "sqlite3", "winsound", "nturl2path",
                               # Windows media controls (the notch's "now playing")
                               "winrt.runtime", "winrt.windows.media.control", "winrt.windows.foundation",
                               "winrt.windows.foundation.collections", "winrt.windows.storage.streams"]
# MediaPipe: its native library and data files; the Python side is found by following our imports.
# Its drawing helpers (matplotlib) and microphone recorder (sounddevice) are left out on purpose —
# rotary/tracker.py hands MediaPipe stand-ins for them.
datas += collect_data_files("mediapipe", excludes=["**/test*/**", "**/*_test.py"])
binaries += collect_dynamic_libs("mediapipe")
hiddenimports += ["mediapipe.tasks.python.vision.hand_landmarker", "mediapipe.tasks.python.vision.face_detector",
                  "mediapipe.tasks.python.core.base_options"]

# Standard library modules that "Run Python code" actions commonly use (the built-in interpreter
# only has what is bundled here; users with their own Python get theirs).
STDLIB_FOR_SCRIPTS = [
    "webbrowser", "json", "csv", "datetime", "time", "random", "math", "statistics", "re", "os", "shutil",
    "pathlib", "glob", "subprocess", "urllib.request", "urllib.parse", "http.client", "socket", "ssl",
    "hashlib", "base64", "uuid", "zipfile", "tarfile", "tempfile", "textwrap", "string", "itertools",
    "functools", "collections", "decimal", "fractions", "html", "html.parser", "xml.etree.ElementTree",
    "email", "smtplib", "winreg", "winsound", "ctypes", "ctypes.wintypes", "platform", "getpass", "pprint",
    "logging", "asyncio", "threading", "queue", "wave", "calendar", "locale", "difflib", "secrets",
]

a = Analysis(
    ["gesture_rotary.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + STDLIB_FOR_SCRIPTS + ["PySide6.QtNetwork"],
    excludes=["tkinter", "matplotlib", "PIL", "sounddevice", "_sounddevice", "contourpy", "kiwisolver",
              "fontTools", "pytest", "IPython", "jax", "jaxlib", "scipy", "pandas",
              "PySide6.QtMultimedia", "PySide6.QtTextToSpeech", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtQuickWidgets", "PySide6.QtPdf", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick3D",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtDesigner", "PySide6.QtHelp",
              "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus",
              "PySide6.QtUiTools", "PySide6.QtSvgWidgets", "PySide6.QtPrintSupport"],
    noarchive=False,
)

# Files that would only take up space: software OpenGL, video codecs, Qt's QML/PDF/multimedia stacks,
# translations, and plugins for things the app never does (TLS, network detection, PDF thumbnails…).
DROP = re.compile(r"""(?ix)
    opengl32sw\.dll | opencv_videoio_ffmpeg.*\.dll | (av(codec|format|util|filter|device)|sw(scale|resample))-\d+\.dll
  | Qt6(Quick|Qml|Pdf|Multimedia|TextToSpeech|OpenGL|VirtualKeyboard|ShaderTools|Svg Widgets)\w*\.dll
  | [\\/]translations[\\/] | [\\/]qml[\\/]
  | [\\/]plugins[\\/](tls|networkinformation|multimedia|texttospeech|qmltooling|scenegraph|position|sqldrivers)[\\/]
  | [\\/]plugins[\\/]imageformats[\\/]q(pdf|webp|tiff|icns|tga|wbmp)\.dll
  | [\\/]plugins[\\/]platforms[\\/]q(direct2d|minimal|offscreen)\.dll
  | mediapipe[\\/].*[\\/]test(s|data)?[\\/]
""")


def keep(entry):
    dest = entry[0]
    return not DROP.search("/" + dest.replace("\\", "/").replace("/", os.sep))


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Gesture Rotary", icon="assets/icon.ico",
          console=False, upx=False, version=None)
coll = COLLECT(exe, a.binaries, a.datas, name="Gesture Rotary", upx=False)

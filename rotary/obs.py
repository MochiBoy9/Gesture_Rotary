"""OBS Studio control over obs-websocket v5 (built into OBS 28+).

When OBS isn't running, record/stream/virtual-camera/replay/scene actions start OBS
with the matching command-line flag instead, so they work with no setup at all."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import socket
import uuid

from . import WIN, winapi

log = logging.getLogger(__name__)
OBS_PROCESS = "obs64.exe" if WIN else "obs"

DEFAULTS = {"host": "localhost", "port": 4455, "password": ""}

REQUESTS = {
    "ToggleRecord": "Start / stop recording",
    "ToggleRecordPause": "Pause / resume recording",
    "ToggleStream": "Start / stop streaming",
    "SaveReplayBuffer": "Save replay",
    "ToggleReplayBuffer": "Start / stop replay buffer",
    "ToggleVirtualCam": "Virtual camera on / off",
    "ToggleMic": "Mute / unmute microphone",
    "SetCurrentProgramScene": "Switch scene",
}

# Flags OBS understands on launch, used when it isn't running yet.
LAUNCH_FLAGS = {"ToggleRecord": ["--startrecording"], "ToggleStream": ["--startstreaming"],
                "ToggleVirtualCam": ["--startvirtualcam"], "ToggleReplayBuffer": ["--startreplaybuffer"]}


class OBSError(Exception):
    pass


def auth_string(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


def settings_from(cfg: dict | None) -> tuple[str, int, str]:
    o = ((cfg or {}).get("integrations") or {}).get("obs") or {}
    password = ""
    if o.get("password_dpapi"):
        try:
            password = winapi.unprotect(o["password_dpapi"])
        except Exception:
            password = ""
    try:
        port = int(o.get("port") or DEFAULTS["port"])
    except (TypeError, ValueError):
        port = DEFAULTS["port"]
    return str(o.get("host") or DEFAULTS["host"]), port, password


class OBSClient:
    def __init__(self, host: str = "localhost", port: int = 4455, password: str = "", timeout: float = 2.0):
        self.host, self.port, self.password, self.timeout = host, port, password, timeout
        self.ws = None

    def __enter__(self) -> "OBSClient":
        import websocket
        try:
            self.ws = websocket.create_connection(f"ws://{self.host}:{self.port}", timeout=self.timeout)
        except (ConnectionRefusedError, socket.timeout, TimeoutError, OSError) as e:
            raise ConnectionRefusedError(str(e)) from e
        except websocket.WebSocketException as e:
            raise OBSError(f"Something other than OBS is answering on port {self.port}") from e
        hello = self._recv()
        if hello.get("op") != 0:
            raise OBSError("unexpected reply from OBS")
        ident = {"rpcVersion": 1, "eventSubscriptions": 0}
        a = (hello.get("d") or {}).get("authentication")
        if a:
            if not self.password:
                raise OBSError("OBS asks for a WebSocket password — add it in Apps → OBS Studio")
            ident["authentication"] = auth_string(self.password, a["salt"], a["challenge"])
        self._send({"op": 1, "d": ident})
        msg = self._recv()
        if msg.get("op") != 2:
            raise OBSError("OBS refused the connection")
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass

    def _send(self, obj: dict) -> None:
        self.ws.send(json.dumps(obj))

    def _recv(self) -> dict:
        import websocket
        try:
            opcode, data = self.ws.recv_data(control_frame=True)
        except websocket.WebSocketConnectionClosedException as e:
            raise OBSError("OBS closed the connection") from e
        except (websocket.WebSocketTimeoutException, socket.timeout, TimeoutError) as e:
            raise OBSError("OBS didn't answer") from e
        if opcode == websocket.ABNF.OPCODE_CLOSE:
            code = int.from_bytes(data[:2], "big") if len(data) >= 2 else 0
            if code == 4009:
                raise OBSError("Wrong OBS WebSocket password")
            raise OBSError(f"OBS closed the connection ({code})")
        try:
            return json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        except ValueError as e:
            raise OBSError("unreadable reply from OBS") from e

    def call(self, request: str, data: dict | None = None) -> dict:
        rid = uuid.uuid4().hex
        self._send({"op": 6, "d": {"requestType": request, "requestId": rid, "requestData": data or {}}})
        for _ in range(50):
            msg = self._recv()
            d = msg.get("d") or {}
            if msg.get("op") == 7 and d.get("requestId") == rid:
                st = d.get("requestStatus") or {}
                if not st.get("result"):
                    raise OBSError(st.get("comment") or f"OBS said no (code {st.get('code')})")
                return d.get("responseData") or {}
        raise OBSError("no answer from OBS")


def scenes(cfg: dict | None, timeout: float = 0.8) -> list[str]:
    host, port, pw = settings_from(cfg)
    try:
        with OBSClient(host, port, pw, timeout) as c:
            data = c.call("GetSceneList")
    except Exception:
        return []
    # OBS lists scenes bottom-up; show them in the order the user sees them.
    return [s.get("sceneName", "") for s in reversed(data.get("scenes", [])) if s.get("sceneName")]


def test_connection(host: str, port: int, password: str) -> str:
    """Returns a human-readable status line (raises nothing)."""
    try:
        with OBSClient(host, port, password, 1.5) as c:
            v = c.call("GetVersion")
        return f"Connected to OBS {v.get('obsVersion', '')}"
    except ConnectionRefusedError:
        if winapi.is_running(OBS_PROCESS):
            return "OBS is running but its WebSocket server is off (Tools → WebSocket Server Settings)"
        return "OBS isn't running"
    except OBSError as e:
        return str(e)
    except Exception as e:  # pragma: no cover
        return f"Couldn't connect: {e}"


def run(action: dict, cfg: dict | None, obs_exe: str = "") -> None:
    request = action.get("request", "ToggleRecord")
    data = dict(action.get("data") or {})
    host, port, pw = settings_from(cfg)
    try:
        with OBSClient(host, port, pw) as c:
            if request == "ToggleMic":
                special = c.call("GetSpecialInputs")
                mic = special.get("mic1") or "Mic/Aux"
                c.call("ToggleInputMute", {"inputName": mic})
            else:
                c.call(request, data)
        return
    except ConnectionRefusedError:
        pass
    # Not reachable: start OBS with the right flag, or explain how to turn the server on.
    if winapi.is_running(OBS_PROCESS):
        raise OBSError("Turn on OBS's WebSocket server: Tools → WebSocket Server Settings")
    flags = list(LAUNCH_FLAGS.get(request, []))
    if request == "SetCurrentProgramScene" and data.get("sceneName"):
        flags = ["--scene", data["sceneName"]]
    if not obs_exe or not os.path.exists(obs_exe):
        raise OBSError("OBS Studio isn't running")
    if not flags and request not in ("ToggleMic",):
        raise OBSError("Start OBS first")
    if not flags:
        raise OBSError("OBS isn't running")
    log.info("starting OBS with %s", flags)
    from .actions import open_target
    open_target(obs_exe, " ".join(f'"{f}"' if " " in f else f for f in flags), os.path.dirname(obs_exe))

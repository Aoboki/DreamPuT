from powershell import router as powershell_router

from webcam_signaling import (
    webcam_browser,
    webcam_host,
)

import local_webcams
import motion_recorder
import telegram_notify

from control_signaling import (
    control_browser,
    control_host,
)

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect

from fastapi.templating import Jinja2Templates

from fastapi.responses import (
    Response,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
    FileResponse,
)

from fastapi.staticfiles import StaticFiles

from datetime import datetime
from pathlib import Path

import asyncio
import base64
import hmac
import json
import os
import re
import platform
import secrets
import socket
import time

from Monitor.router import router as monitor_router


# ============================================================
# CLOUDFLARE TURN (ICE servers)
# ============================================================

_ice_cache = {
    "expires": 0.0,
    "servers": None,
}


def _load_cloudflare_turn_config():
    base = Path(__file__).resolve().parent
    cfg_path = base / "turn_cloudflare.txt"
    token_id = os.environ.get("CF_TURN_TOKEN_ID", "").strip()
    api_token = os.environ.get("CF_TURN_API_TOKEN", "").strip()
    ttl = int(os.environ.get("CF_TURN_TTL", "86400"))

    print(f"🔎 TURN config file: {cfg_path} exists={cfg_path.exists()}")

    if cfg_path.exists():
        try:
            for line in cfg_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "TURN_TOKEN_ID":
                    token_id = v
                elif k == "API_TOKEN":
                    api_token = v
                elif k == "TTL":
                    try:
                        ttl = int(v)
                    except ValueError:
                        pass
        except Exception as e:
            print(f"⚠️ turn_cloudflare.txt read error: {e}")

    print(
        f"🔎 TURN_TOKEN_ID len={len(token_id)} "
        f"API_TOKEN len={len(api_token)} ttl={ttl}"
    )
    return token_id, api_token, ttl


def get_cloudflare_ice_servers(force: bool = False):
    """
    Returns iceServers list for RTCPeerConnection.
    Uses Cloudflare TURN API; caches credentials until near expiry.
    """
    import urllib.request

    now = time.time()
    # refresh 1h before expiry
    if (
        not force
        and _ice_cache["servers"] is not None
        and now < float(_ice_cache["expires"]) - 3600
    ):
        return _ice_cache["servers"]

    token_id, api_token, ttl = _load_cloudflare_turn_config()

    fallback = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
        {"urls": "stun:stun.cloudflare.com:3478"},
    ]

    if not token_id or not api_token:
        print("⚠️ Cloudflare TURN not configured — STUN only")
        return fallback

    url = (
        "https://rtc.live.cloudflare.com/v1/turn/keys/"
        + token_id
        + "/credentials/generate-ice-servers"
    )
    body_str = json.dumps({"ttl": ttl})

    def _fetch_via_urllib():
        body = body_str.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": "Bearer " + api_token,
                "Content-Type": "application/json",
                "User-Agent": "RemoteDesktop/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _fetch_via_curl():
        import subprocess
        # curl works on this Pi even when urllib is blocked/misconfigured
        cmd = [
            "curl", "-sS", "--max-time", "20",
            "-H", "Authorization: Bearer " + api_token,
            "-H", "Content-Type: application/json",
            "-d", body_str,
            url,
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return json.loads(out.decode("utf-8"))

    try:
        data = None
        last_err = None
        for fetcher, name in ((_fetch_via_urllib, "urllib"), (_fetch_via_curl, "curl")):
            try:
                data = fetcher()
                print(f"✅ Cloudflare TURN via {name}")
                break
            except Exception as e:
                last_err = e
                print(f"⚠️ Cloudflare TURN {name} failed: {type(e).__name__}: {e}")
        if data is None:
            raise RuntimeError(f"all fetch methods failed: {last_err}")

        servers = data.get("iceServers") or data.get("ice_servers")
        if not servers:
            print(f"⚠️ Cloudflare TURN unexpected response: {data}")
            return fallback

        # Normalize urls to list for consistency
        normalized = []
        for s in servers:
            urls = s.get("urls")
            if isinstance(urls, str):
                urls = [urls]
            entry = {"urls": urls}
            if s.get("username"):
                entry["username"] = s["username"]
            if s.get("credential"):
                entry["credential"] = s["credential"]
            normalized.append(entry)

        # Drop port 53 URLs (often blocked in browsers)
        cleaned = []
        for entry in normalized:
            urls = entry.get("urls") or []
            urls = [u for u in urls if ":53" not in str(u) and not str(u).endswith(":53")]
            if not urls:
                continue
            e = dict(entry)
            e["urls"] = urls
            cleaned.append(e)

        # Always keep Google STUN as extra fallback at the front
        merged = [
            {"urls": ["stun:stun.l.google.com:19302"]},
            {"urls": ["stun:stun1.l.google.com:19302"]},
        ] + cleaned

        _ice_cache["servers"] = merged
        _ice_cache["expires"] = now + max(300, ttl)
        print(f"✅ Cloudflare ICE servers refreshed (ttl={ttl}s, n={len(merged)})")
        return merged

    except Exception as e:
        detail = str(e)
        try:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError):
                body = e.read().decode("utf-8", errors="replace")[:500]
                detail = f"HTTP {e.code}: {body}"
        except Exception:
            pass
        print(f"❌ Cloudflare TURN API error: {type(e).__name__}: {detail}")
        if _ice_cache["servers"] is not None:
            return _ice_cache["servers"]
        return fallback




# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Remote Desktop Server"
)

app.include_router(powershell_router)

# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

STATIC_DIR = BASE_DIR / "static"

TEMPLATES_DIR = BASE_DIR / "templates"

AUTH_FILE = BASE_DIR / "auth.txt"

MONITOR_DIR = BASE_DIR / "Monitor"

# Login / visit activity log (local fallback only)
STATS_DIR = BASE_DIR / "stats"
ACTIVITY_LOG = STATS_DIR / "user_activity.txt"
MAPS_LOCATIONS_FILE = STATS_DIR / "device_locations.json"
MAPS_DEVICE_KEY = (
    os.environ.get("MAPS_DEVICE_KEY")
    or os.environ.get("DREAMPUT_STATS_KEY")
    or "dreamput-remote-stats-key"
).strip()
MAPS_ONLINE_SEC = 120  # seen within 2 min = online on map


# Source of truth for user stats = DreamPUT https://aoboki.pp.ua
# This remote site only displays them on the dashboard.
DREAMPUT_STATS_URL = os.environ.get(
    "DREAMPUT_STATS_URL",
    "https://aoboki.pp.ua",
).rstrip("/")
DREAMPUT_STATS_KEY = (
    os.environ.get("DREAMPUT_STATS_KEY")
    or os.environ.get("STATS_API_KEY")
    or "dreamput-remote-stats-key"
).strip()


# ============================================================
# GLOBAL STATE
# ============================================================

# Browser monitor connections
#
# {
#     "MUKM0502": websocket
# }

monitor_connections = {}


# Monitor frames
#
# {
#     "MUKM0502": jpeg_bytes
# }

monitor_frames = {}


# All connected hosts
#
# {
#     "MUKM0502": {
#         "websocket": websocket,
#         "host_id": "MUKM0502",
#         ...
#     }
# }

connected_hosts = {}

file_request_futures = {}


# ============================================================
# POWERSHELL PENDING RESULTS
# ============================================================

powershell_pending = {}


# Last screenshots
#
# {
#     "MUKM0502": jpeg_bytes
# }

last_screenshots = {}


# ============================================================
# AUTH
# ============================================================

auth_sessions = {}

SESSION_MAX_AGE = 60 * 60 * 24 * 7


# ============================================================
# STATIC
# ============================================================

app.mount(
    "/static",
    StaticFiles(
        directory=str(STATIC_DIR)
    ),
    name="static",
)


# ============================================================
# TEMPLATES
# ============================================================

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
)


# ============================================================
# MONITOR TEMPLATES
# ============================================================

monitor_templates = Jinja2Templates(
    directory=str(MONITOR_DIR)
)


# ============================================================
# AUTH FILE
# ============================================================

def load_credentials():

    if not AUTH_FILE.exists():

        print(
            f"❌ Authentication file not found: "
            f"{AUTH_FILE}"
        )

        return None, None

    login = None
    password = None

    try:

        with open(
            AUTH_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            for line in file:

                line = line.strip()

                if not line:
                    continue

                if line.startswith("#"):
                    continue

                if "=" not in line:
                    continue

                key, value = line.split(
                    "=",
                    1,
                )

                key = key.strip()
                value = value.strip()

                if key == "login":

                    login = value

                elif key == "password":

                    password = value

    except Exception as e:

        print(
            f"❌ Error reading auth.txt: {e}"
        )

        return None, None

    if not login or not password:

        print(
            "❌ auth.txt must contain:"
        )

        print(
            "   login=..."
        )

        print(
            "   password=..."
        )

        return None, None

    return login, password


# ============================================================
# ACTIVITY STATS (time, IP, login)
# ============================================================


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def log_user_activity(
    event: str,
    login: str,
    ip: str,
    extra: str = "",
) -> None:
    """Append one line: time | IP | login | event"""
    try:
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | IP: {ip} | Login: {login or '-'} | Event: {event}"
        if extra:
            line += f" | {extra}"
        line += "\n"
        with ACTIVITY_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"⚠️ activity log write failed: {e}")


def count_registered_users() -> int:
    """
    Registered accounts from auth.txt (1) plus unique successful
    logins recorded in the activity log.
    """
    names = set()
    login, _ = load_credentials()
    if login:
        names.add(login.strip().lower())
    try:
        if ACTIVITY_LOG.is_file():
            for raw in ACTIVITY_LOG.read_text(encoding="utf-8").splitlines():
                # ... | Login: name | Event: login_ok
                if "Login:" not in raw:
                    continue
                if "login_ok" not in raw and "login_success" not in raw:
                    continue
                try:
                    part = raw.split("Login:", 1)[1]
                    name = part.split("|", 1)[0].strip().lower()
                    if name and name != "-":
                        names.add(name)
                except Exception:
                    pass
    except Exception:
        pass
    return max(1, len(names)) if names else 0


def count_active_sessions() -> int:
    """Sessions that are still valid (not expired) — local remote site only."""
    now = time.time()
    dead = []
    n = 0
    for token, session in list(auth_sessions.items()):
        created = float(session.get("created") or 0)
        if now - created > SESSION_MAX_AGE:
            dead.append(token)
            continue
        n += 1
    for token in dead:
        auth_sessions.pop(token, None)
    return n



def _load_device_locations() -> dict:
    try:
        if MAPS_LOCATIONS_FILE.is_file():
            import json as _json
            data = _json.loads(MAPS_LOCATIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"⚠️ maps load: {e}")
    return {}


def _save_device_locations(data: dict) -> None:
    try:
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        import json as _json
        MAPS_LOCATIONS_FILE.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"⚠️ maps save: {e}")


def _maps_device_key_ok(request: Request) -> bool:
    key = (
        request.headers.get("X-Maps-Key")
        or request.headers.get("X-Device-Key")
        or request.query_params.get("key")
        or ""
    ).strip()
    return bool(key) and key == MAPS_DEVICE_KEY

def fetch_dreamput_summary() -> dict:
    """
    Pull registered/active user counts from DreamPUT (aoboki.pp.ua).
    """
    import urllib.request

    url = f"{DREAMPUT_STATS_URL}/api/stats/summary"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "X-Stats-Key": DREAMPUT_STATS_KEY,
                "User-Agent": "RemoteDesktop-Stats/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        print(f"⚠️ DreamPUT stats fetch failed: {e}")
        return {}




def summarize_page_visits_text(text: str) -> dict:
    """Count lines and unique IPs from page_visits log text."""
    total = 0
    ips = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        total += 1
        if "IP:" in line:
            try:
                ip = line.split("IP:", 1)[1].split("|", 1)[0].strip()
                if ip and ip != "-":
                    ips.add(ip)
            except Exception:
                pass
    return {"page_visits": total, "unique_visitor_ips": len(ips)}

def fetch_dreamput_page_visits_text() -> str:
    """Pull page-visit IP log from DreamPUT (aoboki.pp.ua)."""
    import urllib.request

    url = f"{DREAMPUT_STATS_URL}/api/stats/page-visits"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "X-Stats-Key": DREAMPUT_STATS_KEY,
                "User-Agent": "RemoteDesktop-Stats/1.0",
                "Accept": "text/plain",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"⚠️ DreamPUT page-visits fetch failed: {e}")
        return (
            f"# Could not load DreamPUT page visits from {DREAMPUT_STATS_URL}\n"
            f"# Error: {e}\n"
        )

def fetch_dreamput_activity_text() -> str:
    """Pull activity log text from DreamPUT."""
    import urllib.request

    url = f"{DREAMPUT_STATS_URL}/api/stats/activity"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "X-Stats-Key": DREAMPUT_STATS_KEY,
                "User-Agent": "RemoteDesktop-Stats/1.0",
                "Accept": "text/plain",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"⚠️ DreamPUT activity fetch failed: {e}")
        return (
            f"# Could not load DreamPUT activity from {DREAMPUT_STATS_URL}\n"
            f"# Error: {e}\n"
        )


def set_dreamput_free_slots(slots: int) -> dict:
    """Change DreamPUT free_slots via admin API."""
    import urllib.request

    url = f"{DREAMPUT_STATS_URL}/api/admin/free-slots"
    body = json.dumps({"slots": int(slots)}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Admin-Key": DREAMPUT_STATS_KEY,
                "X-Stats-Key": DREAMPUT_STATS_KEY,
                "User-Agent": "RemoteDesktop-Stats/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️ DreamPUT set free_slots failed: {e}")
        return {"ok": False, "error": str(e)}


# ============================================================
# SESSION
# ============================================================

def create_session(
    username: str
):

    token = secrets.token_urlsafe(32)

    auth_sessions[token] = {

        "username":
            username,

        "created":
            time.time(),

    }

    return token


def verify_session(
    token: str | None
):

    if not token:
        return False

    session = auth_sessions.get(
        token
    )

    if not session:
        return False

    created = session.get(
        "created",
        0,
    )

    if (
        time.time() - created
        > SESSION_MAX_AGE
    ):

        auth_sessions.pop(
            token,
            None,
        )

        return False

    return True


def get_session_token(
    request: Request,
):

    return request.cookies.get(
        "remote_desktop_session"
    )


def is_authenticated(
    request: Request,
):

    token = get_session_token(
        request
    )

    return verify_session(
        token
    )


def get_authenticated_username(
    request: Request,
):

    token = get_session_token(
        request
    )

    if not token:
        return None

    session = auth_sessions.get(
        token
    )

    if not session:
        return None

    return session.get(
        "username"
    )


# ============================================================
# MONITOR HOST WEBSOCKET
#
# Monitor.py -> Server
#
# /ws/monitor-host/{host_id}
# ============================================================

@app.websocket(
    "/ws/monitor-host/{host_id}"
)
async def monitor_host_websocket(
    websocket: WebSocket,
    host_id: str,
):

    await websocket.accept()

    host_id = str(
        host_id
    ).strip()

    print()
    print("=" * 60)
    print(
        f"🖥 Monitor.py connected: {host_id}"
    )
    print("=" * 60)

    try:

        while True:

            print(
                f"⏳ Waiting for frame from {host_id}..."
            )

            message = (
                await websocket.receive_text()
            )

            print(
                f"📨 MESSAGE RECEIVED from "
                f"{host_id}: "
                f"{len(message):,} chars"
            )

            # ------------------------------------------------
            # JSON
            # ------------------------------------------------

            try:

                data = json.loads(
                    message
                )

            except json.JSONDecodeError as e:

                print(
                    f"❌ JSON ERROR from "
                    f"{host_id}: {e}"
                )

                continue

            message_type = data.get(
                "type"
            )

            print(
                f"📨 Message type: "
                f"{message_type}"
            )

            # =================================================
            # SCREEN FRAME
            # =================================================

            if message_type == "screen_frame":

                image_base64 = data.get(
                    "image"
                )

                if not image_base64:

                    print(
                        f"⚠️ EMPTY FRAME "
                        f"from {host_id}"
                    )

                    continue

                print(
                    f"📥 SCREEN FRAME RECEIVED "
                    f"from {host_id} | "
                    f"Base64: "
                    f"{len(image_base64):,} chars"
                )

                # ------------------------------------------------
                # DECODE JPEG
                # ------------------------------------------------

                try:

                    image_bytes = (
                        base64.b64decode(
                            image_base64
                        )
                    )

                except Exception as e:

                    print(
                        f"❌ FRAME DECODE ERROR "
                        f"{host_id}: {e}"
                    )

                    continue

                # ------------------------------------------------
                # SAVE FRAME
                # ------------------------------------------------

                monitor_frames[
                    host_id
                ] = image_bytes

                last_screenshots[
                    host_id
                ] = image_bytes

                print(
                    f"✅ FRAME STORED "
                    f"{host_id} | "
                    f"JPEG: "
                    f"{len(image_bytes):,} bytes"
                )

                # ------------------------------------------------
                # SEND TO BROWSER
                # ------------------------------------------------

                monitor_socket = (
                    monitor_connections.get(
                        host_id
                    )
                )

                if monitor_socket:

                    try:

                        await monitor_socket.send_json({

                            "type":
                                "screen_frame",

                            "host_id":
                                host_id,

                            "image":
                                image_base64,

                            "timestamp":
                                data.get(
                                    "timestamp"
                                ),

                        })

                        print(
                            f"📤 FRAME SENT TO BROWSER "
                            f"{host_id}"
                        )

                    except Exception as e:

                        print(
                            f"❌ BROWSER SEND ERROR "
                            f"{host_id}: {e}"
                        )

                        # Remove dead browser socket
                        current_socket = (
                            monitor_connections.get(
                                host_id
                            )
                        )

                        if (
                            current_socket
                            is monitor_socket
                        ):

                            monitor_connections.pop(
                                host_id,
                                None
                            )

                else:

                    print(
                        f"⚠️ BROWSER NOT CONNECTED "
                        f"for {host_id}"
                    )

            # =================================================
            # MONITOR CONNECTED
            # =================================================

            elif message_type == "monitor_connected":

                print(
                    f"🟢 Monitor.py ready: "
                    f"{host_id}"
                )

            # =================================================
            # UNKNOWN
            # =================================================

            else:

                print(
                    f"📩 Monitor.py message "
                    f"from {host_id}: "
                    f"{message_type}"
                )

    except WebSocketDisconnect:

        print()
        print(
            f"🔴 Monitor.py disconnected: "
            f"{host_id}"
        )

    except Exception as e:

        print()
        print(
            f"❌ Monitor.py error "
            f"{host_id}: "
            f"{type(e).__name__}: {e}"
        )


# ============================================================
# MONITOR BROWSER WEBSOCKET
#
# Browser -> Server
#
# /ws/monitor/{host_id}
# ============================================================

@app.websocket(
    "/ws/monitor/{host_id}"
)
async def monitor_websocket(
    websocket: WebSocket,
    host_id: str,
):

    await websocket.accept()

    host_id = str(
        host_id
    ).strip().upper()

    # --------------------------------------------------------
    # Register browser
    # --------------------------------------------------------

    monitor_connections[
        host_id
    ] = websocket

    print()
    print("=" * 60)

    print(
        f"🌐 BROWSER MONITOR CONNECTED: "
        f"{host_id}"
    )

    print(
        f"🔗 Active monitor connections: "
        f"{list(monitor_connections.keys())}"
    )

    print("=" * 60)

    try:

        while True:

            message = (
                await websocket.receive_text()
            )

            print(
                f"📨 BROWSER MESSAGE "
                f"from {host_id}: "
                f"{len(message):,} chars"
            )

            try:

                data = json.loads(
                    message
                )

            except json.JSONDecodeError as e:

                print(
                    f"❌ BROWSER JSON ERROR "
                    f"{host_id}: {e}"
                )

                continue

            message_type = data.get(
                "type"
            )

            print(
                f"🌐 Browser message type: "
                f"{message_type}"
            )

            # ------------------------------------------------
            # Viewer connected
            # ------------------------------------------------

            if message_type == "viewer_connected":

                print(
                    f"🟢 Viewer ready for "
                    f"{host_id}"
                )

                await websocket.send_json({

                    "type":
                        "monitor_connected",

                    "host_id":
                        host_id,

                })

            elif message_type == "input":

                # Forward mouse/keyboard to Windows host
                host = connected_hosts.get(host_id)
                if not host:
                    # try lowercase / original
                    for key, val in connected_hosts.items():
                        if str(key).lower() == str(host_id).lower():
                            host = val
                            break

                if host and host.get("websocket"):
                    try:
                        await host["websocket"].send_text(
                            json.dumps(
                                {
                                    "command": "input",
                                    "action": data.get("action"),
                                    "x": data.get("x"),
                                    "y": data.get("y"),
                                    "button": data.get("button"),
                                    "key": data.get("key"),
                                    "code": data.get("code"),
                                    "ctrl": data.get("ctrl"),
                                    "alt": data.get("alt"),
                                    "shift": data.get("shift"),
                                    "meta": data.get("meta"),
                                    "deltaX": data.get("deltaX"),
                                    "deltaY": data.get("deltaY"),
                                },
                                ensure_ascii=False,
                            )
                        )
                    except Exception as e:
                        print(f"❌ input forward error {host_id}: {e}")
                else:
                    print(f"⚠️ input: host offline {host_id}")

            elif message_type == "control_mode":

                print(
                    f"🎮 Control mode "
                    f"{'ON' if data.get('enabled') else 'OFF'} "
                    f"for {host_id}"
                )

            else:

                print(
                    f"📩 Browser message "
                    f"{host_id}: "
                    f"{message_type}"
                )

    except WebSocketDisconnect:

        print()
        print(
            f"🔴 BROWSER MONITOR DISCONNECTED: "
            f"{host_id}"
        )

    except Exception as e:

        print()
        print(
            f"❌ BROWSER MONITOR ERROR "
            f"{host_id}: "
            f"{type(e).__name__}: {e}"
        )

    finally:

        # ----------------------------------------------------
        # Check that this is still the active browser
        # connection for this host.
        #
        # This is important when the page is refreshed:
        # old websocket must NOT stop a newly opened monitor.
        # ----------------------------------------------------

        current_socket = (
            monitor_connections.get(
                host_id
            )
        )

        if current_socket is websocket:

            # ------------------------------------------------
            # Remove browser monitor connection
            # ------------------------------------------------

            monitor_connections.pop(
                host_id,
                None
            )

            print()
            print(
                f"🧹 Browser monitor connection removed: "
                f"{host_id}"
            )

            # ------------------------------------------------
            # Browser closed monitor page.
            #
            # Tell host.py to stop Monitor_v2.py.
            # host.py itself continues running.
            # ------------------------------------------------

            try:

                print()
                print(
                    f"⏹ Browser closed monitor. "
                    f"Stopping Monitor.py on {host_id}"
                )

                success = await send_host_command(
                    host_id,
                    "monitor_stop"
                )

                if success:

                    print(
                        f"✅ monitor_stop sent to "
                        f"{host_id}"
                    )

                else:

                    print(
                        f"⚠️ Could not send monitor_stop "
                        f"to {host_id}"
                    )

            except Exception as e:

                print(
                    f"❌ Failed to stop monitor "
                    f"{host_id}: "
                    f"{type(e).__name__}: {e}"
                )

        else:

            print(
                f"ℹ️ Old monitor connection closed: "
                f"{host_id}"
            )

# ============================================================
# MONITOR START
# ============================================================

@app.post(
    "/api/monitor/start/{host_id}"
)
async def monitor_start(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    success = await send_host_command(
        host_id,
        "monitor_start",
    )

    if not success:

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Host is offline",

                "monitor_running":
                    False,
            },
            status_code=404,
        )

    return {

        "status":
            "ok",

        "host_id":
            host_id,

        "monitor":
            "starting",

        "monitor_running":
            True,
    }


# ============================================================
# MONITOR STOP
# ============================================================

@app.post(
    "/api/monitor/stop/{host_id}"
)
async def monitor_stop(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    success = await send_host_command(
        host_id,
        "monitor_stop",
    )

    if not success:

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Host is offline",

                "monitor_running":
                    False,
            },
            status_code=404,
        )

    return {

        "status":
            "ok",

        "host_id":
            host_id,

        "monitor":
            "stopping",

        "monitor_running":
            False,
    }


# ============================================================
# MONITOR STATUS
# ============================================================

@app.get(
    "/api/monitor/{host_id}"
)
async def monitor_status(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    host_id = str(
        host_id
    ).strip()

    host = connected_hosts.get(
        host_id
    )

    if not host:

        return {

            "host_id":
                host_id,

            "monitor_running":
                False,

            "status":
                "offline",
        }

    return {

        "host_id":
            host_id,

        "monitor_running":
            bool(
                host.get(
                    "monitor_running",
                    False
                )
            ),

        "status":
            "online",
    }


# ============================================================
# LOGIN PAGE
# ============================================================

@app.get("/login")
async def login_page(
    request: Request,
):

    if is_authenticated(request):

        return RedirectResponse(
            url="/",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
    )


# ============================================================
# LOGIN API
# ============================================================

@app.post("/api/login")
async def login(
    request: Request,
):

    try:

        data = await request.json()

    except Exception:

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Invalid request",
            },
            status_code=400,
        )

    username = str(
        data.get(
            "username",
            "",
        )
    ).strip()

    password = str(
        data.get(
            "password",
            "",
        )
    )

    saved_login, saved_password = (
        load_credentials()
    )

    if (
        saved_login is None
        or saved_password is None
    ):

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Authentication is not configured",
            },
            status_code=500,
        )

    client_ip = _client_ip(request)

    if not hmac.compare_digest(
        username,
        saved_login,
    ):

        print(
            f"⚠️ Failed login attempt: "
            f"{username}"
        )
        log_user_activity(
            "login_fail",
            username,
            client_ip,
        )

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Invalid username or password",
            },
            status_code=401,
        )

    if not hmac.compare_digest(
        password.encode("utf-8"),
        saved_password.encode("utf-8"),
    ):

        print(
            f"⚠️ Failed login attempt: "
            f"{username}"
        )
        log_user_activity(
            "login_fail",
            username,
            client_ip,
        )

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Invalid username or password",
            },
            status_code=401,
        )

    token = create_session(
        username
    )

    print(
        f"🔐 Successful login: "
        f"{username}"
    )
    log_user_activity(
        "login_ok",
        username,
        client_ip,
    )

    response = JSONResponse(
        {
            "status":
                "ok"
        }
    )

    response.set_cookie(

        key=
            "remote_desktop_session",

        value=
            token,

        max_age=
            SESSION_MAX_AGE,

        httponly=
            True,

        secure=
            True,

        samesite=
            "lax",

        path=
            "/",
    )

    return response


# ============================================================
# LOGOUT
# ============================================================

@app.post("/api/logout")
async def logout(
    request: Request,
):

    token = get_session_token(
        request
    )

    if token:

        auth_sessions.pop(
            token,
            None,
        )

    response = JSONResponse(
        {
            "status":
                "ok"
        }
    )

    response.delete_cookie(
        key=
            "remote_desktop_session",

        path=
            "/",
    )

    return response


# ============================================================
# ROOT PAGE
# ============================================================

@app.get("/")
async def index(
    request: Request,
):

    if not is_authenticated(request):

        return RedirectResponse(
            url="/login",
            status_code=303,
        )

    username = (
        get_authenticated_username(
            request
        )
    )

    return templates.TemplateResponse(

        request=request,

        name="index.html",

        context={
            "username":
                username
        },
    )


# ============================================================
# MONITOR PAGE
# ============================================================

@app.get("/monitor")
async def monitor_page(
    request: Request,
    host: str | None = None,
):

    if not is_authenticated(request):

        return RedirectResponse(
            url="/login",
            status_code=303,
        )

    username = get_authenticated_username(
        request
    )

    return monitor_templates.TemplateResponse(

        request=request,

        name="monitor.html",

        context={

            "username":
                username,

            "host_id":
                host,

        },
    )


# ============================================================
# SERVER INFORMATION
# ============================================================

def get_server_cpu_temperature():

    temperature_file = Path(
        "/sys/class/thermal/"
        "thermal_zone0/temp"
    )

    try:

        if temperature_file.exists():

            value = (
                temperature_file
                .read_text(
                    encoding="utf-8"
                )
                .strip()
            )

            temperature = (
                int(value) / 1000
            )

            return round(
                temperature,
                1,
            )

    except Exception:

        pass

    try:

        import subprocess

        result = subprocess.run(

            [
                "vcgencmd",
                "measure_temp",
            ],

            capture_output=True,

            text=True,

            timeout=2,
        )

        output = result.stdout.strip()

        if output.startswith(
            "temp="
        ):

            value = (
                output
                .replace(
                    "temp=",
                    "",
                )
                .replace(
                    "'C",
                    "",
                )
            )

            return round(
                float(value),
                1,
            )

    except Exception:

        pass

    return None


def get_server_memory():

    try:

        import psutil

        memory = (
            psutil.virtual_memory()
        )

        return {

            "total_gb":
                round(
                    memory.total
                    / (1024 ** 3),
                    1,
                ),

            "used_gb":
                round(
                    memory.used
                    / (1024 ** 3),
                    1,
                ),

            "free_gb":
                round(
                    memory.available
                    / (1024 ** 3),
                    1,
                ),

            "percent":
                round(
                    memory.percent,
                    1,
                ),
        }

    except Exception:

        return {

            "total_gb": None,

            "used_gb": None,

            "free_gb": None,

            "percent": None,
        }


def get_server_disk():

    try:

        import psutil

        usage = psutil.disk_usage(
            "/"
        )

        return {

            "total_gb":
                round(
                    usage.total
                    / (1024 ** 3),
                    1,
                ),

            "used_gb":
                round(
                    usage.used
                    / (1024 ** 3),
                    1,
                ),

            "free_gb":
                round(
                    usage.free
                    / (1024 ** 3),
                    1,
                ),

            "percent":
                round(
                    usage.percent,
                    1,
                ),
        }

    except Exception:

        return {

            "total_gb": None,

            "used_gb": None,

            "free_gb": None,

            "percent": None,
        }


# ============================================================
# SERVER INFO API
# ============================================================

@app.get("/api/server/info")
async def server_info(
    request: Request,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.2)
    except Exception:
        cpu_percent = None

    # Hardware info = this remote server; user stats = DreamPUT
    base = {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "cpu": platform.processor(),
        "cpu_count": os.cpu_count(),
        "cpu_percent": cpu_percent,
        "memory": get_server_memory(),
        "disk": get_server_disk(),
        "temperature": get_server_cpu_temperature(),
        "time": datetime.now().isoformat(),
        "online_hosts": len(connected_hosts),
        "dreamput_domain": "aoboki.pp.ua",
    }

    dp = fetch_dreamput_summary()
    if dp.get("ok") or dp.get("registered_users") is not None:
        base["registered_users"] = dp.get("registered_users")
        base["active_users"] = dp.get("active_users")
        base["dreamput_online_hosts"] = dp.get("online_hosts")
        base["dreamput_domain"] = dp.get("domain") or "aoboki.pp.ua"
        base["free_slots"] = dp.get("free_slots")
        base["free_used"] = dp.get("free_used")
        base["page_visits"] = dp.get("page_visits")
        base["unique_visitor_ips"] = dp.get("unique_visitor_ips")
        base["stats_source"] = "dreamput"
    else:
        base["registered_users"] = count_registered_users()
        base["active_users"] = count_active_sessions()
        base["free_slots"] = None
        base["free_used"] = None
        base["stats_source"] = "local_fallback"

    # Always fill page visit counters (summary may be old or missing fields)
    if base.get("page_visits") is None or base.get("unique_visitor_ips") is None:
        try:
            visit_stats = summarize_page_visits_text(fetch_dreamput_page_visits_text())
            if base.get("page_visits") is None:
                base["page_visits"] = visit_stats.get("page_visits", 0)
            if base.get("unique_visitor_ips") is None:
                base["unique_visitor_ips"] = visit_stats.get("unique_visitor_ips", 0)
        except Exception as e:
            print(f"⚠️ page visit summarize: {e}")
            base.setdefault("page_visits", 0)
            base.setdefault("unique_visitor_ips", 0)

    return base


# ============================================================
# USER ACTIVITY STATS (text log)
# ============================================================






# ============================================================
# noVNC reverse proxy (auth required — not public)
# Upstream: websockify on 127.0.0.1:6080
# Disable public hostname vnc.aoboki.pp.ua in Cloudflare Tunnel.
# ============================================================

NOVNC_UPSTREAM = os.environ.get("NOVNC_UPSTREAM", "http://127.0.0.1:6080").rstrip("/")


def _session_token_from_ws(websocket: WebSocket) -> str | None:
    return websocket.cookies.get("remote_desktop_session")


@app.api_route("/vnc", methods=["GET", "HEAD"])
@app.api_route("/vnc/{full_path:path}", methods=["GET", "HEAD", "POST", "OPTIONS"])
async def novnc_http_proxy(request: Request, full_path: str = ""):
    """Serve noVNC static files + HTTP only for logged-in users."""
    if not is_authenticated(request):
        # browser navigation → login; XHR → 401
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" in accept or request.method == "GET" and not full_path:
            return RedirectResponse(url="/login", status_code=303)
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    path = full_path.lstrip("/") if full_path else ""
    url = f"{NOVNC_UPSTREAM}/{path}" if path else f"{NOVNC_UPSTREAM}/"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            url,
            method=request.method if request.method != "HEAD" else "GET",
            headers={
                "User-Agent": request.headers.get("user-agent") or "RemoteDesktop-noVNC-proxy",
                "Accept": request.headers.get("accept") or "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = b"" if request.method == "HEAD" else resp.read()
                ctype = resp.headers.get("Content-Type") or "application/octet-stream"
                # cache static assets briefly
                headers = {
                    "Content-Type": ctype,
                    "Permissions-Policy": "clipboard-read=(self), clipboard-write=(self)",
                }
                return Response(content=data, status_code=getattr(resp, "status", 200), headers=headers)
        except urllib.error.HTTPError as e:
            body = e.read() if request.method != "HEAD" else b""
            return Response(
                content=body,
                status_code=e.code,
                media_type=e.headers.get("Content-Type") or "text/plain",
            )
    except Exception as e:
        print(f"⚠️ noVNC HTTP proxy: {e}")
        return JSONResponse(
            {"detail": "noVNC upstream unavailable", "error": str(e)},
            status_code=502,
        )


@app.websocket("/vnc/{full_path:path}")
async def novnc_ws_proxy(websocket: WebSocket, full_path: str):
    """WebSocket proxy to websockify — requires session cookie."""
    token = _session_token_from_ws(websocket)
    if not verify_session(token):
        await websocket.close(code=4401)
        return

    await websocket.accept(subprotocol=None)
    # Prefer subprotocol binary if client asked — accept default

    path = full_path.lstrip("/")
    qs = websocket.scope.get("query_string", b"").decode("utf-8", errors="ignore")
    upstream_url = f"ws://127.0.0.1:6080/{path}"
    if qs:
        upstream_url = f"{upstream_url}?{qs}"

    try:
        import websockets
    except ImportError:
        print("⚠️ websockets package missing — noVNC WS proxy disabled")
        await websocket.close(code=1011)
        return

    try:
        async with websockets.connect(
            upstream_url,
            max_size=8 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if msg["type"] != "websocket.receive":
                            continue
                        if "bytes" in msg and msg["bytes"] is not None:
                            await upstream.send(msg["bytes"])
                        elif "text" in msg and msg["text"] is not None:
                            await upstream.send(msg["text"])
                except Exception:
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except Exception:
                    pass

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except Exception as e:
        print(f"⚠️ noVNC WS proxy: {e}")
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@app.get("/webcams")
async def webcams_page(request: Request):
    """Yard surveillance — two local USB cameras on this host."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="webcams.html",
        context={},
    )


@app.get("/motion-events")
async def motion_events_page(request: Request):
    """Motion trigger photos + linked video clips (yard cameras)."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="motion_events.html",
        context={},
    )




@app.get("/api/local-cams/recordings")
async def api_list_all_recordings(request: Request):
    motion_recorder.ensure_running()
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return {
        "left": motion_recorder.list_recordings("left"),
        "right": motion_recorder.list_recordings("right"),
        "motion": motion_recorder.worker.status,
        "settings": motion_recorder.motion_settings(),
    }


@app.get("/api/local-cams/recordings/{side}")
async def api_list_side_recordings(side: str, request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    side = side.lower().strip()
    if side not in ("left", "right"):
        return JSONResponse({"detail": "side must be left|right"}, status_code=400)
    return {"side": side, "files": motion_recorder.list_recordings(side)}


@app.get("/api/local-cams/recordings/{side}/{filename}")
async def api_get_recording(side: str, filename: str, request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    side = side.lower().strip()
    if side not in ("left", "right"):
        return JSONResponse({"detail": "bad side"}, status_code=400)
    # prevent path traversal
    name = Path(filename).name
    if not re.match(r"^[LR]\d+\.(mp4|jpg|jpeg)$", name, re.I):
        return JSONResponse({"detail": "bad filename"}, status_code=400)
    path = motion_recorder.recordings_dir(side) / name
    if not path.is_file():
        return JSONResponse({"detail": "not found"}, status_code=404)
    lower = name.lower()
    if lower.endswith(".mp4"):
        media = "video/mp4"
    else:
        media = "image/jpeg"
    return FileResponse(
        path,
        media_type=media,
        filename=name,
    )



@app.get("/api/telegram/status")
async def api_telegram_status(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    cfg = telegram_notify.load_config()
    return {
        "enabled": bool(cfg.get("enabled")),
        "has_token": bool((cfg.get("bot_token") or "").strip()),
        "has_chat_id": bool(str(cfg.get("chat_id") or "").strip()),
        "chat_id": str(cfg.get("chat_id") or ""),
        "send_photo": bool(cfg.get("send_photo", True)),
    }


@app.get("/api/telegram/discover-chats")
async def api_telegram_discover(request: Request):
    """After you write /start to the bot, lists chat_id candidates."""
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    cfg = telegram_notify.load_config()
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        return JSONResponse({"detail": "bot_token not set"}, status_code=400)
    chats = await asyncio.to_thread(telegram_notify.get_updates_chat_ids, token)
    return {"chats": chats}


@app.post("/api/telegram/chat-id")
async def api_telegram_set_chat(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)
    chat_id = str((body or {}).get("chat_id") or "").strip()
    if not chat_id:
        return JSONResponse({"detail": "chat_id required"}, status_code=400)
    cfg = telegram_notify.load_config()
    cfg["chat_id"] = chat_id
    telegram_notify.save_config(cfg)
    return {"ok": True, "chat_id": chat_id}


@app.post("/api/telegram/test")
async def api_telegram_test(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    root = motion_recorder.REC_ROOT
    photo = None
    for side in ("left", "right"):
        d = root / side
        if not d.is_dir():
            continue
        jpgs = sorted(d.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)
        if jpgs:
            photo = jpgs[0]
            break
    if photo is None:
        return JSONResponse(
            {"detail": "No .jpg yet — wait for motion or add a test jpg under data/recordings/"},
            status_code=404,
        )
    ok = await telegram_notify.send_photo(photo, caption=f"Test from DreamPUT · {photo.name}")
    return {"ok": ok, "photo": photo.name}


@app.get("/api/local-cams/motion/status")
async def api_motion_status(request: Request):
    motion_recorder.ensure_running()
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return {
        "worker": motion_recorder.worker.status,
        "settings": motion_recorder.motion_settings(),
    }


@app.get("/api/local-cams")
async def api_local_cams_get(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return local_webcams.load_config()


@app.put("/api/local-cams")
async def api_local_cams_put(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"detail": "Expected object"}, status_code=400)
    return local_webcams.save_config(body)


@app.get("/api/local-cams/detect")
async def api_local_cams_detect(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return {
        "video": local_webcams.detect_v4l_devices(),
        "audio": local_webcams.detect_alsa_devices(),
        "ffmpeg": bool(local_webcams.ffmpeg_bin()),
    }



@app.get("/api/local-cams/{cam_id}/snapshot")
async def api_local_cam_snapshot(cam_id: str, request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    cam = local_webcams.get_camera(cam_id)
    if not cam:
        return JSONResponse({"detail": "Camera not found"}, status_code=404)
    try:
        data = await local_webcams.grab_snapshot_jpeg(cam)
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)
    return Response(content=data, media_type="image/jpeg")


@app.get("/api/local-cams/{cam_id}/stream")
async def api_local_cam_stream(cam_id: str, request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    cam = local_webcams.get_camera(cam_id)
    if not cam or not cam.get("enabled", True):
        return JSONResponse({"detail": "Camera not found or disabled"}, status_code=404)
    return StreamingResponse(
        local_webcams.mjpeg_stream_with_fallback(cam),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/local-cams/{cam_id}/audio")
async def api_local_cam_audio(cam_id: str, request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    cfg = local_webcams.load_config()
    if (cfg.get("audio_from") or "") != cam_id:
        return JSONResponse(
            {"detail": "Audio is assigned to another camera (or muted)"},
            status_code=403,
        )
    cam = local_webcams.get_camera(cam_id)
    if not cam:
        return JSONResponse({"detail": "Camera not found"}, status_code=404)
    alsa = (cam.get("audio_device") or "").strip()
    if not alsa:
        return JSONResponse({"detail": "No audio device configured"}, status_code=404)
    return StreamingResponse(
        local_webcams.audio_mp3_stream(alsa),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
        },
    )



@app.get("/interface")
async def interface_page(request: Request):
    """Server Python interface page — UI scaffold, execution later."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="interface.html",
        context={},
    )


@app.get("/maps")
async def maps_page(request: Request):
    """Family map — device location markers."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="maps.html",
        context={},
    )


@app.get("/api/maps/locations")
async def api_maps_locations(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    raw = _load_device_locations()
    now = time.time()
    devices = []
    for device_id, info in raw.items():
        if not isinstance(info, dict):
            continue
        ts = float(info.get("ts") or 0)
        age = int(now - ts) if ts else None
        devices.append({
            "device_id": device_id,
            "name": info.get("name") or device_id,
            "lat": info.get("lat"),
            "lon": info.get("lon"),
            "accuracy": info.get("accuracy"),
            "ts": ts,
            "age_sec": age,
            "online": age is not None and age <= MAPS_ONLINE_SEC,
            "battery": info.get("battery"),
        })
    devices.sort(key=lambda d: d.get("ts") or 0, reverse=True)
    return {"ok": True, "devices": devices, "online_sec": MAPS_ONLINE_SEC}


@app.post("/api/maps/location")
async def api_maps_location_report(request: Request):
    """
    Phone/app reports GPS position.
    Auth: header X-Maps-Key: <MAPS_DEVICE_KEY>
    Body JSON: { device_id, name?, lat, lon, accuracy?, battery? }
    """
    if not _maps_device_key_ok(request):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    device_id = str(body.get("device_id") or body.get("id") or "").strip()
    if not device_id:
        return JSONResponse({"error": "device_id required"}, status_code=400)
    try:
        lat = float(body.get("lat"))
        lon = float(body.get("lon"))
    except Exception:
        return JSONResponse({"error": "lat/lon required"}, status_code=400)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return JSONResponse({"error": "invalid coordinates"}, status_code=400)
    name = str(body.get("name") or device_id).strip()[:80]
    accuracy = body.get("accuracy")
    try:
        accuracy = float(accuracy) if accuracy is not None else None
    except Exception:
        accuracy = None
    battery = body.get("battery")
    data = _load_device_locations()
    data[device_id] = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "accuracy": accuracy,
        "battery": battery,
        "ts": time.time(),
    }
    _save_device_locations(data)
    return {"ok": True, "device_id": device_id}


@app.get("/stats")
async def stats_page(request: Request):
    """Informational page: login activity log (time, IP, login)."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "username": get_authenticated_username(request) or "",
        },
    )


@app.post("/api/admin/dreamput-free-slots")
async def api_set_dreamput_free_slots(request: Request):
    """
    Admin on remote.aoboki.pp.ua: change DreamPUT free_slots (DEFAULT_FREE_SLOTS).
    Requires logged-in remote session.
    """
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        slots = int(body.get("slots"))
    except Exception:
        return JSONResponse({"ok": False, "error": "slots must be an integer"}, status_code=400)
    if slots < 0 or slots > 100000:
        return JSONResponse({"ok": False, "error": "slots out of range"}, status_code=400)
    result = set_dreamput_free_slots(slots)
    if not result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": result.get("error") or "DreamPUT update failed"},
            status_code=502,
        )
    return {
        "ok": True,
        "free_slots": result.get("free_slots", slots),
        "free_used": result.get("free_used"),
        "promoted": result.get("promoted") or [],
    }



@app.get("/api/stats/page-visits")
async def api_stats_page_visits(request: Request):
    """Page visit IPs from DreamPUT (aoboki.pp.ua)."""
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = fetch_dreamput_page_visits_text()
    if not (body or "").strip():
        body = (
            "# DreamPUT page visits (https://aoboki.pp.ua)\n"
            "# Format: TIME | IP | Path | UA\n"
            "# No entries yet.\n"
        )
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=dreamput_page_visits.txt",
        },
    )


@app.get("/api/stats/page-visits/download")
async def api_stats_page_visits_download(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    body = fetch_dreamput_page_visits_text() or "# empty\n"
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=dreamput_page_visits.txt",
        },
    )


@app.get("/api/stats/activity")
async def api_stats_activity(request: Request):
    """Activity log from DreamPUT (aoboki.pp.ua), not local remote logins."""
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    text = fetch_dreamput_activity_text()
    if not text.strip():
        text = (
            "# DreamPUT user activity (https://aoboki.pp.ua)\n"
            "# Format: TIME | IP | Login | Event\n"
            "# No entries yet.\n"
        )
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=dreamput_user_activity.txt",
        },
    )


@app.get("/api/stats/activity/download")
async def api_stats_download(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    text = fetch_dreamput_activity_text() or "# empty\n"
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; filename=dreamput_user_activity.txt",
        },
    )


# ============================================================
# HOST STATUS
# ============================================================

@app.get("/api/host/status")
async def host_status(
    request: Request,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    host = connected_hosts.get(
        "home"
    )

    if not host:

        return {

            "host_id":
                "home",

            "status":
                "offline",
        }

    return host_to_public_data(
        host
    )


# ============================================================
# CONVERT HOST TO PUBLIC DATA
# ============================================================

def host_to_public_data(
    host
):

    return {

        "host_id":
            host.get("host_id"),

        "status":
            "online",

        "username":
            host.get("username"),

        "name":
            host.get("name"),

        "computer_name":
            host.get("computer_name"),

        "os":
            host.get("os"),

        "os_version":
            host.get("os_version"),

        "os_release":
            host.get("os_release"),

        "architecture":
            host.get("architecture"),

        "python_version":
            host.get("python_version"),

        "cpu":
            host.get("cpu"),

        "cpu_count":
            host.get("cpu_count"),

        "cpu_percent":
            host.get("cpu_percent"),

        "memory":
            host.get("memory"),

        "disk":
            host.get("disk"),

        "cpu_temperature":
            host.get("cpu_temperature"),

        "windows_uptime":
            host.get("windows_uptime"),

        "windows_boot_time":
            host.get("windows_boot_time"),

        "uptime_seconds":
            host.get("uptime_seconds"),

        "boot_time":
            host.get("boot_time"),

        "connected_since":
            host.get("connected_since"),

        "last_seen":
            host.get("last_seen"),

        "monitor_running":
            host.get(
                "monitor_running",
                False
            ),

    }


# ============================================================
# SCREENSHOT
# ============================================================

@app.get(
    "/api/viewer/screenshot/{host_id}/image"
)
async def get_screenshot(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    image = last_screenshots.get(
        host_id
    )

    if image is None:

        return JSONResponse(
            {
                "detail":
                    "No screenshot available"
            },
            status_code=404,
        )

    return Response(

        content=image,

        media_type=
            "image/jpeg",

        headers={

            "Cache-Control":
                "no-store, no-cache, "
                "must-revalidate",

            "Pragma":
                "no-cache",

            "Expires":
                "0",
        },
    )


# ============================================================
# SEND COMMAND TO HOST
# ============================================================

async def send_host_command(
    host_id: str,
    command: str,
):

    host = connected_hosts.get(
        host_id
    )

    if not host:

        return False

    websocket = host.get(
        "websocket"
    )

    if not websocket:

        return False

    try:

        await websocket.send_text(

            json.dumps(

                {
                    "command":
                        command
                },

                ensure_ascii=False,
            )
        )

        print(
            f"📡 Command sent to "
            f"{host_id}: "
            f"{command}"
        )

        return True

    except Exception as e:

        print(
            f"❌ Command error "
            f"for {host_id}: "
            f"{e}"
        )

        return False

# ============================================================
# WEBCAM CONTROL API
# ============================================================

@app.post("/api/webcam/start/{host_id}")
async def webcam_start_api(
    host_id: str,
    request: Request,
):

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )


    host_id = str(
        host_id
    ).strip()


    if not host_id:

        return JSONResponse(
            {
                "success":
                    False,

                "error":
                    "Host ID is empty",
            },
            status_code=400,
        )


    # --------------------------------------------------------
    # CHECK HOST
    # --------------------------------------------------------

    host = connected_hosts.get(
        host_id
    )


    if not host:

        return JSONResponse(
            {
                "success":
                    False,

                "error":
                    "Host is offline",

                "host_id":
                    host_id,
            },
            status_code=404,
        )


    # --------------------------------------------------------
    # SEND COMMAND
    # --------------------------------------------------------

    success = await send_host_command(
        host_id,
        "webcam_start",
    )


    if not success:

        return JSONResponse(
            {
                "success":
                    False,

                "error":
                    "Failed to send command",

                "host_id":
                    host_id,
            },
            status_code=500,
        )


    print()
    print(
        "📷 Webcam START command sent"
    )

    print(
        f"   Host: {host_id}"
    )


    return JSONResponse(
        {
            "success":
                True,

            "host_id":
                host_id,

            "command":
                "webcam_start",
        }
    )


# ============================================================
# WEBCAM STOP
# ============================================================

@app.post("/api/webcam/stop/{host_id}")
async def webcam_stop_api(
    host_id: str,
    request: Request,
):

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )


    host_id = str(
        host_id
    ).strip()


    if not host_id:

        return JSONResponse(
            {
                "success":
                    False,

                "error":
                    "Host ID is empty",
            },
            status_code=400,
        )


    # --------------------------------------------------------
    # CHECK HOST
    # --------------------------------------------------------

    host = connected_hosts.get(
        host_id
    )


    if not host:

        return JSONResponse(
            {
                "success":
                    False,

                "error":
                    "Host is offline",

                "host_id":
                    host_id,
            },
            status_code=404,
        )


    # --------------------------------------------------------
    # SEND COMMAND
    # --------------------------------------------------------

    success = await send_host_command(
        host_id,
        "webcam_stop",
    )


    if not success:

        return JSONResponse(
            {
                "success":
                    False,

                "error":
                    "Failed to send command",

                "host_id":
                    host_id,
            },
            status_code=500,
        )


    print()
    print(
        "📷 Webcam STOP command sent"
    )

    print(
        f"   Host: {host_id}"
    )


    return JSONResponse(
        {
            "success":
                True,

            "host_id":
                host_id,

            "command":
                "webcam_stop",
        }
    )

# ============================================================
# REQUEST SCREENSHOT
# ============================================================

@app.post(
    "/api/host/{host_id}/screenshot"
)
async def request_screenshot(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    success = await send_host_command(
        host_id,
        "screenshot",
    )

    if not success:

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Host is offline",
            },
            status_code=404,
        )

    return {

        "status":
            "ok",

        "command":
            "screenshot",

        "host_id":
            host_id,
    }

# ============================================================
# START WEBCAM PROCESS ON HOST
# ============================================================

@app.post(
    "/api/host/webcam/start/{host_id}"
)
async def start_host_webcam(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )


    host_id = str(
        host_id
    ).strip()


    if not host_id:

        return JSONResponse(
            {
                "success":
                    False,

                "detail":
                    "Host ID is required",
            },
            status_code=400,
        )


    success = await send_host_command(
        host_id,
        "webcam_start"
    )


    if not success:

        return JSONResponse(
            {
                "success":
                    False,

                "detail":
                    f"Host '{host_id}' is offline",
            },
            status_code=404,
        )


    print()
    print(
        f"📷 Webcam start command sent: "
        f"{host_id}"
    )


    return {

        "success":
            True,

        "host_id":
            host_id,

        "command":
            "webcam_start",

    }

# ============================================================
# REQUEST WEBCAM
# ============================================================

@app.post(
    "/api/host/{host_id}/webcam"
)
async def request_webcam(
    request: Request,
    host_id: str,
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    success = await send_host_command(
        host_id,
        "webcam",
    )

    if not success:

        return JSONResponse(
            {
                "status":
                    "error",

                "detail":
                    "Host is offline",
            },
            status_code=404,
        )

    return {

        "status":
            "ok",

        "command":
            "webcam",

        "host_id":
            host_id,
    }


# ============================================================
# HOST WEBSOCKET
#
# host.py -> Server
#
# /ws/host/{host_id}
# ============================================================

@app.websocket(
    "/ws/host/{host_id}"
)
async def host_websocket(
    websocket: WebSocket,
    host_id: str,
):

    await websocket.accept()

    print()
    print(
        f"🟢 WebSocket ACCEPTED: {host_id}"
    )

    # ========================================================
    # NORMALIZE HOST ID
    # ========================================================

    host_id = str(
        host_id
    ).strip()

    if not host_id:

        await websocket.close()

        return

    # ========================================================
    # CHECK EXISTING CONNECTION
    # ========================================================

    old_host = connected_hosts.get(
        host_id
    )

    if old_host:

        old_websocket = old_host.get(
            "websocket"
        )

        if old_websocket:

            print()
            print(
                f"♻️ Replacing existing connection: "
                f"{host_id}"
            )

            try:

                await old_websocket.close()

            except Exception:

                pass

    # ========================================================
    # CREATE HOST ENTRY
    # ========================================================

    connected_hosts[
        host_id
    ] = {

        "host_id":
            host_id,

        "websocket":
            websocket,

        "connected_since":
            datetime.now().isoformat(),

        "last_seen":
            datetime.now().isoformat(),

        "monitor_running":
            False,
    }

    print()
    print(
        "🟢 Host connected:"
    )

    print(
        f"   ID: {host_id}"
    )

    print(
        f"   Total hosts: "
        f"{len(connected_hosts)}"
    )

    # ========================================================
    # MAIN WEBSOCKET LOOP
    # ========================================================

    try:

        while True:

            message = (
                await websocket.receive_text()
            )

            print()
            print(
                f"⏳ DATA FROM HOST: {host_id}"
            )

            # ------------------------------------------------
            # GET CURRENT HOST
            # ------------------------------------------------

            host = connected_hosts.get(
                host_id
            )

            if not host:

                print(
                    f"⚠️ Host entry disappeared: "
                    f"{host_id}"
                )

                break

            # ------------------------------------------------
            # IGNORE OLD CONNECTION
            # ------------------------------------------------

            if host.get(
                "websocket"
            ) is not websocket:

                print(
                    f"♻️ Old connection ignored: "
                    f"{host_id}"
                )

                break

            # ------------------------------------------------
            # UPDATE LAST SEEN
            # ------------------------------------------------

            host[
                "last_seen"
            ] = datetime.now().isoformat()

            # =================================================
            # PARSE JSON
            # =================================================

            try:

                data = json.loads(
                    message
                )

            except json.JSONDecodeError:

                print()
                print(
                    f"⚠️ Invalid JSON from "
                    f"{host_id}"
                )

                continue

            message_type = data.get(
                "type"
            )

            print(
                f"🌐 Host message type: "
                f"{message_type}"
            )

            # =================================================
            # HOST INFO
            # =================================================

            if message_type == "host_info":

                host.update({

                    "host_id":
                        host_id,

                    "username":
                        data.get("username"),

                    "name":
                        data.get("name"),

                    "computer_name":
                        data.get("computer_name"),

                    "os":
                        data.get("os"),

                    "os_version":
                        data.get("os_version"),

                    "os_release":
                        data.get("os_release"),

                    "architecture":
                        data.get("architecture"),

                    "python_version":
                        data.get("python_version"),

                    "cpu":
                        data.get("cpu"),

                    "cpu_count":
                        data.get("cpu_count"),

                    "cpu_percent":
                        data.get("cpu_percent"),

                    "memory":
                        data.get("memory"),

                    "disk":
                        data.get("disk"),

                    "cpu_temperature":
                        data.get("cpu_temperature"),

                    "windows_uptime":
                        data.get("windows_uptime"),

                    "windows_boot_time":
                        data.get("windows_boot_time"),

                    "uptime_seconds":
                        data.get("uptime_seconds"),

                    "boot_time":
                        data.get("boot_time"),

                    "connected_since":
                        host.get(
                            "connected_since"
                        ),

                    "last_seen":
                        datetime.now().isoformat(),

                })

                print()
                print(
                    "💻 Host information received:"
                )

                print(
                    f"   🆔 ID: "
                    f"{host_id}"
                )

                print(
                    f"   👤 User: "
                    f"{data.get('username')}"
                )

                print(
                    f"   💻 Computer: "
                    f"{data.get('computer_name')}"
                )

                print(
                    f"   🪟 OS: "
                    f"{data.get('os')} "
                    f"{data.get('os_release')}"
                )

                print(
                    f"   🐍 Python: "
                    f"{data.get('python_version')}"
                )

                print(
                    f"   🧠 CPU: "
                    f"{data.get('cpu_percent')}%"
                )

                memory = data.get(
                    "memory"
                )

                if memory:

                    print(
                        f"   💾 RAM: "
                        f"{memory.get('percent')}%"
                    )

                disk = data.get(
                    "disk"
                )

                if disk:

                    print(
                        f"   💿 Disk free: "
                        f"{disk.get('free_gb')} GB"
                    )

                print(
                    f"   ⏱ Windows uptime: "
                    f"{data.get('windows_uptime')}"
                )

                print(
                    f"   🕐 Windows boot: "
                    f"{data.get('windows_boot_time')}"
                )

                print(
                    f"   🌐 Total hosts: "
                    f"{len(connected_hosts)}"
                )

            # =================================================
            # HEARTBEAT
            # =================================================

            elif message_type == "heartbeat":

                host[
                    "last_seen"
                ] = datetime.now().isoformat()

                print(
                    f"💓 Heartbeat from "
                    f"{host_id}"
                )
            # =================================================
            # POWERSHELL RESULT
            # =================================================

            elif message_type == "powershell_result":

                print()
                print(
                    "💻 PowerShell result received:"
                )

                print(
                    f"   Host: {host_id}"
                )

                print(
                    f"   Success: "
                    f"{data.get('success')}"
                )

                print(
                    f"   Output: "
                    f"{data.get('output', '')}"
                )

                if data.get("error"):

                    print(
                        f"   Error: "
                        f"{data.get('error')}"
                    )

                # -------------------------------------------------
                # FIND WAITING HTTP REQUEST
                # -------------------------------------------------

                pending = powershell_pending.get(
                    host_id
                )

                if pending:

                    try:

                        if not pending.done():

                            pending.set_result(
                                data
                            )

                            print(
                                "📤 PowerShell result "
                                "delivered to HTTP request"
                            )

                    except Exception as e:

                        print(
                            "❌ Failed to deliver "
                            "PowerShell result:"
                        )

                        print(
                            f"   {type(e).__name__}: {e}"
                        )
# =================================================
            # POWERSHELL STATUS          ← НОВЫЙ БЛОК
            # =================================================

            elif message_type == "powershell_status":

                from powershell import handle_powershell_status
                await handle_powershell_status(data)


            # =================================================
            # POWERSHELL OUTPUT          ← НОВЫЙ БЛОК
            # =================================================

            elif message_type == "powershell_output":

                from powershell import handle_powershell_output
                await handle_powershell_output(data)


            # =================================================
            # POWERSHELL FINISHED        ← НОВЫЙ БЛОК
            # =================================================

            elif message_type == "files_result":
                rid = data.get("request_id")
                fut = file_request_futures.get(rid)
                if fut and not fut.done():
                    fut.set_result(data)
                else:
                    print(f"📁 files_result without waiter: {rid}")

            elif message_type == "powershell_finished":

                from powershell import handle_powershell_finished
                await handle_powershell_finished(data)
                
            # =================================================
            # SCREEN FRAME
            # =================================================

            elif message_type == "screen_frame":

                try:

                    frame_host_id = str(
                        host_id
                    ).strip().upper()

                    image_base64 = data.get(
                        "image"
                    )

                    if not image_base64:

                        print(
                            f"⚠️ Empty screen frame "
                            f"from {frame_host_id}"
                        )

                        continue

                    # ------------------------------------------------
                    # DECODE IMAGE
                    # ------------------------------------------------

                    image_bytes = (
                        base64.b64decode(
                            image_base64
                        )
                    )

                    # ------------------------------------------------
                    # SAVE LAST SCREENSHOT
                    # ------------------------------------------------

                    last_screenshots[
                        frame_host_id
                    ] = image_bytes

                    # ------------------------------------------------
                    # SAVE MONITOR FRAME
                    # ------------------------------------------------

                    monitor_frames[
                        frame_host_id
                    ] = image_bytes

                    print(
                        f"📸 Screen frame from "
                        f"{frame_host_id}: "
                        f"{len(image_bytes):,} bytes"
                    )

                    # ------------------------------------------------
                    # SEND FRAME TO MONITOR BROWSER
                    # ------------------------------------------------

                    monitor_socket = (
                        monitor_connections.get(
                            frame_host_id
                        )
                    )

                    if monitor_socket:

                        try:

                            await monitor_socket.send_json({

                                "type":
                                    "screen_frame",

                                "host_id":
                                    frame_host_id,

                                "image":
                                    image_base64,

                                "timestamp":
                                    data.get(
                                        "timestamp"
                                    ),

                            })

                            print(
                                f"📤 Screen frame sent "
                                f"to monitor: "
                                f"{frame_host_id}"
                            )

                        except Exception as e:

                            print(
                                f"❌ Failed to send "
                                f"screen frame to monitor "
                                f"{frame_host_id}: "
                                f"{type(e).__name__}: {e}"
                            )

                    else:

                        print(
                            f"⚠️ No monitor connected "
                            f"for {frame_host_id}"
                        )

                except Exception as e:

                    print()
                    print(
                        f"❌ Screen frame processing "
                        f"error from {host_id}: "
                        f"{type(e).__name__}: {e}"
                    )

            # =================================================
            # UNKNOWN MESSAGE
            # =================================================

            else:

                print()
                print(
                    f"⚠️ Unknown message type "
                    f"from {host_id}: "
                    f"{message_type}"
                )

    # ========================================================
    # HOST DISCONNECTED
    # ========================================================

    except WebSocketDisconnect as e:

        print()
        print(
            f"🔴 Host disconnected: "
            f"{host_id}"
        )

        print(
            f"   Code: {e.code}"
        )

        if e.reason:

            print(
                f"   Reason: {e.reason}"
            )

    # ========================================================
    # OTHER ERROR
    # ========================================================

    except Exception as e:

        print()
        print(
            f"❌ Host websocket error: "
            f"{host_id}"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

    # ========================================================
    # CLEANUP
    # ========================================================

    finally:

        current_host = (
            connected_hosts.get(
                host_id
            )
        )

        # ----------------------------------------------------
        # REMOVE ONLY CURRENT CONNECTION
        # ----------------------------------------------------

        if (
            current_host
            and current_host.get(
                "websocket"
            ) is websocket
        ):

            connected_hosts.pop(
                host_id,
                None
            )

            print()
            print(
                f"🔴 Host removed: "
                f"{host_id}"
            )

            print(
                f"   Total hosts: "
                f"{len(connected_hosts)}"
            )

        else:

            print()
            print(
                f"♻️ Old connection finished: "
                f"{host_id}"
            )





# ============================================================
# Вебкамера и новый сайт начало
# ============================================================

@app.get("/webcam")
async def webcam_page(
    request: Request
):

    if not is_authenticated(request):

        return RedirectResponse(
            "/login",
            status_code=303,
        )


    return templates.TemplateResponse(
        request=request,
        name="webcam.html",
    )

@app.websocket(
    "/ws/webcam/browser/{host_id}"
)
async def webcam_browser_ws(
    websocket: WebSocket,
    host_id: str,
):

    await webcam_browser(
        websocket,
        host_id
    )


@app.websocket(
    "/ws/webcam/host/{host_id}"
)
async def webcam_host_ws(
    websocket: WebSocket,
    host_id: str,
):

    await webcam_host(
        websocket,
        host_id
    )
# ============================================================
# Вебкамера и новый сайт конец
# ============================================================

# ============================================================
# CLEAN STALE HOSTS
# ============================================================

HOST_TIMEOUT = 35


def cleanup_stale_hosts():

    now = time.time()

    stale_hosts = []

    for host_id, host in list(
        connected_hosts.items()
    ):

        last_seen = host.get(
            "last_seen"
        )

        if not last_seen:
            continue

        try:

            last_seen_timestamp = (
                datetime.fromisoformat(
                    last_seen
                ).timestamp()
            )

        except Exception:

            continue

        if (
            now - last_seen_timestamp
            > HOST_TIMEOUT
        ):

            stale_hosts.append(
                host_id
            )

    for host_id in stale_hosts:

        host = connected_hosts.pop(
            host_id,
            None
        )

        last_screenshots.pop(
            host_id,
            None
        )

        monitor_frames.pop(
            host_id,
            None
        )

        if host:

            print(
                f"⏱ Host timeout: "
                f"{host_id}"
            )

# ============================================================
# POWERSHELL PAGE
# ============================================================


# ============================================================
# CONTROL (WebRTC screen)
# ============================================================

@app.get("/control")
async def control_page(
    request: Request,
    host: str | None = None,
):

    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)

    username = get_authenticated_username(request)
    return templates.TemplateResponse(
        request=request,
        name="control.html",
        context={"username": username, "host": host or ""},
    )


@app.websocket("/ws/control/browser/{host_id}")
async def control_browser_ws(websocket: WebSocket, host_id: str):
    await control_browser(websocket, host_id)


@app.websocket("/ws/control/host/{host_id}")
async def control_host_ws(websocket: WebSocket, host_id: str):
    await control_host(websocket, host_id)


@app.post("/api/control/start/{host_id}")
async def control_start_api(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    success = await send_host_command(host_id, "control_start")
    if not success:
        for k in list(connected_hosts.keys()):
            if str(k).lower() == str(host_id).lower():
                success = await send_host_command(k, "control_start")
                host_id = k
                break
    if not success:
        return JSONResponse({"status": "error", "detail": "Host offline"}, status_code=404)
    return {"status": "ok", "command": "control_start", "host_id": host_id}


@app.post("/api/control/stop/{host_id}")
async def control_stop_api(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    success = await send_host_command(host_id, "control_stop")
    if not success:
        for k in list(connected_hosts.keys()):
            if str(k).lower() == str(host_id).lower():
                success = await send_host_command(k, "control_stop")
                break
    return {"status": "ok", "command": "control_stop", "host_id": host_id}


@app.get("/powershell")
async def powershell_page(
    request: Request,
):

    if not is_authenticated(request):

        return RedirectResponse(
            "/login",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="powershell.html",
    )




@app.get("/api/webrtc/ice-servers")
async def webrtc_ice_servers(request: Request):
    """
    Temporary Cloudflare TURN credentials for browser + host clients.
    Safe to call often — server caches until near TTL expiry.
    """
    try:
        servers = await asyncio.to_thread(get_cloudflare_ice_servers)
        has_turn = False
        for s in servers or []:
            urls = s.get("urls") or []
            if isinstance(urls, str):
                urls = [urls]
            for u in urls:
                if "turn:" in str(u) or "turns:" in str(u):
                    if s.get("username") and s.get("credential"):
                        has_turn = True
                        break
            if has_turn:
                break
        print(f"🧊 /api/webrtc/ice-servers turn={has_turn} n={len(servers or [])}")
        return JSONResponse({
            "iceServers": servers,
            "turn": has_turn,
            "provider": "cloudflare" if has_turn else "stun-only",
        })
    except Exception as e:
        return JSONResponse(
            {
                "iceServers": [
                    {"urls": ["stun:stun.l.google.com:19302"]},
                    {"urls": ["stun:stun1.l.google.com:19302"]},
                ],
                "turn": False,
                "provider": "stun-only",
                "error": str(e),
            },
            status_code=200,
        )


# ============================================================
# ALL CONNECTED HOSTS
# ============================================================



# ============================================================
# FILE MANAGER API
# ============================================================

async def _files_rpc(host_id: str, command: str, payload: dict, timeout: float = 60.0):
    import uuid
    host_id = str(host_id).strip()
    host = connected_hosts.get(host_id)
    if not host:
        for k, v in list(connected_hosts.items()):
            if str(k).lower() == host_id.lower():
                host = v
                host_id = k
                break
    if not host or not host.get("websocket"):
        return {"ok": False, "error": "Host offline"}

    request_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    file_request_futures[request_id] = fut

    msg = {
        "command": command,
        "request_id": request_id,
        **payload,
    }
    try:
        await host["websocket"].send_text(json.dumps(msg, ensure_ascii=False))
        result = await asyncio.wait_for(fut, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Timeout waiting for host"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        file_request_futures.pop(request_id, None)


@app.get("/files")
async def files_page(request: Request, host: str | None = None):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    username = get_authenticated_username(request)
    return templates.TemplateResponse(
        request=request,
        name="files.html",
        context={"username": username, "host": host or ""},
    )


@app.post("/api/files/{host_id}/drives")
async def api_files_drives(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    return await _files_rpc(host_id, "files_drives", {})


@app.post("/api/files/{host_id}/list")
async def api_files_list(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    return await _files_rpc(host_id, "files_list", {"path": body.get("path") or "C:\\"})


@app.post("/api/files/{host_id}/mkdir")
async def api_files_mkdir(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(host_id, "files_mkdir", {"path": body.get("path")})


@app.post("/api/files/{host_id}/delete")
async def api_files_delete(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(host_id, "files_delete", {"path": body.get("path")})


@app.post("/api/files/{host_id}/rename")
async def api_files_rename(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(
        host_id,
        "files_rename",
        {"path": body.get("path"), "new_path": body.get("new_path")},
    )


@app.post("/api/files/{host_id}/download")
async def api_files_download(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(
        host_id, "files_download", {"path": body.get("path")}, timeout=120.0
    )


@app.post("/api/files/{host_id}/upload")
async def api_files_upload(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(
        host_id,
        "files_upload",
        {"path": body.get("path"), "data_b64": body.get("data_b64")},
        timeout=120.0,
    )


@app.post("/api/files/{host_id}/copy")
async def api_files_copy(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(
        host_id,
        "files_copy",
        {"path": body.get("path"), "new_path": body.get("new_path")},
        timeout=120.0,
    )


@app.post("/api/files/{host_id}/move")
async def api_files_move(request: Request, host_id: str):
    if not is_authenticated(request):
        return JSONResponse({"ok": False, "error": "Unauthorized"}, status_code=401)
    body = await request.json()
    return await _files_rpc(
        host_id,
        "files_move",
        {"path": body.get("path"), "new_path": body.get("new_path")},
        timeout=120.0,
    )



@app.get("/api/hosts")
async def get_hosts(
    request: Request
):

    if not is_authenticated(request):

        return JSONResponse(
            {
                "detail":
                    "Unauthorized"
            },
            status_code=401,
        )

    cleanup_stale_hosts()

    hosts = []

    for host in connected_hosts.values():

        hosts.append(
            host_to_public_data(
                host
            )
        )

    return {

        "status":
            "ok",

        "count":
            len(hosts),

        "hosts":
            hosts,
    }


# ============================================================
# CLEANUP SESSIONS
# ============================================================

async def cleanup_sessions():

    while True:

        await asyncio.sleep(
            300
        )

        now = time.time()

        expired = []

        for token, session in list(
            auth_sessions.items()
        ):

            created = session.get(
                "created",
                0,
            )

            if (
                now - created
                > SESSION_MAX_AGE
            ):

                expired.append(
                    token
                )

        for token in expired:

            auth_sessions.pop(
                token,
                None,
            )


# ============================================================
# CLEANUP HOSTS TASK
# ============================================================

async def cleanup_hosts_task():

    while True:

        await asyncio.sleep(
            10
        )

        cleanup_stale_hosts()


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup_event():

    try:
        import logging as _logging
        _log = _logging.getLogger("uvicorn.error")
        motion_recorder.ensure_camera_sides_in_config()
        motion_recorder.worker.start()
        _log.info("motion config path=%s", local_webcams.CONFIG_PATH)
        _log.info("recordings path=%s", motion_recorder.REC_ROOT)
        _log.info("motion settings=%s", motion_recorder.motion_settings())
    except Exception as _me:
        import logging as _logging
        _logging.getLogger("uvicorn.error").exception("MotionWorker start failed: %s", _me)

    print()
    print(
        "========================================"
    )

    print(
        "      Remote Desktop Server"
    )

    print(
        "========================================"
    )

    print(
        f"📁 Base directory: "
        f"{BASE_DIR}"
    )

    print(
        f"🔐 Auth file: "
        f"{AUTH_FILE}"
    )

    print(
        f"🌐 Static directory: "
        f"{STATIC_DIR}"
    )

    print(
        f"📄 Templates directory: "
        f"{TEMPLATES_DIR}"
    )

    print(
        "🌐 Multi-host mode: ENABLED"
    )

    print(
        "🖥 Monitor WebSockets: ENABLED"
    )

    print(
        "========================================"
    )

    login, _ = load_credentials()

    if login:

        print(
            f"👤 Login configured: "
            f"{login}"
        )

    else:

        print(
            "⚠️ Authentication is NOT configured"
        )

    asyncio.create_task(
        cleanup_sessions()
    )

    asyncio.create_task(
        cleanup_hosts_task()
    )


# ============================================================
# MONITOR ROUTER
# ============================================================

app.include_router(
    monitor_router
)


# ============================================================
# END
# ============================================================
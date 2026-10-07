from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

import json


# ============================================================
# ROUTER
# ============================================================

router = APIRouter()


# ============================================================
# APP HELPERS
# ============================================================

def get_connected_hosts():

    from app import connected_hosts

    return connected_hosts


def get_auth_function():

    from app import is_authenticated

    return is_authenticated


def get_templates():

    from app import templates

    return templates


# ============================================================
# HOST
# ============================================================

def normalize_host_id(host_id: str) -> str:

    return str(
        host_id
    ).strip().lower()


def get_host(host_id: str):

    connected_hosts = get_connected_hosts()

    normalized_id = normalize_host_id(
        host_id
    )

    # --------------------------------------------------------
    # First try exact ID
    # --------------------------------------------------------

    host = connected_hosts.get(
        normalized_id
    )

    if host is not None:
        return host


    # --------------------------------------------------------
    # Search case-insensitive
    # --------------------------------------------------------

    for key, value in connected_hosts.items():

        if str(key).strip().lower() == normalized_id:

            return value


    return None


def get_real_host_id(host_id: str):

    connected_hosts = get_connected_hosts()

    normalized_id = normalize_host_id(
        host_id
    )

    for key in connected_hosts.keys():

        if str(key).strip().lower() == normalized_id:

            return key

    return None


# ============================================================
# SEND COMMAND TO HOST
# ============================================================

async def send_monitor_command(
    host_id: str,
    command: str,
):

    connected_hosts = get_connected_hosts()

    real_host_id = get_real_host_id(
        host_id
    )

    if real_host_id is None:

        print()
        print(
            f"❌ Host not found: {host_id}"
        )

        return False, "Host is offline"


    host = connected_hosts.get(
        real_host_id
    )

    if not host:

        print()
        print(
            f"❌ Host data unavailable: "
            f"{host_id}"
        )

        return False, "Host is offline"


    websocket = host.get(
        "websocket"
    )

    if websocket is None:

        print()
        print(
            f"❌ WebSocket unavailable: "
            f"{host_id}"
        )

        return False, (
            "Host WebSocket is unavailable"
        )


    # --------------------------------------------------------
    # Command
    # --------------------------------------------------------

    message = {

        "command":
            command,

        "host_id":
            str(real_host_id),

    }


    try:

        print()
        print(
            "========================================"
        )

        print(
            "🖥 MONITOR COMMAND"
        )

        print(
            f"   Host: {real_host_id}"
        )

        print(
            f"   Command: {command}"
        )

        print(
            f"   WebSocket: {websocket}"
        )

        print(
            "========================================"
        )


        await websocket.send_text(

            json.dumps(

                message,

                ensure_ascii=False,

            )

        )


        print(
            f"📤 Command sent successfully "
            f"to {real_host_id}"
        )


        return True, None


    except Exception as e:

        print()
        print(
            f"❌ Failed to send monitor command"
        )

        print(
            f"   Host: {real_host_id}"
        )

        print(
            f"   Command: {command}"
        )

        print(
            f"   Error: "
            f"{type(e).__name__}: {e}"
        )


        return False, str(e)


# ============================================================
# MONITOR PAGE
# ============================================================

@router.get(
    "/monitor"
)
async def monitor_page(
    request: Request,
):

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    is_authenticated = get_auth_function()

    if not is_authenticated(
        request
    ):

        return RedirectResponse(

            url="/login",

            status_code=303,

        )


    templates = get_templates()


    # --------------------------------------------------------
    # Host ID from URL
    # --------------------------------------------------------

    host_id = request.query_params.get(
        "host"
    )


    if not host_id:

        return templates.TemplateResponse(

            request=request,

            name="monitor.html",

            context={

                "username":
                    request.cookies.get(
                        "remote_desktop_session"
                    ),

                "host_id":
                    None,

                "host":
                    None,

            },

        )


    host_id = str(
        host_id
    ).strip()


    # --------------------------------------------------------
    # Find host
    # --------------------------------------------------------

    host = get_host(
        host_id
    )


    # --------------------------------------------------------
    # Automatically start Monitor.py
    # --------------------------------------------------------

    if host is not None:

        print()
        print(
            "========================================"
        )

        print(
            "🖥 MONITOR PAGE OPENED"
        )

        print(
            f"   Requested host: {host_id}"
        )

        print(
            "   Starting remote monitor..."
        )

        print(
            "========================================"
        )


        success, error = (
            await send_monitor_command(

                host_id,

                "monitor_start",

            )
        )


        if success:

            real_host_id = get_real_host_id(
                host_id
            )

            real_host = get_host(
                real_host_id
            )


            if real_host is not None:

                real_host[
                    "monitor_running"
                ] = True


            print(
                f"🟢 Monitor start command "
                f"sent to {host_id}"
            )


        else:

            print(
                f"🔴 Monitor start failed "
                f"for {host_id}: {error}"
            )


    else:

        print()
        print(
            f"🔴 Monitor requested for "
            f"offline host: {host_id}"
        )


    # --------------------------------------------------------
    # Render page
    # --------------------------------------------------------

    return templates.TemplateResponse(

        request=request,

        name="monitor.html",

        context={

            "username":
                request.cookies.get(
                    "remote_desktop_session"
                ),

            "host_id":
                host_id,

            "host":
                host,

        },

    )


# ============================================================
# MONITOR INFORMATION
# ============================================================

@router.get(
    "/api/monitor/{host_id}"
)
async def monitor_info(
    request: Request,
    host_id: str,
):

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

    is_authenticated = get_auth_function()

    if not is_authenticated(
        request
    ):

        return JSONResponse(

            {

                "status":
                    "error",

                "detail":
                    "Unauthorized",

            },

            status_code=401,

        )


    host_id = str(
        host_id
    ).strip()


    # --------------------------------------------------------
    # Find host
    # --------------------------------------------------------

    host = get_host(
        host_id
    )


    if not host:

        return JSONResponse(

            {

                "status":
                    "offline",

                "host_id":
                    host_id,

                "detail":
                    "Host is offline",

            },

            status_code=404,

        )


    real_host_id = get_real_host_id(
        host_id
    )


    # --------------------------------------------------------
    # Information
    # --------------------------------------------------------

    return {

        "status":
            "online",

        "host_id":
            real_host_id
            or host_id,

        "name":
            host.get(
                "name"
            ),

        "computer_name":
            host.get(
                "computer_name"
            ),

        "username":
            host.get(
                "username"
            ),

        "os":
            host.get(
                "os"
            ),

        "os_version":
            host.get(
                "os_version"
            ),

        "os_release":
            host.get(
                "os_release"
            ),

        "architecture":
            host.get(
                "architecture"
            ),

        "python_version":
            host.get(
                "python_version"
            ),

        "cpu":
            host.get(
                "cpu"
            ),

        "cpu_count":
            host.get(
                "cpu_count"
            ),

        "cpu_percent":
            host.get(
                "cpu_percent"
            ),

        "cpu_temperature":
            host.get(
                "cpu_temperature"
            ),

        "memory":
            host.get(
                "memory"
            ),

        "disk":
            host.get(
                "disk"
            ),

        "connected_since":
            host.get(
                "connected_since"
            ),

        "last_seen":
            host.get(
                "last_seen"
            ),

        "monitor_running":
            host.get(
                "monitor_running",
                False,
            ),

    }


# ============================================================
# MANUAL START API
# ============================================================
#
# Оставляем этот endpoint.
# Он больше не нужен для основного запуска,
# но пригодится для диагностики.
#
# ============================================================

@router.post(
    "/api/monitor/{host_id}/start"
)
async def start_monitor(
    request: Request,
    host_id: str,
):

    is_authenticated = get_auth_function()

    if not is_authenticated(
        request
    ):

        return JSONResponse(

            {

                "status":
                    "error",

                "detail":
                    "Unauthorized",

            },

            status_code=401,

        )


    host_id = str(
        host_id
    ).strip()


    host = get_host(
        host_id
    )


    if not host:

        return JSONResponse(

            {

                "status":
                    "error",

                "host_id":
                    host_id,

                "detail":
                    "Host is offline",

            },

            status_code=404,

        )


    success, error = (
        await send_monitor_command(

            host_id,

            "monitor_start",

        )
    )


    if not success:

        return JSONResponse(

            {

                "status":
                    "error",

                "host_id":
                    host_id,

                "detail":
                    error
                    or "Failed to send command",

            },

            status_code=500,

        )


    real_host_id = get_real_host_id(
        host_id
    )

    real_host = get_host(
        real_host_id
    )


    if real_host is not None:

        real_host[
            "monitor_running"
        ] = True


    return {

        "status":
            "ok",

        "host_id":
            real_host_id
            or host_id,

        "monitor_running":
            True,

        "command":
            "monitor_start",

    }


# ============================================================
# MANUAL STOP API
# ============================================================
#
# Оставляем для диагностики и будущего использования.
#
# ============================================================

@router.post(
    "/api/monitor/{host_id}/stop"
)
async def stop_monitor(
    request: Request,
    host_id: str,
):

    is_authenticated = get_auth_function()

    if not is_authenticated(
        request
    ):

        return JSONResponse(

            {

                "status":
                    "error",

                "detail":
                    "Unauthorized",

            },

            status_code=401,

        )


    host_id = str(
        host_id
    ).strip()


    host = get_host(
        host_id
    )


    if not host:

        return JSONResponse(

            {

                "status":
                    "error",

                "host_id":
                    host_id,

                "detail":
                    "Host is offline",

            },

            status_code=404,

        )


    success, error = (
        await send_monitor_command(

            host_id,

            "monitor_stop",

        )
    )


    if not success:

        return JSONResponse(

            {

                "status":
                    "error",

                "host_id":
                    host_id,

                "detail":
                    error
                    or "Failed to send command",

            },

            status_code=500,

        )


    real_host_id = get_real_host_id(
        host_id
    )

    real_host = get_host(
        real_host_id
    )


    if real_host is not None:

        real_host[
            "monitor_running"
        ] = False


    return {

        "status":
            "ok",

        "host_id":
            real_host_id
            or host_id,

        "monitor_running":
            False,

        "command":
            "monitor_stop",

    }
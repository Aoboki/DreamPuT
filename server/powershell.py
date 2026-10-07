import json
from pathlib import Path

from fastapi import (
    APIRouter,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/powershell"
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
)


# ============================================================
# BROWSER CONNECTIONS
#
# Один PowerShell WebSocket на host_id
#
# {
#     "mukm0502": websocket
# }
# ============================================================

browser_connections = {}


# ============================================================
# POWERSHELL STATE
#
# {
#     "mukm0502": {
#         "running": True,
#         "pid": 1234
#     }
# }
# ============================================================

powershell_state = {}


# ============================================================
# POWERSHELL PAGE
# ============================================================

@router.get("/page")
async def powershell_page(
    request: Request,
):

    return templates.TemplateResponse(
        request=request,
        name="powershell.html",
    )


# ============================================================
# BROWSER WEBSOCKET
#
# Browser:
#
# wss://remote.aoboki.pp.ua/
# api/powershell/ws/browser/{host_id}
#
# ============================================================

@router.websocket(
    "/ws/browser/{host_id}"
)
async def powershell_browser_websocket(
    websocket: WebSocket,
    host_id: str,
):

    host_id = str(
        host_id
    ).strip()

    await websocket.accept()

    print()
    print("=" * 60)
    print("🟢 PowerShell browser connected")
    print(f"   Host: {host_id}")
    print("=" * 60)

    # --------------------------------------------------------
    # Закрываем старое подключение браузера
    # --------------------------------------------------------

    old_socket = browser_connections.get(
        host_id
    )

    if old_socket is not None:

        try:

            await old_socket.close()

        except Exception:
            pass

    browser_connections[
        host_id
    ] = websocket

    # --------------------------------------------------------
    # Отправляем браузеру текущее состояние
    # --------------------------------------------------------

    state = powershell_state.get(
        host_id,
        {}
    )

    try:

        await websocket.send_json(
            {
                "type": "powershell_state",

                "host_id": host_id,

                "running": state.get(
                    "running",
                    False
                ),

                "pid": state.get(
                    "pid"
                ),
            }
        )

    except Exception:
        pass

    # --------------------------------------------------------
    # Ждём сообщения браузера
    #
    # В основном WebSocket нужен для получения результатов
    # от сервера.
    # --------------------------------------------------------

    try:

        while True:

            message = (
                await websocket.receive_text()
            )

            print()
            print(
                f"📥 PowerShell browser message "
                f"{host_id}: {message}"
            )

    except WebSocketDisconnect:

        print()
        print(
            f"🔴 PowerShell browser disconnected: "
            f"{host_id}"
        )

    except Exception as e:

        print()
        print(
            f"❌ PowerShell browser error: "
            f"{host_id}"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

    finally:

        current = browser_connections.get(
            host_id
        )

        if current is websocket:

            browser_connections.pop(
                host_id,
                None
            )

            print(
                f"🧹 PowerShell browser removed: "
                f"{host_id}"
            )


# ============================================================
# SEND TO BROWSER
# ============================================================

async def send_to_browser(
    host_id,
    data,
):

    host_id = str(
        host_id
    ).strip()

    websocket = browser_connections.get(
        host_id
    )

    if websocket is None:

        print()
        print(
            "⚠️ No PowerShell browser connected"
        )

        print(
            f"   Host: {host_id}"
        )

        return False

    try:

        await websocket.send_json(
            data
        )

        return True

    except Exception as e:

        print()
        print(
            "❌ PowerShell browser send error"
        )

        print(
            f"   Host: {host_id}"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        current = browser_connections.get(
            host_id
        )

        if current is websocket:

            browser_connections.pop(
                host_id,
                None
            )

        return False


# ============================================================
# HOST -> SERVER
#
# POWERSHELL OUTPUT
#
# Host sends:
#
# {
#     "type": "powershell_output",
#     "host_id": "...",
#     "stream": "stdout",
#     "output": "..."
# }
# ============================================================
# HOST -> SERVER
#
# POWERSHELL STATUS
# ============================================================

async def handle_powershell_status(data):

    host_id = str(data.get("host_id", "")).strip()

    if not host_id:
        return

    running = bool(data.get("running", False))
    status = data.get("status", "stopped")

    # Обновляем состояние
    powershell_state[host_id] = {
        "running": running,
        "pid": data.get("pid"),
    }

    print()
    print("💻 PowerShell status received")
    print(f"   Host: {host_id}")
    print(f"   Running: {running}")
    print(f"   Status: {status}")

    # Отправляем браузеру
    await send_to_browser(
        host_id,
        {
            "type": "powershell_status",
            "host_id": host_id,
            "running": running,
            "status": status,
            "timestamp": data.get("timestamp"),
        }
    )
# ============================================================

async def handle_powershell_output(
    data,
):

    host_id = str(
        data.get(
            "host_id",
            ""
        )
    ).strip()

    if not host_id:

        print(
            "⚠️ PowerShell output without host_id"
        )

        return

    output = data.get(
        "output",
        ""
    )

    if output is None:

        output = ""

    if not isinstance(
        output,
        str
    ):

        output = str(
            output
        )

    stream = data.get(
        "stream",
        "stdout"
    )

    message = {

        "type":
            "powershell_output",

        "host_id":
            host_id,

        "stream":
            stream,

        "output":
            output,

        "timestamp":
            data.get(
                "timestamp"
            ),
    }

    print()
    print(
        "💻 PowerShell output received"
    )

    print(
        f"   Host: {host_id}"
    )

    print(
        f"   Stream: {stream}"
    )

    if output:

        print(
            output,
            end=""
            if output.endswith("\n")
            else "\n"
        )

    # --------------------------------------------------------
    # Немедленно отправляем в браузер
    # --------------------------------------------------------

    await send_to_browser(
        host_id,
        message
    )


# ============================================================
# HOST -> SERVER
#
# POWERSHELL RESULT
#
# ============================================================

async def handle_powershell_result(
    data,
):

    host_id = str(
        data.get(
            "host_id",
            ""
        )
    ).strip()

    if not host_id:

        return

    success = data.get(
        "success",
        False
    )

    output = data.get(
        "output",
        ""
    )

    error = data.get(
        "error",
        ""
    )

    message = {

        "type":
            "powershell_result",

        "host_id":
            host_id,

        "success":
            success,

        "output":
            output,

        "error":
            error,

        "command_id":
            data.get(
                "command_id"
            ),

        "timestamp":
            data.get(
                "timestamp"
            ),
    }

    print()
    print("=" * 60)
    print("💻 PowerShell result received")
    print(f"   Host: {host_id}")
    print(f"   Success: {success}")

    if output:

        print(
            "   Output:"
        )

        print(
            output
        )

    if error:

        print(
            "   Error:"
        )

        print(
            error
        )

    print("=" * 60)

    # --------------------------------------------------------
    # Главное:
    #
    # НЕ пытаемся отвечать старому HTTP request.
    #
    # Результат отправляется непосредственно браузеру
    # через WebSocket.
    # --------------------------------------------------------

    await send_to_browser(
        host_id,
        message
    )


# ============================================================
# HOST -> SERVER
#
# POWERSHELL STARTED
# ============================================================

async def handle_powershell_started(
    data,
):

    host_id = str(
        data.get(
            "host_id",
            ""
        )
    ).strip()

    if not host_id:

        return

    pid = data.get(
        "pid"
    )

    powershell_state[
        host_id
    ] = {

        "running":
            True,

        "pid":
            pid,
    }

    print()
    print(
        "🟢 PowerShell process started"
    )

    print(
        f"   Host: {host_id}"
    )

    print(
        f"   PID: {pid}"
    )

    await send_to_browser(
        host_id,
        {
            "type":
                "powershell_started",

            "host_id":
                host_id,

            "running":
                True,

            "pid":
                pid,

            "timestamp":
                data.get(
                    "timestamp"
                ),
        }
    )


# ============================================================
# HOST -> SERVER
#
# POWERSHELL FINISHED
# ============================================================

async def handle_powershell_finished(
    data,
):

    host_id = str(
        data.get(
            "host_id",
            ""
        )
    ).strip()

    if not host_id:

        return

    exit_code = data.get(
        "exit_code"
    )

    powershell_state[
        host_id
    ] = {

        "running":
            False,

        "pid":
            None,
    }

    print()
    print(
        "🔴 PowerShell process finished"
    )

    print(
        f"   Host: {host_id}"
    )

    print(
        f"   Exit code: {exit_code}"
    )

    await send_to_browser(
        host_id,
        {
            "type":
                "powershell_finished",

            "host_id":
                host_id,

            "running":
                False,

            "exit_code":
                exit_code,

            "timestamp":
                data.get(
                    "timestamp"
                ),
        }
    )


# ============================================================
# START POWERSHELL
# ============================================================

@router.post(
    "/start/{host_id}"
)
async def powershell_start(
    host_id: str,
    request: Request,
):

    from app import connected_hosts

    host_id = str(
        host_id
    ).strip()

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

    websocket = host.get(
        "websocket"
    )

    if websocket is None:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    "Host WebSocket unavailable",

                "host_id":
                    host_id,
            },

            status_code=500,
        )

    try:

        await websocket.send_text(

            json.dumps(
                {
                    "command":
                        "powershell_start"
                },
                ensure_ascii=False,
            )
        )

        print()
        print(
            "💻 PowerShell START command sent"
        )

        print(
            f"   Host: {host_id}"
        )

        return {

            "success":
                True,

            "host_id":
                host_id,

            "command":
                "powershell_start",
        }

    except Exception as e:

        print()
        print(
            "❌ PowerShell START error"
        )

        print(
            f"   Host: {host_id}"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    str(e),

                "host_id":
                    host_id,
            },

            status_code=500,
        )


# ============================================================
# EXECUTE POWERSHELL COMMAND
#
# ВАЖНО:
#
# HTTP НЕ ЖДЁТ РЕЗУЛЬТАТ.
#
# HTTP response означает только:
#
# "Команда успешно отправлена host.py"
#
# Реальный результат придёт через:
#
# WebSocket
#
# powershell_result
#
# ============================================================

@router.post(
    "/execute/{host_id}"
)
async def powershell_execute(
    host_id: str,
    request: Request,
):

    from app import connected_hosts

    host_id = str(
        host_id
    ).strip()

    # --------------------------------------------------------
    # JSON
    # --------------------------------------------------------

    try:

        data = await request.json()

    except Exception:

        data = {}

    command = data.get(
        "command",
        ""
    )

    if not isinstance(
        command,
        str
    ):

        command = str(
            command
        )

    command = command.strip()

    # --------------------------------------------------------
    # EMPTY COMMAND
    # --------------------------------------------------------

    if not command:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    "PowerShell command is empty",

                "host_id":
                    host_id,
            },

            status_code=400,
        )

    # --------------------------------------------------------
    # HOST
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

    websocket = host.get(
        "websocket"
    )

    if websocket is None:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    "Host WebSocket unavailable",

                "host_id":
                    host_id,
            },

            status_code=500,
        )

    # --------------------------------------------------------
    # SEND COMMAND TO HOST
    # --------------------------------------------------------

    try:

        message = {

            "command":
                "powershell_execute",

            "data": {

                "command":
                    command,

            },

        }

        await websocket.send_text(

            json.dumps(
                message,
                ensure_ascii=False,
            )

        )

        print()
        print("=" * 60)
        print(
            "💻 PowerShell EXECUTE command sent"
        )
        print(
            f"   Host: {host_id}"
        )
        print(
            f"   Command: {command}"
        )
        print("=" * 60)

        # ----------------------------------------------------
        # НЕ ЖДЁМ RESULT
        # ----------------------------------------------------

        return {

            "success":
                True,

            "accepted":
                True,

            "host_id":
                host_id,

            "command":
                command,

            "message":
                "Command sent to host",

        }

    except Exception as e:

        print()
        print(
            "❌ PowerShell EXECUTE error"
        )

        print(
            f"   Host: {host_id}"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    str(e),

                "host_id":
                    host_id,
            },

            status_code=500,
        )


# ============================================================
# STOP CURRENT COMMAND
# ============================================================

@router.post(
    "/stop-command/{host_id}"
)
async def powershell_stop_command(
    host_id: str,
    request: Request,
):

    from app import connected_hosts

    host_id = str(
        host_id
    ).strip()

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

    websocket = host.get(
        "websocket"
    )

    if websocket is None:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    "Host WebSocket unavailable",

                "host_id":
                    host_id,
            },

            status_code=500,
        )

    try:

        await websocket.send_text(

            json.dumps(
                {
                    "command":
                        "powershell_stop_command"
                },
                ensure_ascii=False,
            )
        )

        print()
        print(
            "⏹ PowerShell STOP COMMAND sent"
        )

        print(
            f"   Host: {host_id}"
        )

        return {

            "success":
                True,

            "host_id":
                host_id,

            "command":
                "powershell_stop_command",

        }

    except Exception as e:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    str(e),

                "host_id":
                    host_id,
            },

            status_code=500,
        )


# ============================================================
# STOP POWERSHELL COMPLETELY
# ============================================================

@router.post(
    "/stop/{host_id}"
)
async def powershell_stop(
    host_id: str,
    request: Request,
):

    from app import connected_hosts

    host_id = str(
        host_id
    ).strip()

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

    websocket = host.get(
        "websocket"
    )

    if websocket is None:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    "Host WebSocket unavailable",

                "host_id":
                    host_id,
            },

            status_code=500,
        )

    try:

        await websocket.send_text(

            json.dumps(
                {
                    "command":
                        "powershell_stop"
                },
                ensure_ascii=False,
            )
        )

        print()
        print(
            "⏹ PowerShell STOP command sent"
        )

        print(
            f"   Host: {host_id}"
        )

        return {

            "success":
                True,

            "host_id":
                host_id,

            "command":
                "powershell_stop",

        }

    except Exception as e:

        return JSONResponse(

            {
                "success":
                    False,

                "error":
                    str(e),

                "host_id":
                    host_id,
            },

            status_code=500,
        )


# ============================================================
# STATUS
# ============================================================

@router.get(
    "/status/{host_id}"
)
async def powershell_status(
    host_id: str,
):

    host_id = str(
        host_id
    ).strip()

    state = powershell_state.get(
        host_id,
        {}
    )

    return {

        "success":
            True,

        "host_id":
            host_id,

        "running":
            state.get(
                "running",
                False
            ),

        "pid":
            state.get(
                "pid"
            ),

    }
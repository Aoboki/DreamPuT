
import asyncio
import json
import os
import platform
import socket
import getpass
import shutil
import time
import subprocess
import sys
from datetime import datetime

# ============================================================
# FIND CAMERA AND MICROPHONE
# ============================================================

print("=" * 60)
print("🎥🎤 DETECTING CAMERA AND MICROPHONE")
print("=" * 60)

try:
    if getattr(sys, "frozen", False):
        # Inside one-file exe: import module directly
        import find_audio_camera as _fac
        if hasattr(_fac, "main"):
            _fac.main()
        print()
        print("✅ Camera and microphone detection completed")
    else:
        find_devices_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "find_audio_camera.py",
        )
        subprocess.run(
            [sys.executable, find_devices_script],
            check=True,
        )
        print()
        print("✅ Camera and microphone detection completed")

except subprocess.CalledProcessError as e:

    print()
    print("❌ find_audio_camera.py failed")
    print(f"   Exit code: {e.returncode}")

except Exception as e:

    print()
    print(f"❌ Error running find_audio_camera.py: {e}")


print()


# ============================================================
# IMPORT MAIN MODULES
# ============================================================



import psutil
import websockets

import PowerShellPC


# ============================================================
# PATHS / FROZEN (PyInstaller)
# ============================================================

def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """File next to exe/script, or inside PyInstaller bundle."""
    name = os.path.join(*parts) if parts else ""
    candidates = [
        os.path.join(app_dir(), name),
    ]
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, name))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[0]


def hide_console_window():
    """Hide the black console window on Windows (tray-only mode)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


# Tray state
_tray_icon = None
_tray_stop = False


def _load_tray_image():
    path = resource_path("PIT.png")
    try:
        from PIL import Image
        img = Image.open(path)
        # tray icons look better ~64px
        img = img.convert("RGBA")
        img.thumbnail((64, 64))
        return img
    except Exception as e:
        print(f"⚠️ PIT.png tray icon: {e}")
        try:
            from PIL import Image
            img = Image.new("RGBA", (64, 64), (30, 120, 220, 255))
            return img
        except Exception:
            return None


def start_system_tray():
    """Show PIT.png in the Windows notification area (near the clock)."""
    global _tray_icon
    try:
        import pystray
        from pystray import MenuItem as item
    except Exception as e:
        print(f"⚠️ pystray not available: {e}")
        print("   pip install pystray pillow")
        return None

    image = _load_tray_image()
    if image is None:
        return None

    def on_show_logs(icon, menu_item):
        # Re-show console if hidden
        if os.name == "nt":
            try:
                import ctypes
                hwnd = ctypes.windll.kernel32.GetConsoleWindow()
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
            except Exception:
                pass

    def on_quit(icon, menu_item):
        global _tray_stop
        _tray_stop = True
        try:
            icon.stop()
        except Exception:
            pass
        # Force exit whole process (stops asyncio loop)
        try:
            cleanup()
        except Exception:
            pass
        os._exit(0)

    menu = pystray.Menu(
        item(f"Host: {socket.gethostname()}", None, enabled=False),
        item("Show console", on_show_logs),
        item("Exit", on_quit),
    )

    icon = pystray.Icon(
        "RemoteDesktopHost",
        image,
        f"Remote Desktop — {socket.gethostname()}",
        menu,
    )
    _tray_icon = icon

    # Non-blocking tray on Windows
    try:
        icon.run_detached()
        print("🟢 System tray icon started (PIT.png)")
    except Exception:
        import threading
        threading.Thread(target=icon.run, daemon=True).start()
        print("🟢 System tray icon started (thread)")

    return icon


def spawn_worker(script_filename, *extra_args):
    """
    Start Monitor / Webcam / ControlStream as a child process.
    Supports normal Python and frozen .exe builds.
    """
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    if getattr(sys, "frozen", False):
        # Same exe with --worker=...
        key = {
            "Monitor.py": "monitor",
            "webcam36.py": "webcam",
            "ControlStream.py": "control",
        }.get(script_filename, script_filename)
        cmd = [sys.executable, f"--worker={key}", *extra_args]
        cwd = app_dir()
    else:
        script = os.path.join(app_dir(), script_filename)
        cmd = [sys.executable, script, *extra_args]
        cwd = app_dir()

    return subprocess.Popen(
        cmd,
        cwd=cwd,
        creationflags=creationflags,
    )



# ============================================================
# CONFIG
# ============================================================

SERVER_URL = "wss://remote.aoboki.pp.ua/ws/host"

HEARTBEAT_INTERVAL = 10

RECONNECT_DELAY = 5

HOST_INFO_INTERVAL = 27

POWERSHELL_OUTPUT_INTERVAL = 0.05


# ============================================================
# HOST ID
# ============================================================

HOST_ID = (
    sys.argv[1]
    if len(sys.argv) > 1
    else socket.gethostname().lower()
)


# ============================================================
# MONITOR PROCESS
# ============================================================

MONITOR_PROCESS = None

MONITOR_FILE = os.path.join(app_dir(), "Monitor.py")


# ============================================================
# WEBCAM PROCESS
# ============================================================

WEBCAM_PROCESS = None

WEBCAM_FILE = os.path.join(app_dir(), "webcam36.py")


# ============================================================
# CONTROL STREAM PROCESS (WebRTC desktop)
# ============================================================

CONTROL_PROCESS = None

CONTROL_FILE = os.path.join(app_dir(), "ControlStream.py")


# ============================================================
# MONITOR STATUS
# ============================================================

def is_monitor_running():

    global MONITOR_PROCESS

    if MONITOR_PROCESS is None:
        return False

    try:

        if MONITOR_PROCESS.poll() is None:
            return True

    except Exception:
        pass

    MONITOR_PROCESS = None

    return False


# ============================================================
# START MONITOR
# ============================================================

def start_monitor():

    global MONITOR_PROCESS

    print()
    print("🖥 Monitor START requested")

    if is_monitor_running():

        print("🟢 Monitor.py is already running")

        print(
            f"   PID: {MONITOR_PROCESS.pid}"
        )

        return True

    print()
    print("📁 Monitor file:")

    print(
        f"   {MONITOR_FILE}"
    )

    if not getattr(sys, "frozen", False) and not os.path.isfile(MONITOR_FILE):

        print()
        print("❌ Monitor.py NOT FOUND")

        print(
            f"   Path: {MONITOR_FILE}"
        )

        return False

    try:

        print()
        print("▶️ Starting Monitor.py...")

        print(
            f"   Python: {sys.executable}"
        )

        print(
            f"   HOST_ID: {HOST_ID}"
        )

        creationflags = 0

        if os.name == "nt":

            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
            )

        MONITOR_PROCESS = spawn_worker(
            "Monitor.py",
            HOST_ID,
        )

        print()
        print("🟢 Monitor.py STARTED")

        print(
            f"   PID: {MONITOR_PROCESS.pid}"
        )

        time.sleep(0.5)

        if MONITOR_PROCESS.poll() is not None:

            print()
            print(
                "❌ Monitor.py exited immediately"
            )

            print(
                f"   Exit code: "
                f"{MONITOR_PROCESS.returncode}"
            )

            MONITOR_PROCESS = None

            return False

        return True

    except Exception as e:

        print()
        print(
            "❌ Failed to start Monitor.py"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        MONITOR_PROCESS = None

        return False


# ============================================================
# STOP MONITOR
# ============================================================

def stop_monitor():

    global MONITOR_PROCESS

    print()
    print("🖥 Monitor STOP requested")

    if MONITOR_PROCESS is None:

        print(
            "⏹ Monitor.py is not running"
        )

        return True

    try:

        if MONITOR_PROCESS.poll() is not None:

            print(
                "⏹ Monitor.py already stopped"
            )

            MONITOR_PROCESS = None

            return True

        print(
            f"⏹ Stopping Monitor.py "
            f"(PID {MONITOR_PROCESS.pid})..."
        )

        MONITOR_PROCESS.terminate()

        try:

            MONITOR_PROCESS.wait(
                timeout=5
            )

        except subprocess.TimeoutExpired:

            print(
                "⚠️ Monitor.py did not stop"
            )

            print(
                "   Killing process..."
            )

            MONITOR_PROCESS.kill()

            MONITOR_PROCESS.wait(
                timeout=3
            )

        print(
            "🔴 Monitor.py stopped"
        )

        MONITOR_PROCESS = None

        return True

    except Exception as e:

        print()
        print(
            "❌ Failed to stop Monitor.py"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        MONITOR_PROCESS = None

        return False


# ============================================================
# WEBCAM STATUS
# ============================================================

def is_webcam_running():

    global WEBCAM_PROCESS

    if WEBCAM_PROCESS is None:
        return False

    try:

        if WEBCAM_PROCESS.poll() is None:
            return True

    except Exception:
        pass

    WEBCAM_PROCESS = None

    return False


# ============================================================
# START WEBCAM
# ============================================================

def start_webcam():

    global WEBCAM_PROCESS

    print()
    print("📷 Webcam START requested")

    if is_webcam_running():

        print(
            "🟢 webcam.py is already running"
        )

        print(
            f"   PID: {WEBCAM_PROCESS.pid}"
        )

        return True

    print()
    print("📁 Webcam file:")

    print(
        f"   {WEBCAM_FILE}"
    )

    if not getattr(sys, "frozen", False) and not os.path.isfile(WEBCAM_FILE):

        print()
        print("❌ webcam.py NOT FOUND")

        print(
            f"   Path: {WEBCAM_FILE}"
        )

        return False

    try:

        print()
        print("▶️ Starting webcam.py...")

        print(
            f"   Python: {sys.executable}"
        )

        print(
            f"   HOST_ID: {HOST_ID}"
        )

        creationflags = 0

        if os.name == "nt":

            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP
            )

        WEBCAM_PROCESS = spawn_worker(
            "webcam36.py",
            HOST_ID,
        )

        print()
        print("🟢 webcam.py STARTED")

        print(
            f"   PID: {WEBCAM_PROCESS.pid}"
        )

        time.sleep(0.5)

        if WEBCAM_PROCESS.poll() is not None:

            print()
            print(
                "❌ webcam.py exited immediately"
            )

            print(
                f"   Exit code: "
                f"{WEBCAM_PROCESS.returncode}"
            )

            WEBCAM_PROCESS = None

            return False

        return True

    except Exception as e:

        print()
        print(
            "❌ Failed to start webcam.py"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        WEBCAM_PROCESS = None

        return False


# ============================================================
# STOP WEBCAM
# ============================================================

def stop_webcam():

    global WEBCAM_PROCESS

    print()
    print("📷 Webcam STOP requested")

    if WEBCAM_PROCESS is None:

        print(
            "⏹ webcam.py is not running"
        )

        return True

    try:

        if WEBCAM_PROCESS.poll() is not None:

            print(
                "⏹ webcam.py already stopped"
            )

            WEBCAM_PROCESS = None

            return True

        print(
            f"⏹ Stopping webcam.py "
            f"(PID {WEBCAM_PROCESS.pid})..."
        )

        WEBCAM_PROCESS.terminate()

        try:

            WEBCAM_PROCESS.wait(
                timeout=5
            )

        except subprocess.TimeoutExpired:

            print(
                "⚠️ webcam.py did not stop"
            )

            print(
                "   Killing process..."
            )

            WEBCAM_PROCESS.kill()

            WEBCAM_PROCESS.wait(
                timeout=3
            )

        print(
            "🔴 webcam.py stopped"
        )

        WEBCAM_PROCESS = None

        return True

    except Exception as e:

        print()
        print(
            "❌ Failed to stop webcam.py"
        )

        print(
            f"   {type(e).__name__}: {e}"
        )

        WEBCAM_PROCESS = None

        return False


# ============================================================
# WINDOWS BOOT TIME
# ============================================================

def get_boot_time():

    try:

        return psutil.boot_time()

    except Exception:

        return time.time()


def get_boot_datetime():

    try:

        return datetime.fromtimestamp(
            get_boot_time()
        ).isoformat()

    except Exception:

        return None


def get_uptime_seconds():

    try:

        return max(
            0,
            int(
                time.time()
                - get_boot_time()
            )
        )

    except Exception:

        return 0


def format_uptime(seconds):

    seconds = int(seconds)

    days = seconds // 86400

    hours = (
        seconds % 86400
    ) // 3600

    minutes = (
        seconds % 3600
    ) // 60

    secs = (
        seconds % 60
    )

    return (
        f"{days}d "
        f"{hours}h "
        f"{minutes}m "
        f"{secs}s"
    )


# ============================================================
# CPU TEMPERATURE
# ============================================================

def get_cpu_temperature():

    try:

        temperatures = (
            psutil.sensors_temperatures()
        )

        if not temperatures:
            return None

        for entries in temperatures.values():

            for entry in entries:

                if entry.current is not None:

                    return round(
                        entry.current,
                        1
                    )

    except Exception:

        pass

    return None


# ============================================================
# DISK
# ============================================================

def get_disk_info():

    try:

        system_drive = os.environ.get(
            "SystemDrive",
            "C:"
        )

        disk = shutil.disk_usage(
            system_drive
        )

        return {

            "total_gb":
                round(
                    disk.total /
                    (1024 ** 3),
                    1
                ),

            "used_gb":
                round(
                    disk.used /
                    (1024 ** 3),
                    1
                ),

            "free_gb":
                round(
                    disk.free /
                    (1024 ** 3),
                    1
                ),

            "percent":
                round(
                    (
                        disk.used /
                        disk.total
                    ) * 100,
                    1
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
# MEMORY
# ============================================================

def get_memory_info():

    try:

        memory = (
            psutil.virtual_memory()
        )

        return {

            "total_gb":
                round(
                    memory.total /
                    (1024 ** 3),
                    1
                ),

            "used_gb":
                round(
                    memory.used /
                    (1024 ** 3),
                    1
                ),

            "free_gb":
                round(
                    memory.available /
                    (1024 ** 3),
                    1
                ),

            "percent":
                round(
                    memory.percent,
                    1
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
# SYSTEM INFORMATION
# ============================================================

def get_system_info():

    cpu_percent = psutil.cpu_percent(
        interval=0.5
    )

    memory = get_memory_info()

    disk = get_disk_info()

    boot_time = get_boot_time()

    boot_datetime = get_boot_datetime()

    uptime_seconds = get_uptime_seconds()

    uptime_text = format_uptime(
        uptime_seconds
    )

    computer_name = (
        socket.gethostname()
    )

    username = (
        getpass.getuser()
    )

    info = {

        "type":
            "host_info",

        "host_id":
            HOST_ID,

        "name":
            computer_name,

        "computer_name":
            computer_name,

        "username":
            username,

        "os":
            platform.system(),

        "os_version":
            platform.version(),

        "os_release":
            platform.release(),

        "architecture":
            platform.machine(),

        "python_version":
            platform.python_version(),

        "cpu":
            platform.processor(),

        "cpu_count":
            psutil.cpu_count(
                logical=True
            ),

        "cpu_percent":
            cpu_percent,

        "cpu_temperature":
            get_cpu_temperature(),

        "memory":
            memory,

        "disk":
            disk,

        "windows_boot_time":
            boot_datetime,

        "windows_uptime":
            uptime_text,

        "uptime_seconds":
            uptime_seconds,

        "boot_time":
            boot_time,

        "monitor_running":
            is_monitor_running(),

        "webcam_running":
            is_webcam_running(),

        "powershell_running":
            PowerShellPC.is_running(),

        "timestamp":
            time.time(),

    }

    return info


# ============================================================
# SEND HOST INFO
# ============================================================

async def send_host_info(websocket):

    info = get_system_info()

    await websocket.send(
        json.dumps(
            info,
            ensure_ascii=False
        )
    )

    print()
    print(
        "📡 Host information sent"
    )

    print(
        f"   🆔 Host ID: "
        f"{info['host_id']}"
    )

    print(
        f"   👤 User: "
        f"{info['username']}"
    )

    print(
        f"   💻 Computer: "
        f"{info['computer_name']}"
    )

    print(
        f"   🪟 OS: "
        f"{info['os']} "
        f"{info['os_release']}"
    )

    print(
        f"   🐍 Python: "
        f"{info['python_version']}"
    )

    print(
        f"   🧠 CPU: "
        f"{info['cpu_percent']}%"
    )

    if (
        info["memory"]["percent"]
        is not None
    ):

        print(
            f"   💾 RAM: "
            f"{info['memory']['percent']}%"
        )

    if (
        info["disk"]["free_gb"]
        is not None
    ):

        print(
            f"   💿 Disk free: "
            f"{info['disk']['free_gb']} GB"
        )

    if (
        info["cpu_temperature"]
        is not None
    ):

        print(
            f"   🌡 CPU: "
            f"{info['cpu_temperature']} °C"
        )

    print(
        f"   ⏱ Windows uptime: "
        f"{info['windows_uptime']}"
    )

    print(
        f"   🕐 Windows boot: "
        f"{info['windows_boot_time']}"
    )

    print(
        f"   🖥 Monitor: "
        f"{'ON' if info['monitor_running'] else 'OFF'}"
    )

    print(
        f"   📷 Webcam: "
        f"{'ON' if info['webcam_running'] else 'OFF'}"
    )

    print(
        f"   💻 PowerShell: "
        f"{'ON' if info['powershell_running'] else 'OFF'}"
    )

    print()


# ============================================================
# HOST INFO LOOP
# ============================================================

async def host_info_loop(websocket):

    while True:

        try:

            await asyncio.sleep(
                HOST_INFO_INTERVAL
            )

            await send_host_info(
                websocket
            )

        except Exception as e:

            print()
            print(
                "❌ Host info update error:"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )

            return


# ============================================================
# HEARTBEAT
# ============================================================

async def heartbeat_loop(websocket):

    while True:

        try:

            await asyncio.sleep(
                HEARTBEAT_INTERVAL
            )

            await websocket.send(
                json.dumps({

                    "type":
                        "heartbeat",

                    "host_id":
                        HOST_ID,

                    "timestamp":
                        time.time(),

                })
            )

            print(
                "💓 Heartbeat"
            )

        except Exception:

            return


# ============================================================
# POWERSHELL OUTPUT LOOP
#
# PowerShellPC.py reader thread
#             ↓
#       output_queue
#             ↓
#       this async loop
#             ↓
#        WebSocket
#             ↓
#          server
# ============================================================

async def powershell_output_loop(websocket):

    print()
    print(
        "📡 PowerShell output loop started"
    )

    while True:

        try:

            items = PowerShellPC.get_output()

            if items:

                for item in items:

                    if not isinstance(
                        item,
                        dict
                    ):
                        continue

                    item_type = item.get(
                        "type"
                    )

                    # ----------------------------------------
                    # STDOUT
                    # ----------------------------------------

                    if item_type == "stdout":

                        output = item.get(
                            "output",
                            ""
                        )

                        if output is None:
                            output = ""

                        await websocket.send(
                            json.dumps({

                                "type":
                                    "powershell_output",

                                "host_id":
                                    HOST_ID,

                                "stream":
                                    "stdout",

                                "output":
                                    str(output),

                                "timestamp":
                                    time.time(),

                            },
                            ensure_ascii=False)
                        )

                    # ----------------------------------------
                    # SYSTEM MESSAGE
                    # ----------------------------------------

                    elif item_type == "system":

                        output = item.get(
                            "output",
                            ""
                        )

                        await websocket.send(
                            json.dumps({

                                "type":
                                    "powershell_output",

                                "host_id":
                                    HOST_ID,

                                "stream":
                                    "system",

                                "output":
                                    str(output),

                                "timestamp":
                                    time.time(),

                            },
                            ensure_ascii=False)
                        )

                    # ----------------------------------------
                    # FINISHED
                    # ----------------------------------------

                    elif item_type == "finished":

                        exit_code = item.get(
                            "exit_code"
                        )

                        await websocket.send(
                            json.dumps({

                                "type":
                                    "powershell_finished",

                                "host_id":
                                    HOST_ID,

                                "exit_code":
                                    exit_code,

                                "timestamp":
                                    time.time(),

                            },
                            ensure_ascii=False)
                        )

                        print()
                        print(
                            "🔴 PowerShell finished"
                        )

                        print(
                            f"   Exit code: "
                            f"{exit_code}"
                        )

            await asyncio.sleep(
                POWERSHELL_OUTPUT_INTERVAL
            )

        except asyncio.CancelledError:

            print()
            print(
                "⏹ PowerShell output loop stopped"
            )

            raise

        except Exception as e:

            print()
            print(
                "❌ PowerShell output loop error"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )

            await asyncio.sleep(
                0.5
            )



# ============================================================

def is_control_running():
    global CONTROL_PROCESS
    if CONTROL_PROCESS is None:
        return False
    try:
        if CONTROL_PROCESS.poll() is None:
            return True
    except Exception:
        pass
    CONTROL_PROCESS = None
    return False


def start_control():
    global CONTROL_PROCESS
    print()
    print("🎮 ControlStream START requested")
    if is_control_running():
        print(f"🟢 already running PID={CONTROL_PROCESS.pid}")
        return True
    if not getattr(sys, "frozen", False) and not os.path.isfile(CONTROL_FILE):
        print(f"❌ ControlStream.py NOT FOUND: {CONTROL_FILE}")
        return False
    try:
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        CONTROL_PROCESS = spawn_worker(
            "ControlStream.py",
            HOST_ID,
        )
        time.sleep(0.8)
        if CONTROL_PROCESS.poll() is not None:
            print(f"❌ ControlStream exited: {CONTROL_PROCESS.returncode}")
            CONTROL_PROCESS = None
            return False
        print(f"🟢 ControlStream STARTED PID={CONTROL_PROCESS.pid}")
        return True
    except Exception as e:
        print(f"❌ start_control failed: {e}")
        CONTROL_PROCESS = None
        return False


def stop_control():
    global CONTROL_PROCESS
    print()
    print("🎮 ControlStream STOP requested")
    if CONTROL_PROCESS is None:
        return True
    try:
        if CONTROL_PROCESS.poll() is not None:
            CONTROL_PROCESS = None
            return True
        CONTROL_PROCESS.terminate()
        try:
            CONTROL_PROCESS.wait(timeout=5)
        except subprocess.TimeoutExpired:
            CONTROL_PROCESS.kill()
            CONTROL_PROCESS.wait(timeout=3)
        CONTROL_PROCESS = None
        print("🔴 ControlStream stopped")
        return True
    except Exception as e:
        print(f"❌ stop_control failed: {e}")
        CONTROL_PROCESS = None
        return True


# REMOTE INPUT (mouse / keyboard)
# Uses Windows API via ctypes — no extra packages required.
# pynput is optional and used only if already installed.
# ============================================================

import ctypes
from ctypes import wintypes

# ---- Win32 constants ----
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
WHEEL_DELTA = 120

user32 = ctypes.windll.user32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _move_mouse_abs(x, y):
    sw, sh = _screen_size()
    if sw <= 1 or sh <= 1:
        return
    x = max(0, min(int(x), sw - 1))
    y = max(0, min(int(y), sh - 1))
    # absolute coords are 0..65535
    ax = int(x * 65535 / (sw - 1))
    ay = int(y * 65535 / (sh - 1))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(
        ax, ay, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, 0, None
    )
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _mouse_button(button, down):
    button = (button or "left").lower()
    if button == "right":
        flag = MOUSEEVENTF_RIGHTDOWN if down else MOUSEEVENTF_RIGHTUP
    elif button == "middle":
        flag = MOUSEEVENTF_MIDDLEDOWN if down else MOUSEEVENTF_MIDDLEUP
    else:
        flag = MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(0, 0, 0, flag, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _mouse_wheel(delta_x, delta_y):
    # vertical
    if delta_y:
        steps = int(-delta_y / 100)
        if steps:
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.union.mi = MOUSEINPUT(
                0, 0, steps * WHEEL_DELTA, MOUSEEVENTF_WHEEL, 0, None
            )
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    # horizontal
    if delta_x:
        steps = int(delta_x / 100)
        if steps:
            inp = INPUT()
            inp.type = INPUT_MOUSE
            inp.union.mi = MOUSEINPUT(
                0, 0, steps * WHEEL_DELTA, MOUSEEVENTF_HWHEEL, 0, None
            )
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# Virtual-key map (browser key/code → VK)
_VK = {
    "Enter": 0x0D,
    "Escape": 0x1B,
    "Tab": 0x09,
    "Backspace": 0x08,
    "Delete": 0x2E,
    "Insert": 0x2D,
    "Home": 0x24,
    "End": 0x23,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "ArrowUp": 0x26,
    "ArrowDown": 0x28,
    "ArrowLeft": 0x25,
    "ArrowRight": 0x27,
    " ": 0x20,
    "Space": 0x20,
    "Shift": 0x10,
    "Control": 0x11,
    "Alt": 0x12,
    "Meta": 0x5B,
    "CapsLock": 0x14,
    "PrintScreen": 0x2C,
    "ScrollLock": 0x91,
    "Pause": 0x13,
    "NumLock": 0x90,
    "ContextMenu": 0x5D,
}


def _key_to_vk(key, code):
    if key in _VK:
        return _VK[key]

    if key and key.startswith("F") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)

    if key and len(key) == 1:
        ch = key.upper()
        # letters / digits
        vk = user32.VkKeyScanW(ord(ch))
        if vk != -1:
            return vk & 0xFF
        return ord(ch)

    if code:
        if code.startswith("Key") and len(code) == 4:
            return ord(code[-1].upper())
        if code.startswith("Digit") and len(code) == 6:
            return ord(code[-1])
        if code.startswith("Numpad") and code[-1].isdigit():
            return 0x60 + int(code[-1])

    return None


_EXTENDED = {
    0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27, 0x5B, 0x5D,
}


def _key_event(vk, down):
    if vk is None:
        return
    flags = 0 if down else KEYEVENTF_KEYUP
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(vk, 0, flags, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def handle_remote_input(data):
    action = data.get("action")

    try:
        if action == "mouse_move":
            x = data.get("x")
            y = data.get("y")
            if x is not None and y is not None:
                _move_mouse_abs(x, y)
            return True

        if action == "mouse_down":
            x = data.get("x")
            y = data.get("y")
            if x is not None and y is not None:
                _move_mouse_abs(x, y)
            _mouse_button(data.get("button"), True)
            return True

        if action == "mouse_up":
            x = data.get("x")
            y = data.get("y")
            if x is not None and y is not None:
                _move_mouse_abs(x, y)
            _mouse_button(data.get("button"), False)
            return True

        if action == "mouse_wheel":
            _mouse_wheel(data.get("deltaX") or 0, data.get("deltaY") or 0)
            return True

        if action == "key_down":
            vk = _key_to_vk(data.get("key"), data.get("code"))
            _key_event(vk, True)
            return True

        if action == "key_up":
            vk = _key_to_vk(data.get("key"), data.get("code"))
            _key_event(vk, False)
            return True

        print(f"⚠️ Unknown input action: {action}")
        return False

    except Exception as e:
        print(f"❌ Input error ({action}): {type(e).__name__}: {e}")
        return False


# ============================================================
# COMMAND HANDLER
# ============================================================


# ============================================================
# FILE MANAGER HELPERS
# ============================================================

def _files_safe_path(path: str) -> str:
    if not path or not str(path).strip():
        return "C:\\"
    return os.path.abspath(str(path).strip())


def _files_list(path: str):
    path = _files_safe_path(path)
    if not os.path.exists(path):
        return {"ok": False, "error": "Path not found", "path": path, "items": []}
    if not os.path.isdir(path):
        return {"ok": False, "error": "Not a directory", "path": path, "items": []}

    items = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                    is_dir = entry.is_dir(follow_symlinks=False)
                    items.append({
                        "name": entry.name,
                        "is_dir": is_dir,
                        "size": 0 if is_dir else int(st.st_size),
                        "mtime": int(st.st_mtime),
                    })
                except Exception:
                    items.append({
                        "name": entry.name,
                        "is_dir": False,
                        "size": 0,
                        "mtime": 0,
                    })
    except Exception as e:
        return {"ok": False, "error": str(e), "path": path, "items": []}

    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    parent = os.path.dirname(path.rstrip("\\/"))
    drive, tail = os.path.splitdrive(path)
    if tail in ("\\", "/", ""):
        parent = path
    return {
        "ok": True,
        "path": path,
        "parent": parent,
        "items": items,
    }


def _files_drives():
    drives = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{letter}:\\"
            if os.path.exists(root):
                drives.append(root)
    else:
        drives.append("/")
    return {"ok": True, "drives": drives}


async def handle_files_command(websocket, data):
    import base64
    command = data.get("command")
    request_id = data.get("request_id")
    result = {"ok": False, "error": "unknown", "request_id": request_id}

    try:
        if command == "files_drives":
            result = _files_drives()

        elif command == "files_list":
            result = _files_list(data.get("path") or "C:\\")

        elif command == "files_mkdir":
            path = _files_safe_path(data.get("path") or "")
            os.makedirs(path, exist_ok=True)
            result = {"ok": True, "path": path}

        elif command == "files_delete":
            path = _files_safe_path(data.get("path") or "")
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.remove(path)
            else:
                result = {"ok": False, "error": "Not found", "path": path}
                result["request_id"] = request_id
                await websocket.send(json.dumps({"type": "files_result", **result}, ensure_ascii=False))
                return
            result = {"ok": True, "path": path}

        elif command == "files_rename":
            src = _files_safe_path(data.get("path") or "")
            dst = _files_safe_path(data.get("new_path") or "")
            os.rename(src, dst)
            result = {"ok": True, "path": dst}

        elif command == "files_download":
            path = _files_safe_path(data.get("path") or "")
            if not os.path.isfile(path):
                result = {"ok": False, "error": "Not a file", "path": path}
            else:
                size = os.path.getsize(path)
                max_bytes = 250 * 1024 * 1024
                if size > max_bytes:
                    result = {
                        "ok": False,
                        "error": f"File too large ({size} bytes). Max 250 MB",
                        "path": path,
                        "size": size,
                    }
                else:
                    with open(path, "rb") as f:
                        raw = f.read()
                    result = {
                        "ok": True,
                        "path": path,
                        "name": os.path.basename(path),
                        "size": size,
                        "data_b64": base64.b64encode(raw).decode("ascii"),
                    }

        elif command == "files_upload":
            path = _files_safe_path(data.get("path") or "")
            b64 = data.get("data_b64") or ""
            raw = base64.b64decode(b64)
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
            result = {"ok": True, "path": path, "size": len(raw)}

        elif command == "files_copy":
            src = _files_safe_path(data.get("path") or "")
            dst = _files_safe_path(data.get("new_path") or "")
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                parent = os.path.dirname(dst)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                shutil.copy2(src, dst)
            result = {"ok": True, "path": dst}

        elif command == "files_move":
            src = _files_safe_path(data.get("path") or "")
            dst = _files_safe_path(data.get("new_path") or "")
            parent = os.path.dirname(dst)
            if parent:
                os.makedirs(parent, exist_ok=True)
            shutil.move(src, dst)
            result = {"ok": True, "path": dst}

        else:
            result = {"ok": False, "error": f"Unknown files command: {command}"}

    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    result["request_id"] = request_id
    result["command"] = command
    await websocket.send(json.dumps({"type": "files_result", **result}, ensure_ascii=False))


async def handle_command(
    websocket,
    data
):

    command = data.get(
        "command"
    )

    # ========================================================
    # REMOTE INPUT (no spam logging)
    # ========================================================

    if command == "input":
        handle_remote_input(data)
        return

    if command == "control_start":
        success = start_control()
        await websocket.send(json.dumps({
            "type": "control_status",
            "host_id": HOST_ID,
            "running": success,
            "status": "running" if success else "error",
        }))
        return

    if command == "control_stop":
        success = stop_control()
        await websocket.send(json.dumps({
            "type": "control_status",
            "host_id": HOST_ID,
            "running": False,
            "status": "stopped",
        }))
        return

    print()
    print("========================================")
    print("📩 COMMAND RECEIVED FROM SERVER")
    print(f"📦 DATA: {data}")
    print(
        f"🔧 COMMAND: "
        f"{data.get('command')}"
    )
    print("========================================")

    # ========================================================
    # MONITOR START
    # ========================================================

    if command == "monitor_start":

        success = start_monitor()

        await websocket.send(
            json.dumps({

                "type":
                    "monitor_status",

                "host_id":
                    HOST_ID,

                "running":
                    success,

                "status":
                    "running"
                    if success
                    else "error",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # MONITOR STOP
    # ========================================================

    if command == "monitor_stop":

        success = stop_monitor()

        await websocket.send(
            json.dumps({

                "type":
                    "monitor_status",

                "host_id":
                    HOST_ID,

                "running":
                    False,

                "status":
                    "stopped"
                    if success
                    else "error",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # MONITOR STATUS
    # ========================================================

    if command == "monitor_status":

        running = is_monitor_running()

        await websocket.send(
            json.dumps({

                "type":
                    "monitor_status",

                "host_id":
                    HOST_ID,

                "running":
                    running,

                "status":
                    "running"
                    if running
                    else "stopped",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # HOST INFO
    # ========================================================

    if command == "host_info":

        await send_host_info(
            websocket
        )

        return

    # ========================================================
    # SCREENSHOT
    # ========================================================

    if command == "screenshot":

        await websocket.send(
            json.dumps({

                "type":
                    "command_status",

                "command":
                    "screenshot",

                "status":
                    "not_implemented",

            })
        )

        return

    # ========================================================
    # STOP SCREENSHOT
    # ========================================================

    if command == "stop_screenshot":

        return

    # ========================================================
    # WEBCAM START
    # ========================================================

    if command == "webcam_start":

        success = start_webcam()

        await websocket.send(
            json.dumps({

                "type":
                    "webcam_status",

                "host_id":
                    HOST_ID,

                "running":
                    success,

                "status":
                    "running"
                    if success
                    else "error",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # WEBCAM STOP
    # ========================================================

    if command == "webcam_stop":

        success = stop_webcam()

        await websocket.send(
            json.dumps({

                "type":
                    "webcam_status",

                "host_id":
                    HOST_ID,

                "running":
                    False,

                "status":
                    "stopped"
                    if success
                    else "error",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # WEBCAM STATUS
    # ========================================================

    if command == "webcam_status":

        running = is_webcam_running()

        await websocket.send(
            json.dumps({

                "type":
                    "webcam_status",

                "host_id":
                    HOST_ID,

                "running":
                    running,

                "status":
                    "running"
                    if running
                    else "stopped",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # POWERSHELL START
    # ========================================================

    if command == "powershell_start":

        print()
        print(
            "💻 PowerShell START requested"
        )

        success = PowerShellPC.start()

        await websocket.send(
            json.dumps({

                "type":
                    "powershell_status",

                "host_id":
                    HOST_ID,

                "running":
                    success,

                "status":
                    "running"
                    if success
                    else "error",

                "timestamp":
                    time.time(),

            })
        )

        print(
            "📤 PowerShell status sent: "
            f"{'running' if success else 'error'}"
        )

        return

    # ========================================================
    # POWERSHELL EXECUTE
    # ========================================================

    if command == "powershell_execute":

        print()
        print(
            "💻 PowerShell command requested"
        )

        ps_data = data.get(
            "data",
            {}
        )

        if isinstance(
            ps_data,
            dict
        ):

            ps_command = ps_data.get(
                "command",
                ""
            )

        else:

            ps_command = ps_data

        if not isinstance(
            ps_command,
            str
        ):

            ps_command = str(
                ps_command
            )

        ps_command = ps_command.strip()

        print(
            f"   Command: {ps_command}"
        )

        if not ps_command:

            await websocket.send(
                json.dumps({

                    "type":
                        "powershell_result",

                    "host_id":
                        HOST_ID,

                    "success":
                        False,

                    "output":
                        "",

                    "error":
                        "PowerShell command is empty",

                    "timestamp":
                        time.time(),

                },
                ensure_ascii=False)
            )

            return

        # ----------------------------------------------------
        # START IF NECESSARY
        # ----------------------------------------------------

        if not PowerShellPC.is_running():

            print(
                "⚠️ PowerShell is not running"
            )

            success = PowerShellPC.start()

            if not success:

                await websocket.send(
                    json.dumps({

                        "type":
                            "powershell_result",

                        "host_id":
                            HOST_ID,

                        "success":
                            False,

                        "output":
                            "",

                        "error":
                            "Failed to start PowerShell",

                        "timestamp":
                            time.time(),

                    },
                    ensure_ascii=False)
                )

                return

        # ----------------------------------------------------
        # EXECUTE
        # ----------------------------------------------------

        result = PowerShellPC.execute(
            ps_command
        )

        print(
            f"   Execute result: {result}"
        )

        # ----------------------------------------------------
        # IMPORTANT
        #
        # We DO NOT wait for command output here.
        #
        # PowerShellPC reader thread places output
        # into queue.
        #
        # powershell_output_loop sends it to server.
        # ----------------------------------------------------

        if not result.get(
            "success",
            False
        ):

            await websocket.send(
                json.dumps({

                    "type":
                        "powershell_result",

                    "host_id":
                        HOST_ID,

                    "success":
                        False,

                    "output":
                        "",

                    "error":
                        result.get(
                            "error",
                            "PowerShell execution failed"
                        ),

                    "command_id":
                        result.get(
                            "command_id"
                        ),

                    "timestamp":
                        time.time(),

                },
                ensure_ascii=False)
            )

        else:

            # ------------------------------------------------
            # ACK
            #
            # This is NOT the command output.
            # It only confirms that PowerShell accepted
            # the command.
            # ------------------------------------------------

            await websocket.send(
                json.dumps({

                    "type":
                        "powershell_result",

                    "host_id":
                        HOST_ID,

                    "success":
                        True,

                    "output":
                        "",

                    "error":
                        "",

                    "command_id":
                        result.get(
                            "command_id"
                        ),

                    "running":
                        True,

                    "timestamp":
                        time.time(),

                },
                ensure_ascii=False)
            )

        return

    # ========================================================
    # POWERSHELL STOP
    # ========================================================

    if command == "powershell_stop":

        print()
        print(
            "💻 PowerShell STOP requested"
        )

        success = PowerShellPC.stop()

        await websocket.send(
            json.dumps({

                "type":
                    "powershell_status",

                "host_id":
                    HOST_ID,

                "running":
                    False,

                "status":
                    "stopped"
                    if success
                    else "error",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # POWERSHELL STATUS
    # ========================================================

    if command == "powershell_status":

        running = PowerShellPC.is_running()

        await websocket.send(
            json.dumps({

                "type":
                    "powershell_status",

                "host_id":
                    HOST_ID,

                "running":
                    running,

                "status":
                    "running"
                    if running
                    else "stopped",

                "timestamp":
                    time.time(),

            })
        )

        return

    # ========================================================
    # FILE MANAGER
    # ========================================================

    if command in (
        "files_list",
        "files_mkdir",
        "files_delete",
        "files_rename",
        "files_download",
        "files_upload",
        "files_drives",
        "files_copy",
        "files_move",
    ):
        await handle_files_command(websocket, data)
        return

    # ========================================================
    # UNKNOWN COMMAND
    # ========================================================

    print()
    print(
        f"⚠️ Unknown server command: {command}"
    )


# ============================================================
# CONNECTION
# ============================================================

async def run_connection():

    print()
    print(
        "🔌 Connecting to server..."
    )

    websocket_url = (
        SERVER_URL
        + "/"
        + HOST_ID
    )

    print(
        f"   {websocket_url}"
    )

    async with websockets.connect(

        websocket_url,

        ping_interval=20,

        ping_timeout=20,

        close_timeout=5,

        max_size=None,

    ) as websocket:

        print()
        print(
            "🟢 Connected to Remote Desktop server"
        )

        print(
            f"   Host ID: {HOST_ID}"
        )

        # ----------------------------------------------------
        # INITIAL HOST INFO
        # ----------------------------------------------------

        await send_host_info(
            websocket
        )

        # ----------------------------------------------------
        # HEARTBEAT
        # ----------------------------------------------------

        heartbeat_task = (
            asyncio.create_task(
                heartbeat_loop(
                    websocket
                )
            )
        )

        # ----------------------------------------------------
        # HOST INFO
        # ----------------------------------------------------

        info_task = (
            asyncio.create_task(
                host_info_loop(
                    websocket
                )
            )
        )

        # ----------------------------------------------------
        # POWERSHELL OUTPUT
        # ----------------------------------------------------

        powershell_output_task = (
            asyncio.create_task(
                powershell_output_loop(
                    websocket
                )
            )
        )

        try:

            while True:

                message = (
                    await websocket.recv()
                )

                # ------------------------------------------------
                # BINARY
                # ------------------------------------------------

                if isinstance(
                    message,
                    bytes
                ):

                    print(
                        "📦 Binary message received: "
                        f"{len(message)} bytes"
                    )

                    continue

                # ------------------------------------------------
                # JSON
                # ------------------------------------------------

                try:

                    data = json.loads(
                        message
                    )

                except json.JSONDecodeError:

                    print()
                    print(
                        "⚠️ Invalid JSON from server"
                    )

                    print(
                        f"   Message: {message}"
                    )

                    continue

                await handle_command(
                    websocket,
                    data
                )

        finally:

            heartbeat_task.cancel()

            info_task.cancel()

            powershell_output_task.cancel()

            await asyncio.gather(

                heartbeat_task,

                info_task,

                powershell_output_task,

                return_exceptions=True,

            )


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print(
        "========================================"
    )

    print(
        "      Remote Desktop Host"
    )

    print(
        "========================================"
    )

    print(
        f"🆔 Host ID: "
        f"{HOST_ID}"
    )

    print(
        f"💻 Computer: "
        f"{socket.gethostname()}"
    )

    print(
        f"👤 User: "
        f"{getpass.getuser()}"
    )

    print(
        f"🐍 Python: "
        f"{platform.python_version()}"
    )

    print(
        f"🌐 Server: "
        f"{SERVER_URL}/{HOST_ID}"
    )

    print(
        f"🖥 Monitor: "
        f"{MONITOR_FILE}"
    )

    print(
        f"📷 Webcam: "
        f"{WEBCAM_FILE}"
    )

    print(
        "========================================"
    )

    boot_datetime = (
        get_boot_datetime()
    )

    uptime = (
        get_uptime_seconds()
    )

    print(
        f"🕐 Windows boot: "
        f"{boot_datetime}"
    )

    print(
        f"⏱ Windows uptime: "
        f"{format_uptime(uptime)}"
    )

    print(
        "========================================"
    )

    while True:

        try:

            await run_connection()

        except (
            ConnectionRefusedError,
            OSError,
            websockets.WebSocketException,
        ) as e:

            print()
            print(
                "🔴 Server connection lost"
            )

            print(
                f"   Reason: {e}"
            )

        except Exception as e:

            print()
            print(
                "❌ Host error"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )

        print()
        print(
            f"🔄 Reconnecting in "
            f"{RECONNECT_DELAY} seconds..."
        )

        await asyncio.sleep(
            RECONNECT_DELAY
        )


# ============================================================
# CLEANUP
# ============================================================

def cleanup():

    print()
    print(
        "🧹 Cleaning up..."
    )

    stop_monitor()

    stop_webcam()

    try:

        if PowerShellPC.is_running():

            PowerShellPC.stop()

    except Exception as e:

        print(
            f"⚠️ PowerShell cleanup error: {e}"
        )

    print(
        "🟢 Cleanup complete"
    )


# ============================================================
# START
# ============================================================

def run_worker_mode(worker: str):
    """Run Monitor / Webcam / Control when launched as frozen child."""
    # HOST_ID may be in argv after --worker=...
    args = [a for a in sys.argv[1:] if not a.startswith("--worker")]
    if args:
        # pass host id through
        sys.argv = [sys.argv[0], *args]

    if worker in ("monitor", "Monitor.py"):
        import Monitor as worker_mod
        asyncio.run(worker_mod.main())
        return

    if worker in ("webcam", "webcam36.py"):
        import webcam36 as worker_mod
        asyncio.run(worker_mod.main())
        return

    if worker in ("control", "ControlStream.py"):
        import ControlStream as worker_mod
        asyncio.run(worker_mod.main_loop())
        return

    print(f"❌ Unknown worker: {worker}")
    sys.exit(1)


if __name__ == "__main__":

    # Child worker mode (used by .exe builds)
    for arg in sys.argv[1:]:
        if arg.startswith("--worker="):
            run_worker_mode(arg.split("=", 1)[1])
            sys.exit(0)

    # Hide console + tray icon (no need to rename to .pyw)
    hide_console = True
    if "--console" in sys.argv:
        hide_console = False
        sys.argv = [a for a in sys.argv if a != "--console"]

    if hide_console:
        hide_console_window()

    try:
        start_system_tray()
    except Exception as e:
        print(f"⚠️ Tray failed: {e}")

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "⏹ Host stopped by user"
        )

    except Exception as e:

        print()
        print(
            f"❌ Host stopped: "
            f"{type(e).__name__}: {e}"
        )

    finally:

        cleanup()
        try:
            if _tray_icon is not None:
                _tray_icon.stop()
        except Exception:
            pass


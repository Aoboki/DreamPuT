import asyncio
import base64
import json
import socket
import time
from datetime import datetime
from io import BytesIO

import websockets
from mss import MSS
from PIL import Image


# ============================================================
# CONFIG
# ============================================================

SERVER = "wss://remote.aoboki.pp.ua"

HOST_ID = socket.gethostname()

MONITOR_FPS = 15
FRAME_INTERVAL = 1 / MONITOR_FPS

SCREEN_MAX_WIDTH = 1280
SCREEN_MAX_HEIGHT = 720

JPEG_QUALITY = 70

RECONNECT_DELAY = 5

# ============================================================
# MAXIMUM MONITOR RUNTIME
# ============================================================

MAX_RUNTIME = 3600  # секунд (1 hour for remote control)


# ============================================================
# STATE
# ============================================================

running = True
stop_requested = False

START_TIME = 0


# ============================================================
# SCREEN CAPTURE
# ============================================================

def _get_cursor_pos():
    """Return (x, y, visible) of the system cursor on the primary monitor."""
    try:
        import ctypes
        from ctypes import wintypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y), True
    except Exception:
        return 0, 0, False


def _draw_cursor(image, screen_w, screen_h, mon_left=0, mon_top=0):
    """Draw a simple visible mouse pointer onto the captured frame."""
    try:
        from PIL import ImageDraw

        cx, cy, ok = _get_cursor_pos()
        if not ok:
            return image

        # Translate to monitor-relative coordinates
        cx -= mon_left
        cy -= mon_top

        if cx < 0 or cy < 0 or cx >= screen_w or cy >= screen_h:
            return image

        # Scale to thumbnail size
        iw, ih = image.size
        sx = iw / float(screen_w)
        sy = ih / float(screen_h)
        x = int(cx * sx)
        y = int(cy * sy)

        draw = ImageDraw.Draw(image)

        # Classic arrow cursor shape (scaled a bit for visibility)
        size = max(12, int(16 * max(sx, sy)))
        points = [
            (x, y),
            (x, y + size),
            (x + int(size * 0.35), y + int(size * 0.75)),
            (x + int(size * 0.6), y + int(size * 1.15)),
            (x + int(size * 0.75), y + int(size * 1.05)),
            (x + int(size * 0.45), y + int(size * 0.7)),
            (x + int(size * 0.85), y + int(size * 0.7)),
        ]

        # Shadow / outline
        shadow = [(px + 1, py + 1) for px, py in points]
        draw.polygon(shadow, fill=(0, 0, 0))
        draw.polygon(points, fill=(255, 255, 255), outline=(0, 0, 0))

    except Exception as e:
        print(f"⚠️ cursor draw error: {e}")

    return image


def capture_screen(sct):

    monitor = sct.monitors[1]

    # Original desktop size (for mouse mapping)
    screen_w = int(monitor.get("width") or 0)
    screen_h = int(monitor.get("height") or 0)
    mon_left = int(monitor.get("left") or 0)
    mon_top = int(monitor.get("top") or 0)

    screenshot = sct.grab(
        monitor
    )

    image = Image.frombytes(
        "RGB",
        screenshot.size,
        screenshot.rgb,
    )

    if not screen_w or not screen_h:
        screen_w, screen_h = image.size

    # Draw system cursor BEFORE scaling so position stays accurate
    image = _draw_cursor(
        image, screen_w, screen_h, mon_left=mon_left, mon_top=mon_top
    )

    image.thumbnail(
        (
            SCREEN_MAX_WIDTH,
            SCREEN_MAX_HEIGHT,
        )
    )

    buffer = BytesIO()

    image.save(
        buffer,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
    )

    b64 = base64.b64encode(
        buffer.getvalue()
    ).decode("ascii")

    return {
        "image": b64,
        "screen_width": screen_w,
        "screen_height": screen_h,
        "frame_width": image.size[0],
        "frame_height": image.size[1],
    }


# ============================================================
# SERVER COMMAND LISTENER
# ============================================================

async def listen_commands(ws):

    global running
    global stop_requested

    print()
    print("🎧 Waiting for monitor commands...")

    try:

        async for raw_message in ws:

            try:

                data = json.loads(
                    raw_message
                )

            except json.JSONDecodeError:

                print(
                    "⚠️ Invalid command from server"
                )

                continue

            message_type = data.get(
                "type"
            )

            print(
                f"📩 Monitor command: "
                f"{message_type}"
            )

            # ------------------------------------------------
            # STOP MONITOR
            # ------------------------------------------------

            if message_type == "monitor_stop":

                print()
                print("=" * 60)
                print("🛑 STOP COMMAND RECEIVED")
                print("=" * 60)

                print(
                    "⏹ Stopping screen capture..."
                )

                stop_requested = True
                running = False

                print(
                    "⏹ Monitor will disconnect"
                )

                print("=" * 60)

                return

            # ------------------------------------------------
            # START MONITOR
            # ------------------------------------------------

            elif message_type == "monitor_start":

                print(
                    "▶️ Monitor start command received"
                )

            else:

                print(
                    f"ℹ️ Unknown monitor command: "
                    f"{message_type}"
                )

    except websockets.ConnectionClosed:

        print(
            "🔴 Monitor command channel closed"
        )

        running = False

        raise


# ============================================================
# SEND SCREEN
# ============================================================

async def send_screen(ws):

    global running
    global stop_requested

    with MSS() as sct:

        print()
        print("=" * 60)
        print("🖥 MONITOR STARTED")
        print("=" * 60)

        print(
            f"🆔 Host ID: {HOST_ID}"
        )

        print(
            f"🎞 FPS: {MONITOR_FPS}"
        )

        print(
            f"📐 Maximum resolution: "
            f"{SCREEN_MAX_WIDTH}x"
            f"{SCREEN_MAX_HEIGHT}"
        )

        print(
            f"🖼 JPEG quality: "
            f"{JPEG_QUALITY}"
        )

        print(
            f"⏱ Maximum runtime: "
            f"{MAX_RUNTIME} seconds"
        )

        print("=" * 60)

        while running:

            # ------------------------------------------------
            # CHECK 25 SECOND LIMIT
            # ------------------------------------------------

            elapsed_total = (
                time.monotonic()
                - START_TIME
            )

            if elapsed_total >= MAX_RUNTIME:

                print()
                print("=" * 60)
                print("⏹ 25 SECONDS ELAPSED")
                print("⏹ Stopping Monitor.py")
                print("=" * 60)

                running = False
                stop_requested = True

                break

            # ------------------------------------------------
            # FRAME TIMER
            # ------------------------------------------------

            start = (
                asyncio
                .get_running_loop()
                .time()
            )

            try:

                frame = capture_screen(
                    sct
                )

                message = {

                    "type":
                        "screen_frame",

                    "host_id":
                        HOST_ID,

                    "image":
                        frame["image"],

                    "screen_width":
                        frame["screen_width"],

                    "screen_height":
                        frame["screen_height"],

                    "frame_width":
                        frame["frame_width"],

                    "frame_height":
                        frame["frame_height"],

                    "timestamp":
                        time.time(),

                    "time":
                        datetime.now().isoformat(),

                }

                await ws.send(
                    json.dumps(message)
                )

                print(
                    f"📸 Screen frame sent: "
                    f"{len(frame['image']):,} Base64 chars "
                    f"({frame['screen_width']}x{frame['screen_height']})"
                )

            except websockets.ConnectionClosed:

                print(
                    "🔴 Monitor WebSocket closed"
                )

                running = False

                raise

            except Exception as e:

                print(
                    f"❌ Screen error: {e}"
                )

                running = False

                raise

            # ------------------------------------------------
            # FPS DELAY
            # ------------------------------------------------

            elapsed = (
                asyncio
                .get_running_loop()
                .time()
                - start
            )

            delay = max(
                0,
                FRAME_INTERVAL - elapsed
            )

            if running:

                await asyncio.sleep(
                    delay
                )

        print()
        print(
            "⏹ Monitor screen capture stopped"
        )


# ============================================================
# CONNECTION
# ============================================================

async def monitor_connection():

    global running

    url = (
        f"{SERVER}"
        f"/ws/monitor-host/"
        f"{HOST_ID}"
    )

    print()
    print(
        "🔌 Connecting Monitor..."
    )

    print(
        f"   {url}"
    )

    try:

        async with websockets.connect(

            url,

            max_size=10 * 1024 * 1024,

            ping_interval=20,

            ping_timeout=30,

            close_timeout=5,

        ) as ws:

            print()
            print(
                "🟢 Monitor connected"
            )

            await ws.send(
                json.dumps({

                    "type":
                        "monitor_connected",

                    "host_id":
                        HOST_ID,

                    "timestamp":
                        time.time(),

                })
            )

            # ------------------------------------------------
            # RUN SENDER + COMMAND LISTENER TOGETHER
            # ------------------------------------------------

            sender_task = asyncio.create_task(
                send_screen(ws)
            )

            command_task = asyncio.create_task(
                listen_commands(ws)
            )

            done, pending = await asyncio.wait(

                [
                    sender_task,
                    command_task,
                ],

                return_when=asyncio.FIRST_COMPLETED,
            )

            # ------------------------------------------------
            # Cancel the other task
            # ------------------------------------------------

            for task in pending:

                task.cancel()

            await asyncio.gather(
                *pending,
                return_exceptions=True,
            )

            # ------------------------------------------------
            # If browser/server requested stop
            # ------------------------------------------------

            if not running:

                print()
                print(
                    "⏹ Monitor stopped"
                )

                return

    except websockets.ConnectionClosed as e:

        running = False

        print()
        print(
            "🔴 Monitor connection closed"
        )

        print(
            f"   Reason: {e}"
        )

        raise

    except Exception as e:

        print()
        print(
            "🔴 Monitor connection lost"
        )

        print(
            f"   Reason: {e}"
        )

        raise


# ============================================================
# MAIN
# ============================================================

async def main():

    global running
    global stop_requested
    global START_TIME

    # --------------------------------------------------------
    # RESET STATE
    # --------------------------------------------------------

    running = True
    stop_requested = False

    # --------------------------------------------------------
    # START 25 SECOND TIMER
    # --------------------------------------------------------

    START_TIME = time.monotonic()

    print()
    print("=" * 60)
    print("🖥 REMOTE DESKTOP MONITOR")
    print("=" * 60)

    print(
        f"🆔 Host ID: {HOST_ID}"
    )

    print(
        f"🌐 Server: {SERVER}"
    )

    print(
        f"🎞 FPS: {MONITOR_FPS}"
    )

    print(
        f"⏱ Maximum runtime: "
        f"{MAX_RUNTIME} seconds"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # MAIN CONNECTION LOOP
    # --------------------------------------------------------

    while running:

        # ----------------------------------------------------
        # CHECK GLOBAL 25 SECOND LIMIT
        # ----------------------------------------------------

        if (
            time.monotonic()
            - START_TIME
            >= MAX_RUNTIME
        ):

            print()
            print(
                "⏹ 25 seconds elapsed"
            )

            running = False
            stop_requested = True

            break

        try:

            await monitor_connection()

            # ------------------------------------------------
            # Server explicitly stopped monitor
            # ------------------------------------------------

            if stop_requested:

                print()
                print(
                    "🛑 Monitor stopped"
                )

                break

        except (
            ConnectionRefusedError,
            OSError,
            websockets.WebSocketException,
        ) as e:

            # ------------------------------------------------
            # DO NOT RECONNECT AFTER STOP
            # ------------------------------------------------

            if (
                stop_requested
                or not running
            ):

                break

            # ------------------------------------------------
            # CHECK 25 SECOND LIMIT
            # ------------------------------------------------

            if (
                time.monotonic()
                - START_TIME
                >= MAX_RUNTIME
            ):

                print()
                print(
                    "⏹ 25 seconds elapsed"
                )

                running = False
                stop_requested = True

                break

            print()
            print(
                "🔴 Monitor server connection lost"
            )

            print(
                f"   Reason: {e}"
            )

            print(
                f"🔄 Reconnecting in "
                f"{RECONNECT_DELAY} seconds..."
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )

            running = True

        except asyncio.CancelledError:

            break

        except Exception as e:

            if (
                stop_requested
                or not running
            ):

                break

            # ------------------------------------------------
            # CHECK 25 SECOND LIMIT
            # ------------------------------------------------

            if (
                time.monotonic()
                - START_TIME
                >= MAX_RUNTIME
            ):

                print()
                print(
                    "⏹ 25 seconds elapsed"
                )

                running = False
                stop_requested = True

                break

            print()
            print(
                "❌ Monitor error"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )

            running = True

    # --------------------------------------------------------
    # FINISHED
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("⏹ MONITOR PROCESS FINISHED")
    print("=" * 60)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        running = False
        stop_requested = True

        print()
        print(
            "⏹ Monitor stopped by user"
        )

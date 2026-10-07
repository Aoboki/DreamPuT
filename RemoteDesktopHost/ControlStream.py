"""
WebRTC screen stream for remote Control.
TeamViewer-style: encoded video (VP8/H264 via WebRTC) instead of JPEG screenshots.
"""
import asyncio
import fractions
import json
import logging
import socket
import sys
import time
import uuid

import numpy as np
import websockets
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
    VideoStreamTrack,
)
from av import VideoFrame

try:
    import dxcam
    HAS_DXCAM = True
except Exception:
    HAS_DXCAM = False

try:
    from mss import MSS
    HAS_MSS = True
except Exception:
    HAS_MSS = False


HOST_ID = (
    sys.argv[1]
    if len(sys.argv) > 1
    else socket.gethostname().lower()
)

SERVER_URL = f"wss://remote.aoboki.pp.ua/ws/control/host/{HOST_ID}"

TARGET_FPS = 20
MAX_WIDTH = 1280
MAX_HEIGHT = 720

# quality presets: name -> (max_width, max_height, fps)
QUALITY_PRESETS = {
    "low":    (640,  360,  10),
    "medium": (960,  540,  15),
    "high":   (1280, 720,  20),
    "ultra":  (1920, 1080, 25),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("control-stream")


def fetch_ice_servers():
    """Load Cloudflare TURN iceServers from our signaling server."""
    import urllib.request
    url = "https://remote.aoboki.pp.ua/api/webrtc/ice-servers"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        servers = data.get("iceServers") or []
        if not servers:
            raise RuntimeError("empty iceServers")
        result = []
        for s in servers:
            urls = s.get("urls")
            if isinstance(urls, str):
                urls = [urls]
            kwargs = {"urls": urls}
            if s.get("username"):
                kwargs["username"] = s["username"]
            if s.get("credential"):
                kwargs["credential"] = s["credential"]
            result.append(RTCIceServer(**kwargs))
        log.info("🧊 ICE servers loaded: %d", len(result))
        return result
    except Exception as e:
        log.warning("ICE fetch failed (%s) — STUN only", e)
        return [
            RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
            RTCIceServer(urls=["stun:stun.cloudflare.com:3478"]),
        ]


websocket = None
shutdown_event = asyncio.Event()
sessions = {}
session_lock = asyncio.Lock()
screen_track = None



def _cursor_pos():
    try:
        import ctypes
        from ctypes import wintypes
        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    except Exception:
        return None


def _draw_cursor_bgr(img, full_w, full_h, mon_left=0, mon_top=0):
    """Draw a visible arrow cursor into a BGR numpy frame."""
    pos = _cursor_pos()
    if pos is None:
        return img
    cx, cy = pos[0] - mon_left, pos[1] - mon_top
    h, w = img.shape[:2]
    # map from full desktop coords to current frame size
    if full_w <= 0 or full_h <= 0:
        return img
    x = int(cx * (w / float(full_w)))
    y = int(cy * (h / float(full_h)))
    if x < -5 or y < -5 or x >= w or y >= h:
        return img

    # arrow polygon in BGR: white fill, black outline
    size = max(14, int(18 * max(w / 1280.0, h / 720.0)))
    pts = np.array([
        [x, y],
        [x, y + size],
        [x + int(size * 0.35), y + int(size * 0.72)],
        [x + int(size * 0.55), y + int(size * 1.15)],
        [x + int(size * 0.72), y + int(size * 1.05)],
        [x + int(size * 0.42), y + int(size * 0.68)],
        [x + int(size * 0.85), y + int(size * 0.68)],
    ], dtype=np.int32)

    try:
        import cv2
        shadow = pts + np.array([[1, 1]], dtype=np.int32)
        cv2.fillPoly(img, [shadow], (0, 0, 0))
        cv2.fillPoly(img, [pts], (255, 255, 255))
        cv2.polylines(img, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)
    except Exception:
        # minimal fallback without cv2: draw a small filled rectangle tip
        x2 = min(w, x + 3)
        y2 = min(h, y + size)
        img[max(0, y):y2, max(0, x):x2] = (255, 255, 255)
    return img


class ScreenTrack(VideoStreamTrack):
    """Capture desktop and feed WebRTC."""

    kind = "video"

    def __init__(self, fps=TARGET_FPS, max_width=MAX_WIDTH, max_height=MAX_HEIGHT):
        super().__init__()
        self.fps = fps
        self.max_width = max_width
        self.max_height = max_height
        self._frame_interval = 1.0 / max(1, fps)
        self._last = 0.0
        self.screen_w = 0
        self.screen_h = 0
        self._camera = None
        self._sct = None
        self._monitor = None
        self._init_capture()

    def set_quality(self, preset: str):
        preset = (preset or "high").lower()
        if preset not in QUALITY_PRESETS:
            preset = "high"
        w, h, fps = QUALITY_PRESETS[preset]
        self.max_width = w
        self.max_height = h
        self.fps = fps
        self._frame_interval = 1.0 / max(1, fps)
        log.info("🎚 quality=%s %dx%d @%dfps", preset, w, h, fps)

    def _init_capture(self):
        if HAS_DXCAM:
            try:
                self._camera = dxcam.create(output_idx=0, output_color="BGR")
                self._camera.start(target_fps=self.fps, video_mode=True)
                frame = self._camera.get_latest_frame()
                if frame is not None:
                    self.screen_h, self.screen_w = frame.shape[:2]
                log.info("🟢 Capture: dxcam (Desktop Duplication API)")
                return
            except Exception as e:
                log.warning("dxcam failed: %s — fallback to mss", e)
                self._camera = None

        if not HAS_MSS:
            raise RuntimeError("No screen capture backend (dxcam/mss)")

        self._sct = MSS()
        self._monitor = self._sct.monitors[1]
        self.screen_w = int(self._monitor["width"])
        self.screen_h = int(self._monitor["height"])
        log.info(
            "🟢 Capture: mss %sx%s",
            self.screen_w,
            self.screen_h,
        )

    def _grab(self):
        if self._camera is not None:
            frame = self._camera.get_latest_frame()
            if frame is None:
                return None
            # dxcam returns BGR
            img = frame
        else:
            shot = self._sct.grab(self._monitor)
            # mss BGRA -> BGR for VideoFrame
            img = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                (shot.height, shot.width, 4)
            )[:, :, :3].copy()

        h, w = img.shape[:2]
        # keep original desktop size for mouse mapping on browser
        orig_w, orig_h = w, h
        self.screen_w, self.screen_h = orig_w, orig_h

        mon_left = 0
        mon_top = 0
        if self._monitor is not None:
            mon_left = int(self._monitor.get("left") or 0)
            mon_top = int(self._monitor.get("top") or 0)

        # Draw system cursor on full-res frame first
        img = _draw_cursor_bgr(img, orig_w, orig_h, mon_left, mon_top)

        # downscale if needed
        if w > self.max_width or h > self.max_height:
            scale = min(self.max_width / w, self.max_height / h)
            nw, nh = int(w * scale), int(h * scale)
            try:
                import cv2
                img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
            except Exception:
                y_idx = (np.linspace(0, h - 1, nh)).astype(np.int32)
                x_idx = (np.linspace(0, w - 1, nw)).astype(np.int32)
                img = img[y_idx][:, x_idx]

        return img

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # pace
        now = time.time()
        delay = self._frame_interval - (now - self._last)
        if delay > 0:
            await asyncio.sleep(delay)
        self._last = time.time()

        img = await asyncio.get_event_loop().run_in_executor(None, self._grab)
        if img is None:
            # black frame fallback
            img = np.zeros((360, 640, 3), dtype=np.uint8)

        frame = VideoFrame.from_ndarray(img, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame

    def stop(self):
        try:
            if self._camera is not None:
                self._camera.stop()
        except Exception:
            pass
        try:
            if self._sct is not None:
                self._sct.close()
        except Exception:
            pass


def get_screen_track():
    global screen_track
    if screen_track is None:
        screen_track = ScreenTrack(fps=TARGET_FPS)
    return screen_track


async def send_json(data: dict) -> bool:
    global websocket
    if websocket is None:
        return False
    try:
        await websocket.send(json.dumps(data, ensure_ascii=False))
        return True
    except Exception as e:
        log.error("send error: %s", e)
        return False


async def _close_session(viewer_id: str):
    session = sessions.pop(viewer_id, None)
    if not session:
        return
    pc = session.get("pc")
    if pc:
        try:
            await pc.close()
        except Exception:
            pass
    log.info("🧹 session closed: %s", viewer_id)


async def create_session_for_viewer(viewer_id: str):
    async with session_lock:
        if viewer_id in sessions:
            return

        track = get_screen_track()

        pc = RTCPeerConnection(
            RTCConfiguration(
                iceServers=fetch_ice_servers()
            )
        )

        pc.addTrack(track)
        sessions[viewer_id] = {"pc": pc}

        @pc.on("connectionstatechange")
        async def on_state():
            log.info("WebRTC [%s] %s", viewer_id, pc.connectionState)
            if pc.connectionState in ("failed", "closed", "disconnected"):
                await _close_session(viewer_id)

        @pc.on("iceconnectionstatechange")
        async def on_ice():
            log.info("ICE [%s] %s", viewer_id, pc.iceConnectionState)

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):
            if candidate is None:
                await send_json(
                    {
                        "type": "candidate",
                        "host_id": HOST_ID,
                        "viewer_id": viewer_id,
                        "candidate": None,
                    }
                )
                return
            related = ""
            if getattr(candidate, "relatedAddress", None):
                related = (
                    f" raddr {candidate.relatedAddress} "
                    f"rport {candidate.relatedPort}"
                )
            tcp_type = ""
            if getattr(candidate, "tcpType", None):
                tcp_type = f" tcptype {candidate.tcpType}"
            cand_str = (
                f"candidate:{candidate.foundation} {candidate.component} "
                f"{candidate.protocol} {candidate.priority} "
                f"{candidate.ip} {candidate.port} typ {candidate.type}"
                f"{related}{tcp_type}"
            )
            await send_json(
                {
                    "type": "candidate",
                    "host_id": HOST_ID,
                    "viewer_id": viewer_id,
                    "candidate": {
                        "candidate": cand_str,
                        "sdpMid": candidate.sdpMid,
                        "sdpMLineIndex": candidate.sdpMLineIndex,
                    },
                }
            )

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        await send_json(
            {
                "type": "offer",
                "host_id": HOST_ID,
                "viewer_id": viewer_id,
                "sdp": pc.localDescription.sdp,
                "screen_width": track.screen_w,
                "screen_height": track.screen_h,
            }
        )
        log.info(
            "📤 offer sent viewer=%s screen=%sx%s",
            viewer_id,
            track.screen_w,
            track.screen_h,
        )


async def handle_message(message: dict):
    msg_type = message.get("type")
    viewer_id = message.get("viewer_id")

    if msg_type == "viewer_ready":
        if not viewer_id:
            viewer_id = str(uuid.uuid4())
        await create_session_for_viewer(viewer_id)
        return

    if msg_type in ("viewer_left", "viewer_closed", "viewer_disconnect"):
        if viewer_id:
            async with session_lock:
                await _close_session(viewer_id)
        return

    if msg_type == "answer":
        if not viewer_id:
            return
        async with session_lock:
            session = sessions.get(viewer_id)
            if not session:
                return
            pc = session["pc"]
            if pc.signalingState != "have-local-offer":
                return
            sdp = message.get("sdp")
            if not sdp:
                return
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=sdp, type="answer")
            )
            log.info("🟢 answer accepted %s", viewer_id)
        return

    if msg_type == "candidate":
        if not viewer_id:
            return
        async with session_lock:
            session = sessions.get(viewer_id)
            if not session:
                return
            pc = session["pc"]
            cand = message.get("candidate")
            try:
                from aiortc.sdp import candidate_from_sdp

                if cand is None or (
                    isinstance(cand, dict)
                    and not (cand.get("candidate") or "").strip()
                ):
                    await pc.addIceCandidate(None)
                    return
                raw = cand.get("candidate") or ""
                sdp_str = raw
                if sdp_str.startswith("candidate:"):
                    sdp_str = sdp_str[len("candidate:") :]
                ice = candidate_from_sdp(sdp_str)
                ice.sdpMid = cand.get("sdpMid")
                ice.sdpMLineIndex = cand.get("sdpMLineIndex")
                await pc.addIceCandidate(ice)
            except Exception as e:
                log.error("addIceCandidate: %s", e)
        return

    if msg_type == "quality":
        preset = message.get("quality") or message.get("preset") or "high"
        track = get_screen_track()
        track.set_quality(preset)
        await send_json({
            "type": "quality_ack",
            "host_id": HOST_ID,
            "quality": preset,
            "width": track.max_width,
            "height": track.max_height,
            "fps": track.fps,
        })
        return

    if msg_type in ("control_stop", "stop"):
        log.info("🛑 stop requested")
        shutdown_event.set()
        return


async def main_loop():
    global websocket

    while not shutdown_event.is_set():
        try:
            log.info("🔌 Connecting %s", SERVER_URL)
            async with websockets.connect(
                SERVER_URL,
                max_size=8 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            ) as ws:
                websocket = ws
                log.info("🟢 ControlStream connected as %s", HOST_ID)
                await send_json(
                    {
                        "type": "control_status",
                        "host_id": HOST_ID,
                        "status": "ready",
                    }
                )

                async for raw in ws:
                    if shutdown_event.is_set():
                        break
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    await handle_message(msg)

        except Exception as e:
            websocket = None
            if shutdown_event.is_set():
                break
            log.error("connection error: %s", e)
            await asyncio.sleep(3)

    # cleanup
    for vid in list(sessions.keys()):
        await _close_session(vid)
    global screen_track
    if screen_track:
        screen_track.stop()
        screen_track = None


if __name__ == "__main__":
    log.info("ControlStream starting host_id=%s", HOST_ID)
    if HAS_DXCAM:
        log.info("backend preference: dxcam")
    elif HAS_MSS:
        log.info("backend preference: mss")
    else:
        log.error("No capture backend")
        sys.exit(1)
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        pass

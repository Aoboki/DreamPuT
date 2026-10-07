"""
Local USB webcams on the server host (yard surveillance).
MJPEG video via ffmpeg/v4l2; optional audio from one selected camera.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, AsyncIterator, Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "data" / "local_webcams.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "cameras": [
        {
            "id": "cam1",
            "name": "Yard Left",
            "side": "left",
            "device": "/dev/video0",
            "audio_device": "",
            "width": 640,
            "height": 480,
            "fps": 10,
            "enabled": True,
        },
        {
            "id": "cam2",
            "name": "Yard Right",
            "side": "right",
            "device": "/dev/video2",
            "audio_device": "",
            "width": 640,
            "height": 480,
            "fps": 10,
            "enabled": True,
        },
    ],
    # which camera id provides audio (or "" / null = muted)
    "audio_from": "cam1",
}


def _ensure_config() -> dict[str, Any]:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "cameras" not in data:
            save_config(DEFAULT_CONFIG)
            return json.loads(json.dumps(DEFAULT_CONFIG))
        return data
    except Exception:
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))


def load_config() -> dict[str, Any]:
    return _ensure_config()


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # normalize cameras
    cams = data.get("cameras") or []
    out_cams = []
    for i, c in enumerate(cams[:4]):
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or f"cam{i+1}").strip() or f"cam{i+1}"
        out_cams.append(
            {
                "id": cid,
                "name": str(c.get("name") or cid)[:64],
                "device": str(c.get("device") or "").strip(),
                "audio_device": str(c.get("audio_device") or "").strip(),
                "width": max(160, min(1920, int(c.get("width") or 640))),
                "height": max(120, min(1080, int(c.get("height") or 480))),
                "fps": max(1, min(30, int(c.get("fps") or 10))),
                "enabled": bool(c.get("enabled", True)),
                "side": (str(c.get("side") or ("left" if i == 0 else "right")).lower()),
            }
        )
    if not out_cams:
        out_cams = DEFAULT_CONFIG["cameras"]
    audio_from = str(data.get("audio_from") or "")
    ids = {c["id"] for c in out_cams}
    if audio_from and audio_from not in ids:
        audio_from = out_cams[0]["id"]
    normalized = {"cameras": out_cams, "audio_from": audio_from}
    # preserve motion settings (and other extra keys we care about)
    if isinstance(data.get("motion"), dict):
        normalized["motion"] = data["motion"]
    elif CONFIG_PATH.exists():
        try:
            prev = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(prev.get("motion"), dict):
                normalized["motion"] = prev["motion"]
        except Exception:
            pass
    CONFIG_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized


def get_camera(cam_id: str) -> Optional[dict[str, Any]]:
    cfg = load_config()
    for c in cfg.get("cameras") or []:
        if c.get("id") == cam_id:
            return c
    return None


def detect_v4l_devices() -> list[dict[str, str]]:
    """List capture-oriented /dev/video* nodes (skip pure metadata when possible)."""
    found: list[dict[str, str]] = []
    by_id = Path("/dev/v4l/by-id")
    if by_id.is_dir():
        for p in sorted(by_id.iterdir()):
            if not p.name.endswith("-video-index0"):
                # index0 is usually the real capture node
                continue
            try:
                real = str(p.resolve())
            except Exception:
                continue
            found.append({"path": real, "label": p.name, "via": "by-id"})
    # also raw video nodes
    for n in range(0, 32):
        path = f"/dev/video{n}"
        if not os.path.exists(path):
            continue
        if any(f["path"] == path for f in found):
            continue
        # prefer even nodes as capture (common USB pattern); still list all
        found.append({"path": path, "label": f"video{n}", "via": "raw"})
    return found


def detect_alsa_devices() -> list[dict[str, str]]:
    """Parse `arecord -l` for capture cards."""
    out: list[dict[str, str]] = []
    arecord = shutil.which("arecord")
    if not arecord:
        return out
    try:
        import subprocess

        r = subprocess.run(
            [arecord, "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = r.stdout or ""
    except Exception:
        return out
    # card 1: Web Camera [Web Camera], device 0: USB Audio [USB Audio]
    for m in re.finditer(
        r"card\s+(\d+):\s*(\S+)\s*\[([^\]]+)\].*?device\s+(\d+):\s*([^\[]+)\[([^\]]+)\]",
        text,
        re.S,
    ):
        card, card_id, card_name, dev, dev_id, dev_name = m.groups()
        plughw = f"plughw:{card},{dev}"
        hw = f"hw:{card},{dev}"
        out.append(
            {
                "plughw": plughw,
                "hw": hw,
                "label": f"{card_name.strip()} / {dev_name.strip()} ({plughw})",
            }
        )
    return out


def ffmpeg_bin() -> Optional[str]:
    """Resolve ffmpeg even when systemd has a minimal PATH."""
    for candidate in (
        shutil.which("ffmpeg"),
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/bin/ffmpeg",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None



def _ffmpeg_mjpeg_cmd(device: str, w: int, h: int, fps: int, copy: bool) -> list[str]:
    ff = ffmpeg_bin()
    assert ff
    # Low-latency v4l2 → MJPEG pipe
    cmd = [
        ff,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-f",
        "v4l2",
        "-input_format",
        "mjpeg",
        "-video_size",
        f"{w}x{h}",
        "-framerate",
        str(fps),
        "-i",
        device,
        "-an",
        "-fps_mode",
        "passthrough",
    ]
    if copy:
        # native MJPEG from USB cam — lowest CPU/latency
        cmd += ["-c:v", "copy", "-f", "mjpeg", "pipe:1"]
    else:
        cmd += ["-f", "mjpeg", "-q:v", "8", "pipe:1"]
    return cmd


def _multipart_frame(jpeg: bytes) -> bytes:
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: "
        + str(len(jpeg)).encode()
        + b"\r\n\r\n"
        + jpeg
        + b"\r\n"
    )


class _CamPublisher:
    """One ffmpeg process per camera; broadcast JPEGs to many viewers."""

    def __init__(self, cam_id: str, cam: dict[str, Any]):
        self.cam_id = cam_id
        self.cam = dict(cam)
        self.subs: set[asyncio.Queue] = set()
        self.task: Optional[asyncio.Task] = None
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.last_jpeg: Optional[bytes] = None
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2)  # drop old frames → lower lag
        async with self._lock:
            self.subs.add(q)
            if self.last_jpeg:
                try:
                    q.put_nowait(self.last_jpeg)
                except asyncio.QueueFull:
                    pass
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self._run())
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self.subs.discard(q)
            if not self.subs:
                await self._stop_proc()
                if self.task and not self.task.done():
                    self.task.cancel()
                    try:
                        await self.task
                    except (asyncio.CancelledError, Exception):
                        pass
                self.task = None

    async def _stop_proc(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.kill()
        except Exception:
            pass
        try:
            await self.proc.wait()
        except Exception:
            pass
        self.proc = None

    def _broadcast(self, jpeg: bytes) -> None:
        self.last_jpeg = jpeg
        dead = []
        for q in list(self.subs):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(jpeg)
            except Exception:
                dead.append(q)
        for q in dead:
            self.subs.discard(q)

    async def _run(self) -> None:
        device = self.cam.get("device") or ""
        if not device or not os.path.exists(device) or not ffmpeg_bin():
            return
        w = int(self.cam.get("width") or 640)
        h = int(self.cam.get("height") or 480)
        fps = max(5, min(15, int(self.cam.get("fps") or 10)))

        for copy in (True, False):
            if not self.subs:
                return
            cmd = _ffmpeg_mjpeg_cmd(device, w, h, fps, copy=copy)
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=1024 * 1024,
                )
            except Exception:
                continue
            assert self.proc.stdout is not None
            buf = b""
            frames = 0
            try:
                while self.subs:
                    chunk = await self.proc.stdout.read(65536)
                    if not chunk:
                        break
                    buf += chunk
                    # keep buffer bounded
                    if len(buf) > 2 * 1024 * 1024:
                        buf = buf[-256 * 1024 :]
                    while True:
                        start = buf.find(b"\xff\xd8")
                        if start < 0:
                            buf = buf[-2:] if len(buf) > 2 else buf
                            break
                        end = buf.find(b"\xff\xd9", start + 2)
                        if end < 0:
                            if start > 0:
                                buf = buf[start:]
                            break
                        jpeg = buf[start : end + 2]
                        buf = buf[end + 2 :]
                        frames += 1
                        self._broadcast(jpeg)
            finally:
                await self._stop_proc()
            if frames > 0:
                # process died but had frames — restart if still subscribers
                await asyncio.sleep(0.3)
                if self.subs:
                    continue
                return
            # try encode mode
        return


_publishers: dict[str, _CamPublisher] = {}
_pub_lock = asyncio.Lock()


async def mjpeg_stream(cam: dict[str, Any]) -> AsyncIterator[bytes]:
    """Shared MJPEG stream: many browsers, one ffmpeg per camera."""
    cam_id = str(cam.get("id") or "cam")
    device = cam.get("device") or ""
    if not device or not os.path.exists(device):
        msg = f"Device not found: {device}".encode()
        yield b"--frame\r\nContent-Type: text/plain\r\n\r\n" + msg + b"\r\n"
        return
    if not ffmpeg_bin():
        yield b"--frame\r\nContent-Type: text/plain\r\n\r\nffmpeg not installed\r\n"
        return

    async with _pub_lock:
        pub = _publishers.get(cam_id)
        if pub is None or pub.cam.get("device") != device:
            pub = _CamPublisher(cam_id, cam)
            _publishers[cam_id] = pub
        else:
            # refresh size/fps from latest config
            pub.cam = dict(cam)

    q = await pub.subscribe()
    try:
        while True:
            try:
                jpeg = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # keep connection alive
                yield b"--frame\r\nContent-Type: text/plain\r\n\r\n\r\n"
                continue
            yield _multipart_frame(jpeg)
    finally:
        await pub.unsubscribe(q)


async def grab_snapshot_jpeg(cam: dict[str, Any]) -> bytes:
    """Single JPEG — prefer last frame from live publisher, else ffmpeg once."""
    cam_id = str(cam.get("id") or "")
    pub = _publishers.get(cam_id)
    if pub and pub.last_jpeg:
        return pub.last_jpeg

    device = cam.get("device") or ""
    if not device or not os.path.exists(device):
        raise FileNotFoundError(device)
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg missing")
    w = int(cam.get("width") or 640)
    h = int(cam.get("height") or 480)
    out = Path("/tmp") / f"cam_snap_{cam.get('id', 'x')}.jpg"
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-input_format",
        "mjpeg",
        "-video_size",
        f"{w}x{h}",
        "-i",
        device,
        "-frames:v",
        "1",
        "-update",
        "1",
        "-f",
        "image2",
        str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError((err or b"snapshot failed").decode("utf-8", "replace")[:500])
    data = out.read_bytes()
    try:
        out.unlink()
    except Exception:
        pass
    return data


async def mjpeg_stream_with_fallback(cam: dict[str, Any]) -> AsyncIterator[bytes]:
    async for part in mjpeg_stream(cam):
        yield part


async def audio_mp3_stream(alsa_device: str) -> AsyncIterator[bytes]:
    """Stream MP3 from an ALSA capture device (one camera mic)."""
    if not alsa_device:
        return
    ff = ffmpeg_bin()
    if not ff:
        return
    cmd = [
        ff,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "alsa",
        "-i",
        alsa_device,
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "mp3",
        "-b:a",
        "64k",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    try:
        while True:
            chunk = await proc.stdout.read(2048)
            if not chunk:
                break
            yield chunk
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await proc.wait()
        except Exception:
            pass

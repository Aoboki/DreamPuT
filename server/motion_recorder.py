"""
Motion detection + short recordings for yard USB cameras.
- Detect motion → record 30s video+audio → back to detect
- Per-camera folder, keep last N files (default 10)
- Naming: left → L1.mp4, L2.mp4…  right → R1.mp4, R2.mp4…
"""
from __future__ import annotations

import logging

import asyncio
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Optional

import local_webcams as lw
import telegram_notify

log = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent
REC_ROOT = BASE_DIR / "data" / "recordings"
STATE_PATH = BASE_DIR / "data" / "motion_state.json"

DEFAULT_MOTION = {
    "enabled": True,
    "record_seconds": 15,
    "max_files_per_camera": 30,
    "threshold": 25,                # per-pixel gray delta after blur
    "min_changed_ratio": 0.25,      # 25% of frame must change
    "cooldown_seconds": 20,
    "check_interval": 2.0,          # photo every N seconds
    "confirm_hits": 2,              # consecutive checks above threshold
}


def _ffmpeg() -> Optional[str]:
    return lw.ffmpeg_bin()


def motion_settings() -> dict[str, Any]:
    cfg = lw.load_config()
    m = dict(DEFAULT_MOTION)
    raw = cfg.get("motion") or {}
    if isinstance(raw, dict):
        m.update(raw)
    # coerce types
    try:
        m["record_seconds"] = max(5, min(600, int(m.get("record_seconds") or 15)))
    except Exception:
        m["record_seconds"] = 15
    try:
        m["check_interval"] = max(0.5, min(30.0, float(m.get("check_interval") or 2.0)))
    except Exception:
        m["check_interval"] = 2.0
    try:
        m["min_changed_ratio"] = max(0.01, min(0.9, float(m.get("min_changed_ratio") or 0.13)))
    except Exception:
        m["min_changed_ratio"] = 0.13
    try:
        m["max_files_per_camera"] = max(1, min(100, int(m.get("max_files_per_camera") or 10)))
    except Exception:
        m["max_files_per_camera"] = 10
    m["enabled"] = bool(m.get("enabled", True))
    return m


def camera_side(cam: dict[str, Any], index: int) -> str:
    side = str(cam.get("side") or "").strip().lower()
    if side in ("left", "right", "l", "r"):
        return "left" if side in ("left", "l") else "right"
    # defaults: first cam left, second right
    return "left" if index == 0 else "right"


def side_prefix(side: str) -> str:
    return "L" if side == "left" else "R"


def recordings_dir(side: str) -> Path:
    d = REC_ROOT / side
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_recordings(side: str) -> list[dict[str, Any]]:
    d = recordings_dir(side)
    files = []
    for p in d.glob("*.mp4"):
        m = re.match(r"^([LR])(\d+)\.mp4$", p.name, re.I)
        if not m:
            continue
        num = int(m.group(2))
        st = p.stat()
        thumb = p.with_suffix(".jpg")
        entry = {
            "name": p.name,
            "side": side,
            "index": num,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
            "url": f"/api/local-cams/recordings/{side}/{p.name}",
            "thumb": f"/api/local-cams/recordings/{side}/{thumb.name}" if thumb.is_file() else None,
            "thumb_name": thumb.name if thumb.is_file() else None,
            "change_percent": None,
        }
        meta = p.with_suffix(".json")
        if meta.is_file():
            try:
                entry["change_percent"] = json.loads(meta.read_text(encoding="utf-8")).get("change_percent")
            except Exception:
                pass
        files.append(entry)
    files.sort(key=lambda x: x["index"], reverse=True)
    return files


def _next_index(side: str) -> int:
    d = recordings_dir(side)
    seq_file = d / ".seq"
    best = 0
    if seq_file.exists():
        try:
            best = int(seq_file.read_text().strip() or "0")
        except Exception:
            best = 0
    for p in d.glob("*.mp4"):
        m = re.match(r"^[LR](\d+)\.mp4$", p.name, re.I)
        if m:
            best = max(best, int(m.group(1)))
    return best + 1


def _save_seq(side: str, n: int) -> None:
    seq_file = recordings_dir(side) / ".seq"
    seq_file.write_text(str(n) + "\n", encoding="utf-8")


def rotate_old(side: str, max_files: int) -> None:
    files = list_recordings(side)
    # list is newest first; delete oldest beyond max
    while len(files) > max_files:
        oldest = files.pop()  # last = smallest index among remaining... 
        # actually sorted reverse by index — last is oldest number
        path = recordings_dir(side) / oldest["name"]
        try:
            path.unlink(missing_ok=True)
            path.with_suffix(".jpg").unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
            log.info("Removed old recording %s", path.name)
        except Exception as e:
            log.warning("rotate delete failed: %s", e)
        files = list_recordings(side)


def resolve_audio_device(cam: dict[str, Any]) -> str:
    """Use camera audio_device, else first ALSA capture from arecord -l."""
    alsa = str(cam.get("audio_device") or "").strip()
    if alsa:
        return alsa
    devices = lw.detect_alsa_devices()
    if devices:
        return devices[0].get("plughw") or devices[0].get("hw") or ""
    return ""


async def record_clip(

    cam: dict[str, Any],
    side: str,
    seconds: int,
    max_files: int,
) -> Optional[Path]:
    """Record video+audio with ffmpeg for `seconds`, return path."""
    ff = _ffmpeg()
    if not ff:
        log.error("motion record: ffmpeg missing")
        return None
    device = cam.get("device") or ""
    if not device or not os.path.exists(device):
        log.error("motion record: no device %s", device)
        return None

    w = int(cam.get("width") or 640)
    h = int(cam.get("height") or 480)
    fps = max(5, min(15, int(cam.get("fps") or 10)))
    alsa = resolve_audio_device(cam)

    n = _next_index(side)
    prefix = side_prefix(side)
    out = recordings_dir(side) / f"{prefix}{n}.mp4"

    # Build ffmpeg: v4l2 (+ optional alsa) → mp4
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
        "-framerate",
        str(fps),
        "-i",
        device,
    ]
    def build_cmd(use_audio: bool) -> list:
        c = [
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
            "-framerate",
            str(fps),
            "-thread_queue_size",
            "512",
            "-i",
            device,
        ]
        if use_audio and alsa:
            adev = alsa
            if adev.startswith("hw:") and not adev.startswith("plughw:"):
                adev = "plughw:" + adev[len("hw:"):]
            c += [
                "-f",
                "alsa",
                "-thread_queue_size",
                "1024",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-i",
                adev,
                # output options: fixed duration, do NOT use -shortest
                "-t",
                str(seconds),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0?",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                "-af",
                "aresample=async=1:first_pts=0",
                str(out),
            ]
        else:
            c += [
                "-t",
                str(seconds),
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-an",
                str(out),
            ]
        return c

    # try with audio, then video-only fallback
    last_err = b""
    for use_audio in ((True, False) if alsa else (False,)):
        cmd = build_cmd(use_audio)
        log.info(
            "Recording %s (%ss) device=%s audio=%s",
            out.name,
            seconds,
            device,
            (alsa if use_audio else "none"),
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        last_err = err or b""
        if proc.returncode == 0 and out.exists() and out.stat().st_size >= 1000:
            break
        try:
            out.unlink(missing_ok=True)
        except Exception:
            pass
    else:
        msg = last_err.decode("utf-8", "replace")[:500]
        log.error("record failed: %s", msg)
        return None

    _save_seq(side, n)
    rotate_old(side, max_files)
    log.info("Saved %s (%s bytes)", out, out.stat().st_size)
    return out


async def _grab_gray_jpeg(device: str, w: int, h: int) -> Optional[bytes]:
    """One JPEG frame via ffmpeg (does not hold device long)."""
    ff = _ffmpeg()
    if not ff or not device or not os.path.exists(device):
        return None
    out = Path("/tmp") / f"motion_{os.path.basename(device)}.jpg"
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
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    if proc.returncode != 0 or not out.exists():
        return None
    data = out.read_bytes()
    try:
        out.unlink(missing_ok=True)
    except Exception:
        pass
    return data


def photo_change_percent(prev: bytes, cur: bytes, pixel_threshold: int = 25) -> float:
    """Compare two JPEGs; return % of pixels that changed (0..100).

    Uses grayscale + downscale + blur to ignore JPEG noise / tiny lighting flicker.
    Requires Pillow (PIL). Without PIL returns 0.0 (never false-trigger on byte noise).
    """
    try:
        from PIL import Image, ImageFilter
        import io

        def prep(data: bytes) -> list[int]:
            im = Image.open(io.BytesIO(data)).convert("L")
            im = im.resize((160, 120), Image.Resampling.BILINEAR)
            im = im.filter(ImageFilter.BoxBlur(2))
            return list(im.getdata())

        pa = prep(prev)
        pb = prep(cur)
        if not pa or len(pa) != len(pb):
            return 0.0
        thr = max(5, int(pixel_threshold))
        changed = sum(1 for i in range(len(pa)) if abs(pa[i] - pb[i]) > thr)
        return (changed / len(pa)) * 100.0
    except Exception as e:
        log.warning("photo_change_percent needs Pillow for reliable detect: %s", e)
        return 0.0


def _jpeg_motion(prev: bytes, cur: bytes, threshold: int, min_ratio: float) -> bool:
    """Back-compat: True if change ratio >= min_ratio (min_ratio is 0..1)."""
    pct = photo_change_percent(prev, cur, pixel_threshold=threshold)
    return (pct / 100.0) >= float(min_ratio)


async def _release_device_for_record(cam_id: str, device: str) -> None:
    """Stop live MJPEG publisher and free /dev/videoX for ffmpeg record."""
    try:
        pub = getattr(lw, "_publishers", {}).get(cam_id)
        if pub is not None:
            await pub._stop_proc()
            for q in list(getattr(pub, "subs", []) or []):
                try:
                    pub.subs.discard(q)
                except Exception:
                    pass
            if getattr(pub, "task", None) and not pub.task.done():
                pub.task.cancel()
                try:
                    await pub.task
                except Exception:
                    pass
                pub.task = None
    except Exception as e:
        log.warning("publisher stop failed: %s", e)

    if device and os.path.exists(device):
        try:
            proc = await asyncio.create_subprocess_exec(
                "fuser",
                "-k",
                device,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass
    await asyncio.sleep(1.0)


class MotionWorker:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.status: dict[str, Any] = {"running": False, "cameras": {}}

    def start(self) -> None:
        if self._task and not self._task.done():
            log.info("MotionWorker already running")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())
        s = motion_settings()
        log.info(
            "MotionWorker started enabled=%s record_seconds=%s max_files=%s min_changed_ratio=%s (%.0f%%) interval=%s",
            s.get("enabled"),
            s.get("record_seconds"),
            s.get("max_files_per_camera"),
            s.get("min_changed_ratio"),
            float(s.get("min_changed_ratio") or 0) * 100,
            s.get("check_interval"),
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except Exception:
                self._task.cancel()
        self.status["running"] = False
        log.info("MotionWorker stopped")


    async def _record_job(
        self,
        *,
        cam_id: str,
        cam: dict,
        side: str,
        device: str,
        rec_sec: int,
        max_files: int,
        change_pct: float,
        trigger_jpeg: bytes,
    ) -> None:
        """Background record for one camera (does not block the other)."""
        path = None
        try:
            async with _lock_for_cam(cam_id):
                await _release_device_for_record(cam_id, device)
                try:
                    path = await record_clip(cam, side, rec_sec, max_files)
                except Exception as e:
                    log.exception("record_clip failed %s: %s", cam_id, e)
                    path = None
                if path and trigger_jpeg:
                    try:
                        thumb = path.with_suffix(".jpg")
                        thumb.write_bytes(trigger_jpeg)
                        meta = path.with_suffix(".json")
                        meta.write_text(
                            json.dumps(
                                {
                                    "change_percent": round(change_pct, 2),
                                    "side": side,
                                    "cam_id": cam_id,
                                    "video": path.name,
                                },
                                ensure_ascii=False,
                            )
                            + "\n",
                            encoding="utf-8",
                        )
                        log.info("Saved trigger thumb %s (%.1f%%)", thumb.name, change_pct)
                        try:
                            cap = (
                                f"Yard {side} · {path.name}\n"
                                f"Change: {change_pct:.1f}%\n"
                                f"Cam: {cam_id}"
                            )
                            await telegram_notify.send_photo(thumb, caption=cap)
                        except Exception as e:
                            log.warning("telegram notify failed: %s", e)
                    except Exception as e:
                        log.warning("thumb save failed: %s", e)
        finally:
            self.status.setdefault("cameras", {})[cam_id] = {
                "side": side,
                "device": device,
                "state": "idle" if path else "record_failed",
                "last_file": path.name if path else None,
                "last_change_percent": round(change_pct, 2),
                "last_motion": time.time(),
            }
            log.info(
                "Record job done %s → %s",
                cam_id,
                path.name if path else "FAILED",
            )

    async def _loop(self) -> None:
        self.status["running"] = True
        prev_frames: dict[str, bytes] = {}
        last_record: dict[str, float] = {}
        warm: dict[str, int] = {}

        while not self._stop.is_set():
            settings = motion_settings()
            if not settings.get("enabled", True):
                self.status["running"] = False
                await asyncio.sleep(2)
                self.status["running"] = True
                continue

            cfg = lw.load_config()
            cams = cfg.get("cameras") or []
            max_files = int(settings.get("max_files_per_camera") or 10)
            rec_sec = int(settings.get("record_seconds") or 15)
            thr = int(settings.get("threshold") or 25)
            min_ratio = float(settings.get("min_changed_ratio") or 0.25)
            cooldown = float(settings.get("cooldown_seconds") or 20)
            interval = float(settings.get("check_interval") or 2.0)
            confirm_need = max(1, int(settings.get("confirm_hits") or 2))

            for idx, cam in enumerate(cams):
                if self._stop.is_set():
                    break
                if not cam.get("enabled", True):
                    continue
                cam_id = str(cam.get("id") or f"cam{idx}")
                side = camera_side(cam, idx)
                device = cam.get("device") or ""
                w = int(cam.get("width") or 640)
                h = int(cam.get("height") or 480)

                st = {
                    "side": side,
                    "device": device,
                    "state": "detect",
                    "last_motion": last_record.get(cam_id),
                }
                self.status["cameras"][cam_id] = st

                # skip if recently recorded
                if time.time() - last_record.get(cam_id, 0) < cooldown:
                    st["state"] = "cooldown"
                    continue

                # Only dedicated snapshots for detection (never live stream frames —
                # stream frames cause false high % from compression / reconnects)
                snap = await _grab_gray_jpeg(device, w, h)
                if not snap:
                    st["state"] = "no_frame"
                    continue

                warm[cam_id] = warm.get(cam_id, 0) + 1
                if warm[cam_id] < 2:
                    prev_frames[cam_id] = snap
                    st["state"] = "warmup"
                    continue

                prev = prev_frames.get(cam_id)
                prev_frames[cam_id] = snap
                if not prev:
                    continue

                pixel_thr = int(settings.get("threshold") or 25)
                need_pct = float(min_ratio) * 100.0  # 0.25 → 25%
                change_pct = photo_change_percent(prev, snap, pixel_threshold=pixel_thr)
                st["last_change_percent"] = round(change_pct, 2)

                # track consecutive hits above threshold
                hits = getattr(self, "_hits", None)
                if hits is None:
                    self._hits = {}
                    hits = self._hits
                if change_pct >= need_pct:
                    hits[cam_id] = hits.get(cam_id, 0) + 1
                else:
                    hits[cam_id] = 0
                    st["state"] = "idle"
                    # debug near-misses (half threshold and up)
                    if change_pct >= need_pct * 0.5:
                        log.info(
                            "Motion soft %s change=%.1f%% (need %.1f%%, hits=0)",
                            cam_id, change_pct, need_pct,
                        )
                    continue

                if hits.get(cam_id, 0) < confirm_need:
                    st["state"] = "confirm"
                    log.info(
                        "Motion confirm %s change=%.1f%% hits=%s/%s (need %.1f%%)",
                        cam_id, change_pct, hits.get(cam_id, 0), confirm_need, need_pct,
                    )
                    continue

                hits[cam_id] = 0
                log.info(
                    "Motion on %s (%s) change=%.1f%% (need >= %.1f%%)",
                    cam_id, side, change_pct, need_pct,
                )
                st["state"] = "recording"
                self.status["cameras"][cam_id] = st
                # Prevent re-trigger while background job runs
                last_record[cam_id] = time.time()
                warm[cam_id] = 0
                prev_frames.pop(cam_id, None)

                # Non-blocking: both cameras can record at the same time
                asyncio.create_task(
                    self._record_job(
                        cam_id=cam_id,
                        cam=dict(cam),
                        side=side,
                        device=device,
                        rec_sec=rec_sec,
                        max_files=max_files,
                        change_pct=change_pct,
                        trigger_jpeg=snap,
                    )
                )

            self.status["tick"] = int(self.status.get("tick") or 0) + 1
            if self.status["tick"] % 20 == 1:
                log.info(
                    "Motion tick=%s need>=%.1f%% (ratio=%s) interval=%ss cams=%s",
                    self.status["tick"],
                    min_ratio * 100.0,
                    min_ratio,
                    interval,
                    self.status.get("cameras"),
                )

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

        self.status["running"] = False


_cam_locks: dict[str, asyncio.Lock] = {}


def _lock_for_cam(cam_id: str) -> asyncio.Lock:
    """Independent lock per camera — both cams can record at once."""
    if cam_id not in _cam_locks:
        _cam_locks[cam_id] = asyncio.Lock()
    return _cam_locks[cam_id]


worker = MotionWorker()


def ensure_running() -> None:
    """Start worker if event loop is running and task is dead."""
    try:
        worker.start()
    except Exception as e:
        log.exception("MotionWorker ensure_running failed: %s", e)



def ensure_camera_sides_in_config() -> None:
    """Ensure cam1=left, cam2=right in config for UI naming."""
    try:
        cfg = lw.load_config()
        changed = False
        cams = cfg.get("cameras") or []
        for i, c in enumerate(cams):
            if not c.get("side"):
                c["side"] = "left" if i == 0 else "right"
                changed = True
        if "motion" not in cfg:
            cfg["motion"] = dict(DEFAULT_MOTION)
            changed = True
        if changed:
            lw.save_config(cfg)
    except Exception as e:
        log.exception("ensure_camera_sides_in_config failed: %s", e)

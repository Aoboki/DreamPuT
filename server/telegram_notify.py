"""Send motion alerts to Telegram (bot API)."""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("uvicorn.error")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "data" / "telegram.json"

DEFAULT = {
    "enabled": True,
    "bot_token": "",
    "chat_id": "",
    "send_photo": True,
    "send_video": False,
}


def load_config() -> dict[str, Any]:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dict(DEFAULT)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT)
        out = dict(DEFAULT)
        out.update(data)
        return out
    except Exception as e:
        log.warning("telegram config read failed: %s", e)
        return dict(DEFAULT)


def save_config(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT)
    out.update(data or {})
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _http_json(url: str, data: Optional[bytes] = None, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_updates_chat_ids(token: str) -> list[dict[str, Any]]:
    """Return recent chats that messaged the bot (for discovering chat_id)."""
    url = _api(token, "getUpdates")
    try:
        data = _http_json(url, timeout=15)
    except Exception as e:
        log.error("telegram getUpdates failed: %s", e)
        return []
    if not data.get("ok"):
        return []
    found: dict[str, dict[str, Any]] = {}
    for u in data.get("result") or []:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        found[str(cid)] = {
            "chat_id": cid,
            "type": chat.get("type"),
            "title": chat.get("title")
            or chat.get("username")
            or chat.get("first_name")
            or "",
        }
    return list(found.values())


async def send_photo(
    photo_path: Path,
    caption: str = "",
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> bool:
    cfg = load_config()
    if not cfg.get("enabled", True) or not cfg.get("send_photo", True):
        return False
    token = (token or cfg.get("bot_token") or "").strip()
    chat_id = str(chat_id or cfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        log.warning("telegram: bot_token or chat_id missing — skip send")
        return False
    if not photo_path.is_file():
        log.warning("telegram: photo missing %s", photo_path)
        return False

    def _do() -> bool:
        boundary = "----DreamPUTBoundary7MA4YWxkTrZu0gW"
        photo_bytes = photo_path.read_bytes()

        def field(name: str, value: str) -> bytes:
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()

        body = b""
        body += field("chat_id", str(chat_id))
        if caption:
            body += field("caption", caption[:1000])
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="{photo_path.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode()
        body += photo_bytes
        body += f"\r\n--{boundary}--\r\n".encode()
        url = _api(token, "sendPhoto")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                log.info("telegram: photo sent to %s (%s)", chat_id, photo_path.name)
                return True
            log.error("telegram: sendPhoto not ok: %s", data)
            return False
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", "replace")[:300]
            log.error("telegram HTTP %s: %s", e.code, err)
            return False
        except Exception as e:
            log.error("telegram send failed: %s", e)
            return False

    return await asyncio.to_thread(_do)

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import uuid
from pathlib import Path

import websockets
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.contrib.media import MediaPlayer


# ============================================================
# CONFIGURATION
# ============================================================

HOST_ID = (
    sys.argv[1]
    if len(sys.argv) > 1
    else socket.gethostname().lower()
)

SERVER_URL = f"wss://remote.aoboki.pp.ua/ws/webcam/host/{HOST_ID}"

# Путь к файлу с устройствами
DEVICES_FILE = Path(__file__).resolve().parent / "devices.txt"


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

log = logging.getLogger("webcam")


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



# ============================================================
# GLOBAL STATE
# ============================================================

websocket = None
shutdown_event = asyncio.Event()

# Один MediaPlayer для камеры на всех зрителей
media_player = None

# Отдельный MediaPlayer для микрофона
audio_player = None

# Активные сессии зрителей
#
# {
#     "viewer_id": {
#         "pc": RTCPeerConnection,
#     }
# }
#
sessions = {}

session_lock = asyncio.Lock()


# ============================================================
# ЧТЕНИЕ УСТРОЙСТВ ИЗ devices.txt
# ============================================================

def load_devices():
    """
    Читает названия камеры и микрофона из devices.txt.

    Формат:

    CAMERA_DEVICE=video=Integrated Webcam
    AUDIO_DEVICE=audio=Microphone (Realtek(R) Audio)
    """

    camera = "video=Integrated Webcam"
    audio = None

    if not DEVICES_FILE.exists():
        log.warning(
            "⚠️ devices.txt не найден, используются значения по умолчанию"
        )
        return camera, audio

    try:
        with open(DEVICES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()

                if (
                    not line
                    or line.startswith("#")
                    or "=" not in line
                ):
                    continue

                key, value = line.split("=", 1)

                key = key.strip().upper()
                value = value.strip()

                if key == "CAMERA_DEVICE":
                    camera = value

                elif key == "AUDIO_DEVICE":
                    audio = value

        log.info("📁 Устройства загружены из devices.txt")
        log.info("   Camera: %s", camera)

        if audio:
            log.info("   Audio:  %s", audio)
        else:
            log.info("   Audio:  ОТКЛЮЧЁН")

    except Exception as e:
        log.error("❌ Ошибка чтения devices.txt: %s", e)

    return camera, audio


CAMERA_DEVICE, AUDIO_DEVICE = load_devices()

AUDIO_ENABLED = bool(AUDIO_DEVICE)


# ============================================================
# HELPERS
# ============================================================

def log_header():
    log.info("========================================")
    log.info("        Remote Desktop Webcam")
    log.info("========================================")
    log.info("🆔 HOST_ID: %s", HOST_ID)
    log.info("🌐 Server: %s", SERVER_URL)
    log.info("📷 Camera: %s", CAMERA_DEVICE)

    if AUDIO_ENABLED:
        log.info("🎤 Audio:  ENABLED")
        log.info("🎤 Device: %s", AUDIO_DEVICE)
    else:
        log.info("🎤 Audio:  DISABLED")

    log.info("========================================")


async def send_json(data: dict) -> bool:
    global websocket

    ws = websocket

    if ws is None:
        return False

    try:
        await ws.send(
            json.dumps(
                data,
                ensure_ascii=False,
            )
        )
        return True

    except Exception as e:
        log.warning(
            "⚠️ WebSocket send failed: %s",
            e,
        )
        return False


# ============================================================
# MEDIA
# ============================================================

def open_media_player():
    """
    Открывает камеру один раз.

    Видео и аудио открываются отдельными MediaPlayer:
    
        camera_player -> video
        audio_player  -> audio

    Это надёжнее для Windows DirectShow,
    чем пытаться открыть камеру и микрофон
    одним MediaPlayer.
    """

    global media_player
    global audio_player

    # --------------------------------------------------------
    # Если камера уже открыта
    # --------------------------------------------------------

    if media_player is not None:
        return media_player

    # --------------------------------------------------------
    # Открываем камеру
    # --------------------------------------------------------

    log.info("📷 Открываю камеру: %s", CAMERA_DEVICE)

    video_options = {
        "framerate": "30",
        "video_size": "640x480",
    }

    try:
        player = MediaPlayer(
            CAMERA_DEVICE,
            format="dshow",
            options=video_options,
        )

    except Exception as e:
        log.error(
            "❌ Не удалось открыть камеру: %s: %s",
            type(e).__name__,
            e,
        )
        return None

    # --------------------------------------------------------
    # Проверяем video track
    # --------------------------------------------------------

    if player.video is None:
        log.error(
            "❌ Камера открылась, но video track отсутствует"
        )

        try:
            player.stop()
        except Exception:
            pass

        return None

    media_player = player

    log.info("🟢 Камера успешно открыта")

    # --------------------------------------------------------
    # Открываем микрофон отдельно
    # --------------------------------------------------------

    if AUDIO_ENABLED and AUDIO_DEVICE:
        log.info(
            "🎤 Открываю микрофон: %s",
            AUDIO_DEVICE,
        )

        try:
            audio_player_instance = MediaPlayer(
                AUDIO_DEVICE,
                format="dshow",
            )

            if audio_player_instance.audio is not None:
                audio_player = audio_player_instance

                log.info(
                    "🟢 Микрофон успешно открыт"
                )

                log.info(
                    "🎤 Audio track готов"
                )

            else:
                log.error(
                    "❌ Микрофон открылся, "
                    "но audio track отсутствует"
                )

                try:
                    audio_player_instance.stop()
                except Exception:
                    pass

                audio_player = None

        except Exception as e:
            # Очень важно:
            # ошибка микрофона НЕ должна ломать видео.

            log.error(
                "❌ Не удалось открыть микрофон: %s: %s",
                type(e).__name__,
                e,
            )

            log.warning(
                "⚠️ Видео продолжит работать без аудио"
            )

            audio_player = None

    else:
        log.info(
            "🎤 Аудио отключено"
        )

    return media_player


# ============================================================
# CLOSE MEDIA
# ============================================================

async def close_all_media():
    """
    Закрывает все PeerConnection,
    камеру и микрофон.
    """

    global media_player
    global audio_player

    async with session_lock:

        viewer_ids = list(sessions.keys())

        for vid in viewer_ids:
            await _close_session(vid)

        # ----------------------------------------------------
        # Закрываем камеру
        # ----------------------------------------------------

        if media_player is not None:

            log.info(
                "⏹ Закрываю камеру..."
            )

            try:
                if media_player.video is not None:
                    media_player.video.stop()
            except Exception:
                pass

            try:
                if hasattr(media_player, "stop"):
                    media_player.stop()
            except Exception:
                pass

            media_player = None

            log.info(
                "🔴 Камера закрыта"
            )

        # ----------------------------------------------------
        # Закрываем микрофон
        # ----------------------------------------------------

        if audio_player is not None:

            log.info(
                "⏹ Закрываю микрофон..."
            )

            try:
                if audio_player.audio is not None:
                    audio_player.audio.stop()
            except Exception:
                pass

            try:
                if hasattr(audio_player, "stop"):
                    audio_player.stop()
            except Exception:
                pass

            audio_player = None

            log.info(
                "🔴 Микрофон закрыт"
            )


async def _close_session(viewer_id: str):
    """
    Закрывает одну сессию зрителя.
    """

    session = sessions.pop(
        viewer_id,
        None,
    )

    if not session:
        return

    pc = session.get("pc")

    if pc:
        try:
            await pc.close()
        except Exception:
            pass

    log.info(
        "🔴 Сессия зрителя закрыта: %s",
        viewer_id,
    )


# ============================================================
# СОЗДАНИЕ СЕССИИ ДЛЯ ЗРИТЕЛЯ
# ============================================================

async def create_session_for_viewer(viewer_id: str):

    async with session_lock:

        # ----------------------------------------------------
        # Проверяем существующую сессию
        # ----------------------------------------------------

        if viewer_id in sessions:

            log.warning(
                "⚠️ Сессия %s уже существует",
                viewer_id,
            )

            return

        # ----------------------------------------------------
        # Открываем камеру и микрофон
        # ----------------------------------------------------

        player = open_media_player()

        if player is None:

            await send_json(
                {
                    "type": "error",
                    "viewer_id": viewer_id,
                    "message": "Camera unavailable",
                }
            )

            return

        # ----------------------------------------------------
        # Создаём PeerConnection
        # ----------------------------------------------------

        log.info(
            "🔗 Создаю WebRTC сессию для зрителя: %s",
            viewer_id,
        )

       
        pc = RTCPeerConnection(
            RTCConfiguration(
                iceServers=fetch_ice_servers()
            )
        )

        # ----------------------------------------------------
        # VIDEO TRACK
        # ----------------------------------------------------

        if player.video is not None:

            pc.addTrack(
                player.video
            )

            log.info(
                "🎥 Video track добавлен"
            )

        else:

            log.error(
                "❌ Video track отсутствует"
            )

        # ----------------------------------------------------
        # AUDIO TRACK
        # ----------------------------------------------------

        if AUDIO_ENABLED:

            if audio_player is not None:

                if audio_player.audio is not None:

                    try:
                        pc.addTrack(
                            audio_player.audio
                        )

                        log.info(
                            "🎤 Audio track добавлен "
                            "для зрителя %s",
                            viewer_id,
                        )

                    except Exception as e:

                        log.error(
                            "❌ Ошибка добавления audio track: "
                            "%s: %s",
                            type(e).__name__,
                            e,
                        )

                else:

                    log.warning(
                        "⚠️ audio_player существует, "
                        "но audio track отсутствует"
                    )

            else:

                log.warning(
                    "⚠️ Микрофон недоступен. "
                    "Зритель получит только видео."
                )

        else:

            log.info(
                "🎤 Audio track не добавляется "
                "(аудио отключено)"
            )

        # ----------------------------------------------------
        # Сохраняем сессию
        # ----------------------------------------------------

        sessions[viewer_id] = {
            "pc": pc
        }

        # ----------------------------------------------------
        # Логирование состояния WebRTC
        # ----------------------------------------------------

        @pc.on("connectionstatechange")
        async def on_state_change():

            log.info(
                "WebRTC [%s] state: %s",
                viewer_id,
                pc.connectionState,
            )

            if pc.connectionState in (
                "failed",
                "closed",
                "disconnected",
            ):

                await _close_session(
                    viewer_id
                )

        # ----------------------------------------------------
        # ICE состояние
        # ----------------------------------------------------

        @pc.on("iceconnectionstatechange")
        async def on_ice_state_change():

            log.info(
                "WebRTC [%s] ICE state: %s",
                viewer_id,
                pc.iceConnectionState,
            )

        # ----------------------------------------------------
        # Trickle ICE — отправляем кандидаты зрителю
        # ----------------------------------------------------

        @pc.on("icecandidate")
        async def on_icecandidate(candidate):

            if candidate is None:
                log.info(
                    "🧊 ICE gathering complete [%s]",
                    viewer_id,
                )
                # Сообщаем браузеру об окончании сбора кандидатов
                try:
                    await send_json(
                        {
                            "type": "candidate",
                            "host_id": HOST_ID,
                            "viewer_id": viewer_id,
                            "candidate": None,
                        }
                    )
                except Exception:
                    pass
                return

            try:
                # Собираем SDP-строку кандидата в формате, понятном браузеру
                # foundation component protocol priority ip port typ type ...
                related = ""
                if getattr(candidate, "relatedAddress", None) and getattr(candidate, "relatedPort", None):
                    related = f" raddr {candidate.relatedAddress} rport {candidate.relatedPort}"

                tcp_type = ""
                if getattr(candidate, "tcpType", None):
                    tcp_type = f" tcptype {candidate.tcpType}"

                cand_str = (
                    f"candidate:{candidate.foundation} {candidate.component} "
                    f"{candidate.protocol} {candidate.priority} "
                    f"{candidate.ip} {candidate.port} typ {candidate.type}"
                    f"{related}{tcp_type}"
                )

                cand_dict = {
                    "candidate": cand_str,
                    "sdpMid": candidate.sdpMid,
                    "sdpMLineIndex": candidate.sdpMLineIndex,
                }

                await send_json(
                    {
                        "type": "candidate",
                        "host_id": HOST_ID,
                        "viewer_id": viewer_id,
                        "candidate": cand_dict,
                    }
                )

                log.info(
                    "🧊 ICE candidate sent [%s] %s",
                    viewer_id,
                    candidate.type,
                )

            except Exception as e:
                log.error(
                    "❌ Ошибка отправки ICE candidate: %s",
                    e,
                )

        # ----------------------------------------------------
        # Создаём offer
        # ----------------------------------------------------

        try:

            offer = await pc.createOffer()

            await pc.setLocalDescription(
                offer
            )

        except Exception as e:

            log.error(
                "❌ Ошибка создания offer: %s",
                e,
            )

            await _close_session(
                viewer_id
            )

            return

        # ----------------------------------------------------
        # Диагностика SDP
        # ----------------------------------------------------

        sdp = pc.localDescription.sdp or ""
        has_audio = "m=audio" in sdp
        has_video = "m=video" in sdp

        log.info(
            "📄 Offer SDP: video=%s audio=%s (viewer=%s)",
            has_video,
            has_audio,
            viewer_id,
        )

        if AUDIO_ENABLED and not has_audio:
            log.error(
                "❌ Аудио включено, но m=audio отсутствует в SDP!"
            )

        # ----------------------------------------------------
        # Отправляем offer серверу
        # ----------------------------------------------------

        await send_json(
            {
                "type": "offer",
                "host_id": HOST_ID,
                "viewer_id": viewer_id,
                "sdp": pc.localDescription.sdp,
            }
        )

        log.info(
            "📤 Offer отправлен для зрителя %s",
            viewer_id,
        )

        log.info(
            "👥 Текущее количество зрителей: %d",
            len(sessions),
        )


# ============================================================
# ОБРАБОТКА СООБЩЕНИЙ ОТ СЕРВЕРА
# ============================================================

async def handle_message(message: dict):

    msg_type = message.get(
        "type"
    )

    viewer_id = message.get(
        "viewer_id"
    )

    log.info(
        "📩 Сообщение: %s (viewer=%s)",
        msg_type,
        viewer_id,
    )

    # --------------------------------------------------------
    # Новый зритель
    # --------------------------------------------------------

    if msg_type == "viewer_ready":

        if not viewer_id:
            viewer_id = str(
                uuid.uuid4()
            )

        await create_session_for_viewer(
            viewer_id
        )

        return

    # --------------------------------------------------------
    # Зритель ушёл
    # --------------------------------------------------------

    if msg_type in (
        "viewer_left",
        "viewer_closed",
        "viewer_disconnect",
        "viewer_disconnected",
    ):

        if viewer_id:

            async with session_lock:

                await _close_session(
                    viewer_id
                )

            log.info(
                "👥 Зрителей осталось: %d",
                len(sessions),
            )

        return

    # --------------------------------------------------------
    # Answer от браузера
    # --------------------------------------------------------

    if msg_type == "answer":

        if not viewer_id:

            log.warning(
                "⚠️ Answer без viewer_id"
            )

            return

        async with session_lock:

            session = sessions.get(
                viewer_id
            )

            if not session:

                log.warning(
                    "⚠️ Answer для неизвестного "
                    "зрителя: %s",
                    viewer_id,
                )

                return

            pc = session["pc"]

            if pc.signalingState != "have-local-offer":

                log.warning(
                    "⚠️ Игнорирую повторный/поздний "
                    "answer (%s)",
                    pc.signalingState,
                )

                return

            sdp = message.get(
                "sdp"
            )

            if not sdp:
                return

            try:

                await pc.setRemoteDescription(
                    RTCSessionDescription(
                        sdp=sdp,
                        type="answer",
                    )
                )

                log.info(
                    "🟢 Answer принят для %s",
                    viewer_id,
                )

            except Exception as e:

                log.error(
                    "❌ Ошибка setRemoteDescription: %s",
                    e,
                )

                await _close_session(
                    viewer_id
                )

        return

    # --------------------------------------------------------
    # ICE candidate от браузера
    # --------------------------------------------------------

    if msg_type == "candidate":

        if not viewer_id:
            log.warning("⚠️ Candidate без viewer_id")
            return

        async with session_lock:

            session = sessions.get(viewer_id)

            if not session:
                log.warning(
                    "⚠️ Candidate для неизвестного зрителя: %s",
                    viewer_id,
                )
                return

            pc = session["pc"]
            cand = message.get("candidate")

            try:
                from aiortc.sdp import candidate_from_sdp

                # end-of-candidates
                if cand is None or (
                    isinstance(cand, dict)
                    and not (cand.get("candidate") or "").strip()
                ):
                    await pc.addIceCandidate(None)
                    log.info("🧊 end-of-candidates [%s]", viewer_id)
                    return

                if isinstance(cand, dict):
                    raw = cand.get("candidate") or ""
                    # candidate_from_sdp ожидает строку БЕЗ префикса "candidate:"
                    sdp_str = raw
                    if sdp_str.startswith("candidate:"):
                        sdp_str = sdp_str[len("candidate:"):]

                    ice_cand = candidate_from_sdp(sdp_str)
                    ice_cand.sdpMid = cand.get("sdpMid")
                    ice_cand.sdpMLineIndex = cand.get("sdpMLineIndex")
                    await pc.addIceCandidate(ice_cand)
                else:
                    await pc.addIceCandidate(cand)

                log.info(
                    "🧊 ICE candidate добавлен [%s]",
                    viewer_id,
                )

            except Exception as e:
                log.error(
                    "❌ Ошибка addIceCandidate: %s: %s",
                    type(e).__name__,
                    e,
                )

        return

    # --------------------------------------------------------
    # Остановка
    # --------------------------------------------------------

    if msg_type in (
        "webcam_stop",
        "stop",
    ):

        log.info(
            "🛑 Получена команда остановки"
        )

        await close_all_media()

        return

    # --------------------------------------------------------
    # Неизвестный тип
    # --------------------------------------------------------

    log.warning(
        "⚠️ Неизвестный тип сообщения: %s",
        msg_type,
    )


# ============================================================
# ПРОВЕРКА ЗРИТЕЛЕЙ КАЖДЫЕ 30 СЕКУНД
# ============================================================

async def viewers_watchdog():

    """
    Каждые 30 секунд проверяет количество зрителей.

    Если зрителей 0 —
    останавливает камеру и микрофон.
    """

    while not shutdown_event.is_set():

        try:

            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=30,
            )

        except asyncio.TimeoutError:
            pass

        if shutdown_event.is_set():
            break

        count = len(
            sessions
        )

        log.info(
            "👥 Проверка зрителей: %d",
            count,
        )

        if (
            count == 0
            and (
                media_player is not None
                or audio_player is not None
            )
        ):

            log.info(
                "⏹ Зрителей нет → "
                "останавливаю трансляцию"
            )

            await close_all_media()


# ============================================================
# WEBSOCKET CONNECTION
# ============================================================

async def webcam_connection():

    global websocket

    while not shutdown_event.is_set():

        try:

            log.info(
                "🔌 Подключаюсь к серверу..."
            )

            async with websockets.connect(
                SERVER_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=10 * 1024 * 1024,
            ) as ws:

                websocket = ws

                log.info(
                    "🟢 Канал вебкамеры подключён"
                )

                # ------------------------------------------------
                # Сообщаем серверу, что мы онлайн
                # ------------------------------------------------

                await send_json(
                    {
                        "type": "webcam_status",
                        "host_id": HOST_ID,
                        "status": "running",
                        "viewers": len(sessions),
                    }
                )

                log.info(
                    "🎧 Ожидаю зрителей..."
                )

                # ------------------------------------------------
                # Получаем сообщения сервера
                # ------------------------------------------------

                async for raw in ws:

                    try:

                        if isinstance(
                            raw,
                            bytes,
                        ):
                            raw = raw.decode(
                                "utf-8"
                            )

                        message = json.loads(
                            raw
                        )

                    except Exception as e:

                        log.warning(
                            "⚠️ Некорректное сообщение: %s",
                            e,
                        )

                        continue

                    try:

                        await handle_message(
                            message
                        )

                    except Exception as e:

                        log.error(
                            "❌ Ошибка обработки: %s: %s",
                            type(e).__name__,
                            e,
                        )

        except asyncio.CancelledError:

            raise

        except Exception as e:

            if shutdown_event.is_set():
                break

            log.error(
                "🔴 Соединение потеряно: %s: %s",
                type(e).__name__,
                e,
            )

            await close_all_media()

            log.info(
                "🔄 Переподключение через 3 секунды..."
            )

            try:

                await asyncio.wait_for(
                    shutdown_event.wait(),
                    timeout=3,
                )

            except asyncio.TimeoutError:
                pass

        finally:

            websocket = None

    log.info(
        "🔴 Канал вебкамеры остановлен"
    )


# ============================================================
# SHUTDOWN
# ============================================================

async def shutdown():

    global websocket

    if shutdown_event.is_set():
        return

    log.info(
        "🛑 Завершение работы..."
    )

    shutdown_event.set()

    await close_all_media()

    if websocket is not None:

        try:
            await websocket.close()
        except Exception:
            pass

        websocket = None


# ============================================================
# SIGNAL HANDLERS
# ============================================================

def install_signal_handlers(loop):

    def handler():

        asyncio.create_task(
            shutdown()
        )

    try:

        loop.add_signal_handler(
            signal.SIGINT,
            handler,
        )

        loop.add_signal_handler(
            signal.SIGTERM,
            handler,
        )

    except NotImplementedError:

        # Windows
        pass


# ============================================================
# MAIN
# ============================================================

async def main():

    log_header()

    loop = asyncio.get_running_loop()

    install_signal_handlers(
        loop
    )

    conn_task = asyncio.create_task(
        webcam_connection()
    )

    watchdog_task = asyncio.create_task(
        viewers_watchdog()
    )

    try:

        await shutdown_event.wait()

    except KeyboardInterrupt:

        pass

    finally:

        conn_task.cancel()

        watchdog_task.cancel()

        await asyncio.gather(
            conn_task,
            watchdog_task,
            return_exceptions=True,
        )

        await shutdown()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\n🛑 Webcam stopped"
        )

    except Exception as e:

        print(
            f"❌ Fatal error: "
            f"{type(e).__name__}: {e}"
        )

        sys.exit(1)


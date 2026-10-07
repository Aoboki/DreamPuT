
import json
import uuid
import asyncio

from fastapi import WebSocket, WebSocketDisconnect


# ============================================================
# ACTIVE CONNECTIONS
# ============================================================

# host_id → WebSocket хоста
host_connections = {}

# host_id → { viewer_id: WebSocket }
browser_connections = {}


# ============================================================
# BROWSER (зритель)
# ============================================================

async def webcam_browser(websocket: WebSocket, host_id: str):
    await websocket.accept()
    host_id = str(host_id).strip()

    # Генерируем уникальный ID для этого зрителя
    viewer_id = str(uuid.uuid4())

    # Добавляем зрителя
    if host_id not in browser_connections:
        browser_connections[host_id] = {}

    browser_connections[host_id][viewer_id] = websocket

    print(f"📺 Webcam browser connected: {host_id} (viewer={viewer_id})")
    print(f"   Всего зрителей на {host_id}: {len(browser_connections[host_id])}")

    try:
        # Сообщаем хосту, что появился новый зритель
        # host_ws = host_connections.get(host_id)
        # ----------------------------------------------------
        # Ждём, пока webcam.py подключится (максимум 8 секунд)
        # ----------------------------------------------------
        host_ws = None
        for _ in range(16):          # 16 × 0.5 сек = 8 секунд
            host_ws = host_connections.get(host_id)
            if host_ws:
                break
            await asyncio.sleep(0.5)
            
        if host_ws:
            await host_ws.send_text(json.dumps({
                "type": "viewer_ready",
                "host_id": host_id,
                "viewer_id": viewer_id,
            }, ensure_ascii=False))

            print(f"📡 viewer_ready отправлен хосту {host_id} (viewer={viewer_id})")
        else:
            print(f"⚠️ Webcam host offline: {host_id}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Webcam host is offline",
            }, ensure_ascii=False))

        # Основной цикл — пересылаем сигналинг от браузера к хосту
        while True:
            message = await websocket.receive_text()

            try:
                data = json.loads(message)
                message_type = data.get("type")
            except Exception:
                data = None
                message_type = None

            # Добавляем viewer_id, если его нет
            if data is not None and "viewer_id" not in data:
                data["viewer_id"] = viewer_id
                message = json.dumps(data, ensure_ascii=False)

            print(f"📩 Browser → Host: {message_type} (viewer={viewer_id})")

            host_ws = host_connections.get(host_id)
            if host_ws:
                try:
                    await host_ws.send_text(message)
                except Exception as e:
                    print(f"❌ Browser → Host error: {type(e).__name__}: {e}")
            else:
                print(f"⚠️ Нет хоста для {host_id}")

    except WebSocketDisconnect:
        print(f"🔴 Webcam browser disconnected: {host_id} (viewer={viewer_id})")

    except Exception as e:
        print(f"❌ Webcam browser error {host_id}: {type(e).__name__}: {e}")

    finally:
        # Удаляем зрителя
        viewers = browser_connections.get(host_id, {})
        if viewers.get(viewer_id) is websocket:
            viewers.pop(viewer_id, None)

            # Если зрителей больше нет — удаляем ключ
            if not viewers:
                browser_connections.pop(host_id, None)

            print(f"🧹 Зритель удалён: {viewer_id}")
            print(f"   Осталось зрителей на {host_id}: {len(browser_connections.get(host_id, {}))}")

            # Сообщаем хосту, что зритель ушёл
            host_ws = host_connections.get(host_id)
            if host_ws:
                try:
                    await host_ws.send_text(json.dumps({
                        "type": "viewer_left",
                        "host_id": host_id,
                        "viewer_id": viewer_id,
                    }, ensure_ascii=False))
                    print(f"📡 viewer_left отправлен хосту {host_id}")
                except Exception:
                    pass
            # Если зрителей больше не осталось — останавливаем webcam.py через host.py
            remaining = len(browser_connections.get(host_id, {}))
            if remaining == 0:
                print(f"⏹ Зрителей не осталось → останавливаем webcam.py на {host_id}")

                # Отправляем команду главному host.py
                from app import connected_hosts, send_host_command   # или как у тебя называется

                try:
                    await send_host_command(host_id, "webcam_stop")
                    print(f"📡 webcam_stop отправлен host.py ({host_id})")
                except Exception as e:
                    print(f"❌ Не удалось отправить webcam_stop: {e}")

# ============================================================
# WINDOWS HOST
# ============================================================

async def webcam_host(websocket: WebSocket, host_id: str):
    await websocket.accept()
    host_id = str(host_id).strip()

    # Заменяем старое подключение хоста
    old_host = host_connections.get(host_id)
    if old_host and old_host is not websocket:
        try:
            await old_host.close()
        except Exception:
            pass

    host_connections[host_id] = websocket
    print(f"🟢 Webcam host connected: {host_id}")

    try:
        while True:
            message = await websocket.receive_text()

            try:
                data = json.loads(message)
                message_type = data.get("type")
                viewer_id = data.get("viewer_id")
            except Exception:
                data = None
                message_type = None
                viewer_id = None

            print(f"📩 Host → Browser: {message_type} (viewer={viewer_id})")

            # Если это статус — просто логируем
            if message_type == "webcam_status":
                print(f"   Статус хоста: {data.get('status')}, зрителей: {data.get('viewers')}")
                continue

            # Пересылаем конкретному зрителю или всем
            viewers = browser_connections.get(host_id, {})

            if not viewers:
                print(f"⚠️ Нет зрителей для хоста {host_id}")
                continue

            if viewer_id and viewer_id in viewers:
                # Отправляем конкретному зрителю
                try:
                    await viewers[viewer_id].send_text(message)
                    print(f"📤 Отправлено зрителю {viewer_id}")
                except Exception as e:
                    print(f"❌ Ошибка отправки зрителю {viewer_id}: {e}")
                    viewers.pop(viewer_id, None)
            else:
                # Рассылка всем (на всякий случай)
                dead = []
                for vid, ws in viewers.items():
                    try:
                        await ws.send_text(message)
                    except Exception:
                        dead.append(vid)
                for vid in dead:
                    viewers.pop(vid, None)

    except WebSocketDisconnect:
        print(f"🔴 Webcam host disconnected: {host_id}")

    except Exception as e:
        print(f"❌ Webcam host error {host_id}: {type(e).__name__}: {e}")

    finally:
        if host_connections.get(host_id) is websocket:
            host_connections.pop(host_id, None)
            print(f"🧹 Webcam host removed: {host_id}")
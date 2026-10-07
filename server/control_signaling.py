import json
import uuid
import asyncio
from fastapi import WebSocket, WebSocketDisconnect

# host_id -> WebSocket
host_connections = {}
# host_id -> { viewer_id: WebSocket }
browser_connections = {}


async def control_browser(websocket: WebSocket, host_id: str):
    await websocket.accept()
    host_id = str(host_id).strip()
    viewer_id = str(uuid.uuid4())

    if host_id not in browser_connections:
        browser_connections[host_id] = {}
    browser_connections[host_id][viewer_id] = websocket

    print(f"🎮 Control browser connected: {host_id} viewer={viewer_id}")

    try:
        host_ws = None
        for _ in range(20):
            host_ws = host_connections.get(host_id)
            if host_ws:
                break
            # case-insensitive
            for k, v in host_connections.items():
                if str(k).lower() == host_id.lower():
                    host_ws = v
                    host_id = k
                    break
            if host_ws:
                break
            await asyncio.sleep(0.5)

        if host_ws:
            await host_ws.send_text(json.dumps({
                "type": "viewer_ready",
                "host_id": host_id,
                "viewer_id": viewer_id,
            }, ensure_ascii=False))
        else:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Control host offline",
            }, ensure_ascii=False))

        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
                message_type = data.get("type")
            except Exception:
                data = None
                message_type = None

            if data is not None and "viewer_id" not in data:
                data["viewer_id"] = viewer_id
                message = json.dumps(data, ensure_ascii=False)

            # Input events go to main host process (mouse/keyboard)
            if message_type == "input":
                try:
                    from app import connected_hosts
                    host = connected_hosts.get(host_id)
                    if not host:
                        for k, v in connected_hosts.items():
                            if str(k).lower() == host_id.lower():
                                host = v
                                break
                    if host and host.get("websocket"):
                        await host["websocket"].send_text(json.dumps({
                            "command": "input",
                            "action": data.get("action"),
                            "x": data.get("x"),
                            "y": data.get("y"),
                            "button": data.get("button"),
                            "key": data.get("key"),
                            "code": data.get("code"),
                            "ctrl": data.get("ctrl"),
                            "alt": data.get("alt"),
                            "shift": data.get("shift"),
                            "meta": data.get("meta"),
                            "deltaX": data.get("deltaX"),
                            "deltaY": data.get("deltaY"),
                        }, ensure_ascii=False))
                except Exception as e:
                    print(f"❌ control input forward: {e}")
                continue

            host_ws = host_connections.get(host_id)
            if not host_ws:
                for k, v in host_connections.items():
                    if str(k).lower() == host_id.lower():
                        host_ws = v
                        break
            if host_ws:
                try:
                    await host_ws.send_text(message)
                except Exception as e:
                    print(f"❌ Browser→Host control: {e}")

    except WebSocketDisconnect:
        print(f"🔴 Control browser disconnected: {host_id}")
    except Exception as e:
        print(f"❌ Control browser error: {e}")
    finally:
        viewers = browser_connections.get(host_id, {})
        if viewers.get(viewer_id) is websocket:
            viewers.pop(viewer_id, None)
            if not viewers:
                browser_connections.pop(host_id, None)
            host_ws = host_connections.get(host_id)
            if host_ws:
                try:
                    await host_ws.send_text(json.dumps({
                        "type": "viewer_left",
                        "host_id": host_id,
                        "viewer_id": viewer_id,
                    }, ensure_ascii=False))
                except Exception:
                    pass
            if not browser_connections.get(host_id):
                try:
                    from app import send_host_command
                    await send_host_command(host_id, "control_stop")
                except Exception:
                    pass


async def control_host(websocket: WebSocket, host_id: str):
    await websocket.accept()
    host_id = str(host_id).strip()

    old = host_connections.get(host_id)
    if old and old is not websocket:
        try:
            await old.close()
        except Exception:
            pass

    host_connections[host_id] = websocket
    print(f"🟢 ControlStream host connected: {host_id}")

    try:
        while True:
            message = await websocket.receive_text()
            try:
                data = json.loads(message)
                message_type = data.get("type")
                viewer_id = data.get("viewer_id")
            except Exception:
                continue

            if message_type == "control_status":
                print(f"   status: {data.get('status')}")
                continue

            viewers = browser_connections.get(host_id, {})
            if not viewers:
                # case-insensitive viewers key
                for k, v in browser_connections.items():
                    if str(k).lower() == host_id.lower():
                        viewers = v
                        break

            if viewer_id and viewer_id in viewers:
                try:
                    await viewers[viewer_id].send_text(message)
                except Exception:
                    viewers.pop(viewer_id, None)
            else:
                dead = []
                for vid, ws in list(viewers.items()):
                    try:
                        await ws.send_text(message)
                    except Exception:
                        dead.append(vid)
                for vid in dead:
                    viewers.pop(vid, None)

    except WebSocketDisconnect:
        print(f"🔴 ControlStream host disconnected: {host_id}")
    except Exception as e:
        print(f"❌ ControlStream host error: {e}")
    finally:
        if host_connections.get(host_id) is websocket:
            host_connections.pop(host_id, None)

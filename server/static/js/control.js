"use strict";

(function () {
    const params = new URLSearchParams(window.location.search);
    const HOST_ID = (params.get("host") || "").trim();

    const MOVE_THROTTLE_MS = 20;
    let ICE_SERVERS = [
        { urls: "stun:stun.l.google.com:19302" },
        { urls: "stun:stun1.l.google.com:19302" }
    ];

    async function loadIceServers() {
        try {
            const res = await fetch("/api/webrtc/ice-servers", { credentials: "same-origin" });
            const data = await res.json();
            if (data && Array.isArray(data.iceServers) && data.iceServers.length) {
                ICE_SERVERS = data.iceServers;
                console.log("🧊 ICE servers loaded:", ICE_SERVERS.length, "turn=", data.turn, data.provider);
                if (data.turn === false) {
                    console.warn("⚠️ No TURN credentials — home NAT may fail. Check /api/webrtc/ice-servers and turn_cloudflare.txt");
                }
            }
        } catch (e) {
            console.warn("ICE servers fetch failed, using STUN only", e);
        }
        return ICE_SERVERS;
    }


    function sendQuality(preset) {
        const q = preset || (document.getElementById("quality-select") || {}).value || "high";
        sendJson({ type: "quality", host_id: HOST_ID, quality: q });
        console.log("🎚 quality ->", q);
    }

    function bindQualitySelect() {
        const sel = document.getElementById("quality-select");
        if (!sel) return;
        sel.addEventListener("change", function () {
            if (running) sendQuality(sel.value);
        });
    }


    let socket = null;
    let pc = null;
    let running = false;
    let inputActive = false;
    let remoteW = 1920;
    let remoteH = 1080;
    let lastMoveSent = 0;
    let pendingMove = null;
    let moveTimer = null;

    const screen = document.getElementById("screen");
    const stage = document.getElementById("stage");
    const placeholder = document.getElementById("placeholder");
    const btnStart = document.getElementById("btn-start");
    const btnStop = document.getElementById("btn-stop");
    const connStatus = document.getElementById("conn-status");
    const connText = document.getElementById("conn-text");
    const hostTitle = document.getElementById("host-title");
    const hostSub = document.getElementById("host-sub");
    const toastEl = document.getElementById("toast");
    const localCursor = document.getElementById("local-cursor");

    function toast(msg, type) {
        if (!toastEl) return;
        toastEl.textContent = msg;
        toastEl.className = "toast show" + (type ? " " + type : "");
        clearTimeout(toast._t);
        toast._t = setTimeout(function () {
            toastEl.classList.remove("show");
        }, 2800);
    }

    function setStatus(kind, text) {
        connStatus.className = "status " + (kind || "");
        connText.textContent = text || "";
    }

    function controlWsUrl() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        return proto + "//" + location.host + "/ws/control/browser/" + encodeURIComponent(HOST_ID);
    }

    function sendJson(obj) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return false;
        try {
            socket.send(JSON.stringify(obj));
            return true;
        } catch (e) {
            return false;
        }
    }

    function mapToRemote(clientX, clientY) {
        if (!screen || !remoteW || !remoteH) return null;
        const rect = screen.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return null;
        const naturalW = screen.videoWidth || screen.naturalWidth || remoteW;
        const naturalH = screen.videoHeight || screen.naturalHeight || remoteH;
        const scale = Math.min(rect.width / naturalW, rect.height / naturalH);
        const dispW = naturalW * scale;
        const dispH = naturalH * scale;
        const offsetX = rect.left + (rect.width - dispW) / 2;
        const offsetY = rect.top + (rect.height - dispH) / 2;
        let x = (clientX - offsetX) / dispW;
        let y = (clientY - offsetY) / dispH;
        x = Math.max(0, Math.min(1, x));
        y = Math.max(0, Math.min(1, y));
        return {
            x: Math.round(x * remoteW),
            y: Math.round(y * remoteH)
        };
    }

    function sendInput(payload) {
        payload.type = "input";
        payload.host_id = HOST_ID;
        sendJson(payload);
    }

    function flushMove() {
        if (!pendingMove) return;
        sendInput({ action: "mouse_move", x: pendingMove.x, y: pendingMove.y });
        pendingMove = null;
        lastMoveSent = Date.now();
    }

    function queueMove(pos) {
        pendingMove = pos;
        const now = Date.now();
        const wait = MOVE_THROTTLE_MS - (now - lastMoveSent);
        if (wait <= 0) {
            if (moveTimer) {
                clearTimeout(moveTimer);
                moveTimer = null;
            }
            flushMove();
        } else if (!moveTimer) {
            moveTimer = setTimeout(function () {
                moveTimer = null;
                flushMove();
            }, wait);
        }
    }

    function showLocalCursor(x, y) {
        if (!localCursor) return;
        localCursor.style.display = "block";
        localCursor.style.left = x + "px";
        localCursor.style.top = y + "px";
    }

    function hideLocalCursor() {
        if (localCursor) localCursor.style.display = "none";
    }

    function activateInput() {
        if (!running) return;
        inputActive = true;
        stage.classList.add("controlling");
        stage.focus();
        toast("Input captured — Esc to release", "ok");
    }

    function releaseInput() {
        if (!inputActive) return;
        inputActive = false;
        stage.classList.remove("controlling");
        hideLocalCursor();
        sendInput({ action: "mouse_up", button: "left" });
        sendInput({ action: "mouse_up", button: "right" });
        sendInput({ action: "mouse_up", button: "middle" });
        toast("Input released", null);
    }

    function onMouseMove(e) {
        if (!inputActive) return;
        showLocalCursor(e.clientX, e.clientY);
        const pos = mapToRemote(e.clientX, e.clientY);
        if (pos) queueMove(pos);
    }

    function onMouseDown(e) {
        if (!running) return;
        if (!inputActive) {
            activateInput();
            return;
        }
        e.preventDefault();
        const pos = mapToRemote(e.clientX, e.clientY);
        if (!pos) return;
        const button = e.button === 1 ? "middle" : e.button === 2 ? "right" : "left";
        sendInput({ action: "mouse_down", button: button, x: pos.x, y: pos.y });
    }

    function onMouseUp(e) {
        if (!inputActive) return;
        e.preventDefault();
        const pos = mapToRemote(e.clientX, e.clientY);
        const button = e.button === 1 ? "middle" : e.button === 2 ? "right" : "left";
        sendInput({
            action: "mouse_up",
            button: button,
            x: pos ? pos.x : undefined,
            y: pos ? pos.y : undefined
        });
    }

    function onWheel(e) {
        if (!inputActive) return;
        e.preventDefault();
        const pos = mapToRemote(e.clientX, e.clientY);
        sendInput({
            action: "mouse_wheel",
            deltaX: e.deltaX,
            deltaY: e.deltaY,
            x: pos ? pos.x : undefined,
            y: pos ? pos.y : undefined
        });
    }

    function onContextMenu(e) {
        if (inputActive || running) e.preventDefault();
    }

    function onKeyDown(e) {
        if (!inputActive) return;
        if (e.key === "Escape") {
            e.preventDefault();
            releaseInput();
            return;
        }
        e.preventDefault();
        sendInput({
            action: "key_down",
            key: e.key,
            code: e.code,
            ctrl: e.ctrlKey,
            alt: e.altKey,
            shift: e.shiftKey,
            meta: e.metaKey
        });
    }

    function onKeyUp(e) {
        if (!inputActive) return;
        if (e.key === "Escape") return;
        e.preventDefault();
        sendInput({
            action: "key_up",
            key: e.key,
            code: e.code,
            ctrl: e.ctrlKey,
            alt: e.altKey,
            shift: e.shiftKey,
            meta: e.metaKey
        });
    }

    function bindInput() {
        stage.addEventListener("mousemove", onMouseMove);
        stage.addEventListener("mousedown", onMouseDown);
        window.addEventListener("mouseup", onMouseUp);
        stage.addEventListener("wheel", onWheel, { passive: false });
        stage.addEventListener("contextmenu", onContextMenu);
        window.addEventListener("keydown", onKeyDown);
        window.addEventListener("keyup", onKeyUp);
        stage.tabIndex = 0;
    }

    // -------- WebRTC --------

    function closePc() {
        if (pc) {
            try { pc.close(); } catch (e) {}
            pc = null;
        }
        if (screen) {
            screen.srcObject = null;
            screen.removeAttribute("src");
            screen.style.display = "none";
        }
    }

    function ensurePc() {
        if (pc) return pc;
        pc = new RTCPeerConnection({ iceServers: ICE_SERVERS, iceCandidatePoolSize: 8 });

        pc.ontrack = function (ev) {
            console.log("📡 remote track", ev.track.kind);
            const stream = ev.streams && ev.streams[0]
                ? ev.streams[0]
                : new MediaStream([ev.track]);
            screen.srcObject = stream;
            screen.style.display = "block";
            screen.autoplay = true;
            screen.playsInline = true;
            screen.muted = true;
            if (placeholder) placeholder.style.display = "none";
            screen.play().catch(function () {});
            setStatus("online", "Streaming (WebRTC)");
        };

        pc.onicecandidate = function (ev) {
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            if (ev.candidate) {
                sendJson({
                    type: "candidate",
                    host_id: HOST_ID,
                    candidate: {
                        candidate: ev.candidate.candidate,
                        sdpMid: ev.candidate.sdpMid,
                        sdpMLineIndex: ev.candidate.sdpMLineIndex
                    }
                });
            } else {
                sendJson({ type: "candidate", host_id: HOST_ID, candidate: null });
            }
        };

        pc.onconnectionstatechange = function () {
            console.log("PC state", pc.connectionState);
            if (pc.connectionState === "connected") {
                setStatus("online", "Connected");
            } else if (pc.connectionState === "failed") {
                setStatus("offline", "WebRTC failed");
            }
        };

        return pc;
    }

    async function handleOffer(msg) {
        if (msg.screen_width) remoteW = msg.screen_width;
        if (msg.screen_height) remoteH = msg.screen_height;

        const peer = ensurePc();
        await peer.setRemoteDescription({ type: "offer", sdp: msg.sdp });
        const answer = await peer.createAnswer();
        await peer.setLocalDescription(answer);
        sendJson({
            type: "answer",
            host_id: HOST_ID,
            sdp: peer.localDescription.sdp
        });
        console.log("📤 answer sent");
    }

    async function handleCandidate(msg) {
        if (!pc) return;
        try {
            if (!msg.candidate) {
                await pc.addIceCandidate(null);
                return;
            }
            await pc.addIceCandidate(msg.candidate);
        } catch (e) {
            console.warn("ICE candidate error", e);
        }
    }

    function handleMessage(raw) {
        if (typeof raw !== "string") return;
        let msg;
        try { msg = JSON.parse(raw); } catch (e) { return; }
        if (!msg || !msg.type) return;

        if (msg.type === "offer") {
            handleOffer(msg).catch(function (e) {
                console.error(e);
                toast("Offer error: " + e.message, "error");
            });
            return;
        }
        if (msg.type === "candidate") {
            handleCandidate(msg);
            return;
        }
        if (msg.type === "error") {
            toast(msg.message || "Error", "error");
            setStatus("offline", "Error");
        }
    }

    function connectWs() {
        if (socket) {
            try { socket.close(); } catch (e) {}
            socket = null;
        }
        setStatus("", "Signaling...");
        socket = new WebSocket(controlWsUrl());
        socket.onopen = function () {
            setStatus("online", "Signaling OK");
            sendJson({ type: "viewer_connected", host_id: HOST_ID });
        };
        socket.onmessage = function (ev) { handleMessage(ev.data); };
        socket.onerror = function () { setStatus("offline", "WS error"); };
        socket.onclose = function () {
            socket = null;
            if (running) setStatus("offline", "Signaling closed");
        };
    }

    async function apiStart() {
        const res = await fetch("/api/control/start/" + encodeURIComponent(HOST_ID), { method: "POST" });
        if (!res.ok) {
            let detail = "HTTP " + res.status;
            try {
                const j = await res.json();
                detail = j.detail || j.message || detail;
            } catch (e) {}
            throw new Error(detail);
        }
    }

    async function apiStop() {
        try {
            await fetch("/api/control/stop/" + encodeURIComponent(HOST_ID), { method: "POST" });
        } catch (e) {}
    }

    async function startControl() {
        if (!HOST_ID) {
            toast("No host selected", "error");
            return;
        }
        btnStart.disabled = true;
        setStatus("", "Starting ControlStream...");
        try {
            await loadIceServers();
            await apiStart();
            // wait for host process to connect
            await new Promise(function (r) { setTimeout(r, 1200); });
            running = true;
            btnStop.disabled = false;
            closePc();
            connectWs();
            setTimeout(function () { sendQuality(); }, 1800);
            hostSub.textContent = "WebRTC desktop — click screen to control";
            toast("Control started", "ok");
        } catch (e) {
            running = false;
            btnStart.disabled = false;
            btnStop.disabled = true;
            setStatus("offline", "Failed");
            toast("Start failed: " + (e.message || e), "error");
        }
    }

    async function stopControl() {
        running = false;
        releaseInput();
        closePc();
        if (socket) {
            try { socket.close(); } catch (e) {}
            socket = null;
        }
        await apiStop();
        btnStart.disabled = false;
        btnStop.disabled = true;
        setStatus("offline", "Stopped");
        hostSub.textContent = "Stopped";
        if (placeholder) {
            placeholder.style.display = "block";
            placeholder.innerHTML =
                "Press <b>Start</b> for WebRTC remote desktop.<br>" +
                "Then click the screen to control mouse and keyboard.";
        }
        toast("Stopped", null);
    }

    function init() {
        // Prefer <video> for WebRTC
        if (screen && screen.tagName === "IMG") {
            const video = document.createElement("video");
            video.id = "screen";
            video.autoplay = true;
            video.playsInline = true;
            video.muted = true;
            video.style.cssText = screen.style.cssText || "max-width:100%;max-height:100%;display:none;background:#000;";
            screen.parentNode.replaceChild(video, screen);
            // re-bind
            window._screenEl = video;
        }

        // re-get after possible replace
        const screenEl = document.getElementById("screen");
        if (screenEl) {
            // monkey patch local const by using property on stage
            Object.defineProperty(window, "__controlScreen", { value: screenEl });
        }

        if (!HOST_ID) {
            hostTitle.textContent = "Control";
            hostSub.textContent = "Select a host from the main page";
            setStatus("offline", "No host");
            btnStart.disabled = true;
            return;
        }

        hostTitle.textContent = "Control · " + HOST_ID;
        hostSub.textContent = "WebRTC mode";
        setStatus("", "Idle");
        bindInput();
        bindQualitySelect();
        btnStart.addEventListener("click", startControl);
        btnStop.addEventListener("click", stopControl);

        const btnBack = document.getElementById("btn-back");
        if (btnBack) {
            btnBack.addEventListener("click", function (e) {
                e.preventDefault();
                (async function () {
                    if (running) await stopControl();
                    window.location.href = "/";
                })();
            });
        }

        window.addEventListener("pagehide", function () {
            if (running) {
                try {
                    navigator.sendBeacon(
                        "/api/control/stop/" + encodeURIComponent(HOST_ID)
                    );
                } catch (err) {}
            }
        });

        window.addEventListener("beforeunload", function () {
            if (running) apiStop();
        });
    }

    // Fix screen reference after IMG->VIDEO swap inside init
    const _mapToRemote = mapToRemote;
    const _origInit = init;

    // rewrite mapToRemote/display to use getElementById always
    // (already uses screen const - fix by updating screen variable after replace)

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () {
            // convert img to video first
            let el = document.getElementById("screen");
            if (el && el.tagName === "IMG") {
                const video = document.createElement("video");
                video.id = "screen";
                video.autoplay = true;
                video.playsInline = true;
                video.muted = true;
                video.setAttribute("draggable", "false");
                video.style.maxWidth = "100%";
                video.style.maxHeight = "100%";
                video.style.width = "auto";
                video.style.height = "auto";
                video.style.objectFit = "contain";
                video.style.display = "none";
                video.style.background = "#000";
                el.parentNode.replaceChild(video, el);
            }
            // cannot reassign const screen — patch functions to query live
            initLive();
        });
    } else {
        initLive();
    }

    function liveScreen() {
        return document.getElementById("screen");
    }

    // Override helpers to use live element
    mapToRemote = function (clientX, clientY) {
        const scr = liveScreen();
        if (!scr || !remoteW || !remoteH) return null;
        const rect = scr.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return null;
        const naturalW = scr.videoWidth || remoteW;
        const naturalH = scr.videoHeight || remoteH;
        if (!naturalW || !naturalH) return null;
        const scale = Math.min(rect.width / naturalW, rect.height / naturalH);
        const dispW = naturalW * scale;
        const dispH = naturalH * scale;
        const offsetX = rect.left + (rect.width - dispW) / 2;
        const offsetY = rect.top + (rect.height - dispH) / 2;
        let x = (clientX - offsetX) / dispW;
        let y = (clientY - offsetY) / dispH;
        x = Math.max(0, Math.min(1, x));
        y = Math.max(0, Math.min(1, y));
        return { x: Math.round(x * remoteW), y: Math.round(y * remoteH) };
    };

    function initLive() {
        if (!HOST_ID) {
            hostTitle.textContent = "Control";
            hostSub.textContent = "Select a host from the main page";
            setStatus("offline", "No host");
            btnStart.disabled = true;
            return;
        }
        hostTitle.textContent = "Control · " + HOST_ID;
        hostSub.textContent = "WebRTC desktop stream";
        setStatus("", "Idle");
        bindInput();
        btnStart.addEventListener("click", startControl);
        btnStop.addEventListener("click", stopControl);

        const btnBack = document.getElementById("btn-back");
        if (btnBack) {
            btnBack.addEventListener("click", function (e) {
                e.preventDefault();
                (async function () {
                    if (running) await stopControl();
                    window.location.href = "/";
                })();
            });
        }

        window.addEventListener("pagehide", function () {
            if (running) {
                try {
                    navigator.sendBeacon(
                        "/api/control/stop/" + encodeURIComponent(HOST_ID)
                    );
                } catch (err) {}
            }
        });

        window.addEventListener("beforeunload", function () {
            if (running) apiStop();
        });
    }

    // patch ensurePc ontrack to use live screen
    const _ensurePc = ensurePc;
    ensurePc = function () {
        if (pc) return pc;
        pc = new RTCPeerConnection({ iceServers: ICE_SERVERS, iceCandidatePoolSize: 8 });
        pc.ontrack = function (ev) {
            const scr = liveScreen();
            const stream = (ev.streams && ev.streams[0]) ? ev.streams[0] : new MediaStream([ev.track]);
            if (scr) {
                scr.srcObject = stream;
                scr.style.display = "block";
                scr.play().catch(function () {});
            }
            if (placeholder) placeholder.style.display = "none";
            setStatus("online", "Streaming (WebRTC)");
        };
        pc.onicecandidate = function (ev) {
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            if (ev.candidate) {
                sendJson({
                    type: "candidate",
                    host_id: HOST_ID,
                    candidate: {
                        candidate: ev.candidate.candidate,
                        sdpMid: ev.candidate.sdpMid,
                        sdpMLineIndex: ev.candidate.sdpMLineIndex
                    }
                });
            } else {
                sendJson({ type: "candidate", host_id: HOST_ID, candidate: null });
            }
        };
        pc.onconnectionstatechange = function () {
            if (!pc) return;
            if (pc.connectionState === "connected") setStatus("online", "Connected");
            if (pc.connectionState === "failed") setStatus("offline", "WebRTC failed");
        };
        return pc;
    };

    closePc = function () {
        if (pc) {
            try { pc.close(); } catch (e) {}
            pc = null;
        }
        const scr = liveScreen();
        if (scr) {
            scr.srcObject = null;
            scr.style.display = "none";
        }
    };
})();

"use strict";

(function () {
    const params = new URLSearchParams(window.location.search);
    const HOST_ID = (params.get("host") || "").trim();

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
    let stopping = false;

    const screen = document.getElementById("screen");
    const placeholder = document.getElementById("placeholder");
    const connStatus = document.getElementById("conn-status");
    const connText = document.getElementById("conn-text");
    const hostTitle = document.getElementById("host-title");
    const hostSub = document.getElementById("host-sub");
    const toastEl = document.getElementById("toast");
    const btnBack = document.getElementById("btn-back");

    function toast(msg, type) {
        if (!toastEl) return;
        toastEl.textContent = msg;
        toastEl.className = "toast show" + (type ? " " + type : "");
        clearTimeout(toast._t);
        toast._t = setTimeout(function () {
            toastEl.classList.remove("show");
        }, 2500);
    }

    function setStatus(kind, text) {
        connStatus.className = "status " + (kind || "");
        connText.textContent = text || "";
    }

    function wsUrl() {
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

    function closePc() {
        if (pc) {
            try { pc.close(); } catch (e) {}
            pc = null;
        }
        if (screen) {
            screen.srcObject = null;
            screen.style.display = "none";
        }
    }

    function ensurePc() {
        if (pc) return pc;
        pc = new RTCPeerConnection({ iceServers: ICE_SERVERS, iceCandidatePoolSize: 8 });

        pc.ontrack = function (ev) {
            const stream = (ev.streams && ev.streams[0])
                ? ev.streams[0]
                : new MediaStream([ev.track]);
            screen.srcObject = stream;
            screen.style.display = "block";
            if (placeholder) placeholder.style.display = "none";
            screen.play().catch(function () {});
            setStatus("online", "Streaming");
            hostSub.textContent = "Live WebRTC desktop";
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
    }

    async function handleOffer(msg) {
        const peer = ensurePc();
        await peer.setRemoteDescription({ type: "offer", sdp: msg.sdp });
        const answer = await peer.createAnswer();
        await peer.setLocalDescription(answer);
        sendJson({
            type: "answer",
            host_id: HOST_ID,
            sdp: peer.localDescription.sdp
        });
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
            console.warn("ICE", e);
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
                toast("Offer error", "error");
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
        socket = new WebSocket(wsUrl());
        socket.onopen = function () {
            setStatus("online", "Signaling OK");
            sendJson({ type: "viewer_connected", host_id: HOST_ID });
        };
        socket.onmessage = function (ev) { handleMessage(ev.data); };
        socket.onerror = function () { setStatus("offline", "WS error"); };
        socket.onclose = function () {
            socket = null;
            if (running && !stopping) setStatus("offline", "Disconnected");
        };
    }

    async function apiStart() {
        const res = await fetch(
            "/api/control/start/" + encodeURIComponent(HOST_ID),
            { method: "POST" }
        );
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
            await fetch(
                "/api/control/stop/" + encodeURIComponent(HOST_ID),
                { method: "POST" }
            );
        } catch (e) {}
    }

    async function start() {
        if (!HOST_ID) {
            setStatus("offline", "No host");
            if (placeholder) {
                placeholder.textContent = "Open from host card: /monitor?host=ID";
            }
            return;
        }

        hostTitle.textContent = "Monitor · " + HOST_ID;
        setStatus("", "Starting...");

        try {
            await loadIceServers();
            await apiStart();
            await new Promise(function (r) { setTimeout(r, 1200); });
            running = true;
            closePc();
            connectWs();
            setTimeout(function () { sendQuality(); }, 1800);
            toast("Monitor started", "ok");
        } catch (e) {
            running = false;
            setStatus("offline", "Failed");
            if (placeholder) {
                placeholder.textContent = "Failed: " + (e.message || e);
            }
            toast("Start failed: " + (e.message || e), "error");
        }
    }

    async function stopAndLeave(href) {
        if (stopping) {
            if (href) window.location.href = href;
            return;
        }
        stopping = true;
        running = false;
        closePc();
        if (socket) {
            try { socket.close(); } catch (e) {}
            socket = null;
        }
        setStatus("offline", "Stopping...");
        await apiStop();
        if (href) {
            window.location.href = href;
        }
    }

    function init() {
        if (btnBack) {
            btnBack.addEventListener("click", function (e) {
                e.preventDefault();
                stopAndLeave("/");
            });
        }

        window.addEventListener("pagehide", function () {
            if (running) {
                // best-effort stop
                navigator.sendBeacon(
                    "/api/control/stop/" + encodeURIComponent(HOST_ID)
                );
            }
        });

        window.addEventListener("beforeunload", function () {
            if (running) {
                apiStop();
            }
        });

        bindQualitySelect();
        // Auto-start immediately
        start();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();

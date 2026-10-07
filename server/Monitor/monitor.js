// ============================================================
// REMOTE DESKTOP MONITOR
// server/Monitor/monitor.js
// ============================================================

"use strict";


// ============================================================
// HOST ID
// ============================================================

const params = new URLSearchParams(
    window.location.search
);

const HOST_ID = params.get("host");


// ============================================================
// CONFIG
// ============================================================

const RECONNECT_DELAY = 3000;

const API_BASE = "/api/monitor";


// ============================================================
// STATE
// ============================================================

let monitorSocket = null;

let reconnectTimer = null;

let reconnectAttempts = 0;

let monitorRunning = false;

let pageClosing = false;

let lastFrameTime = 0;


// ============================================================
// DOM
// ============================================================

const screen = document.getElementById(
    "screen"
);

const screenPlaceholder =
    document.getElementById(
        "screen-placeholder"
    );

const monitorToggle =
    document.getElementById(
        "monitor-toggle"
    );

const hostStatus =
    document.getElementById(
        "host-status"
    );

const statusDot =
    document.getElementById(
        "status-dot"
    );


// ============================================================
// LOG
// ============================================================

function log(...args) {

    console.log(
        "[MONITOR]",
        ...args
    );

}


// ============================================================
// ERROR
// ============================================================

function logError(...args) {

    console.error(
        "[MONITOR]",
        ...args
    );

}


// ============================================================
// SCREEN PLACEHOLDER
// ============================================================

function showPlaceholder(
    text
) {

    if (!screenPlaceholder) {
        return;
    }

    screenPlaceholder.textContent =
        text;

}


// ============================================================
// SHOW SCREEN
// ============================================================

function showScreen() {

    if (screen) {

        screen.style.display =
            "block";
    }

    if (screenPlaceholder) {

        screenPlaceholder.style.display =
            "none";
    }

}


// ============================================================
// HIDE SCREEN
// ============================================================

function hideScreen(
    message = "Monitor is OFF"
) {

    if (screen) {

        screen.style.display =
            "none";

        screen.removeAttribute(
            "src"
        );
    }

    if (screenPlaceholder) {

        screenPlaceholder.style.display =
            "block";

        screenPlaceholder.textContent =
            message;
    }

}


// ============================================================
// UPDATE STATUS
// ============================================================

function setStatus(
    text,
    online = false
) {

    if (hostStatus) {

        hostStatus.textContent =
            text;
    }

    if (statusDot) {

        statusDot.classList.remove(
            "online",
            "offline"
        );

        if (online) {

            statusDot.classList.add(
                "online"
            );

        } else {

            statusDot.classList.add(
                "offline"
            );
        }
    }

}


// ============================================================
// CHECK HOST ID
// ============================================================

if (!HOST_ID) {

    logError(
        "Host ID is missing"
    );

    setStatus(
        "No host selected",
        false
    );

    showPlaceholder(
        "No host selected"
    );

} else {

    log(
        "Host ID:",
        HOST_ID
    );
}


// ============================================================
// WEBSOCKET URL
// ============================================================

function getWebSocketURL() {

    const protocol =
        window.location.protocol === "https:"
            ? "wss:"
            : "ws:";

    const host =
        window.location.host;

    return (
        protocol
        + "//"
        + host
        + "/ws/monitor/"
        + encodeURIComponent(
            HOST_ID
        )
    );

}


// ============================================================
// CONNECT MONITOR
// ============================================================

function connectMonitor() {

    if (!HOST_ID) {

        return;
    }

    if (pageClosing) {

        return;
    }

    // --------------------------------------------------------
    // Already connected
    // --------------------------------------------------------

    if (
        monitorSocket &&
        (
            monitorSocket.readyState ===
            WebSocket.OPEN
            ||
            monitorSocket.readyState ===
            WebSocket.CONNECTING
        )
    ) {

        log(
            "WebSocket already connected"
        );

        return;
    }


    const url =
        getWebSocketURL();


    log(
        "Connecting:",
        url
    );


    showPlaceholder(
        "Connecting to monitor..."
    );


    try {

        monitorSocket =
            new WebSocket(
                url
            );


        monitorSocket.binaryType =
            "blob";


        // ====================================================
        // OPEN
        // ====================================================

        monitorSocket.onopen =
            function () {

                reconnectAttempts = 0;

                log(
                    "🟢 Monitor WebSocket connected"
                );

                setStatus(
                    "Monitor connected",
                    true
                );


                // ------------------------------------------------
                // Tell server/browser side that viewer connected
                // ------------------------------------------------

                try {

                    monitorSocket.send(
                        JSON.stringify({

                            type:
                                "viewer_connected",

                            host_id:
                                HOST_ID,

                            timestamp:
                                Date.now(),

                        })
                    );

                } catch (error) {

                    logError(
                        "Failed to send viewer_connected:",
                        error
                    );
                }


                // ------------------------------------------------
                // Request monitor start
                // ------------------------------------------------

                startRemoteMonitor();

            };


        // ====================================================
        // MESSAGE
        // ====================================================

        monitorSocket.onmessage =
            function (event) {

                handleMessage(
                    event.data
                );

            };


        // ====================================================
        // ERROR
        // ====================================================

        monitorSocket.onerror =
            function (error) {

                logError(
                    "WebSocket error:",
                    error
                );

                setStatus(
                    "Monitor connection error",
                    false
                );

            };


        // ====================================================
        // CLOSE
        // ====================================================

        monitorSocket.onclose =
            function (event) {

                log(
                    "🔴 Monitor WebSocket closed",
                    event.code,
                    event.reason
                );


                monitorSocket =
                    null;


                setStatus(
                    "Monitor disconnected",
                    false
                );


                if (!pageClosing) {

                    hideScreen(
                        "Monitor disconnected"
                    );

                    scheduleReconnect();

                }

            };

    }

    catch (error) {

        logError(
            "WebSocket creation failed:",
            error
        );

        scheduleReconnect();

    }

}


// ============================================================
// HANDLE MESSAGE
// ============================================================

function handleMessage(
    data
) {

    // --------------------------------------------------------
    // Binary
    // --------------------------------------------------------

    if (
        data instanceof Blob
        ||
        data instanceof ArrayBuffer
    ) {

        log(
            "📦 Binary frame received"
        );

        handleBinaryFrame(
            data
        );

        return;
    }


    // --------------------------------------------------------
    // JSON
    // --------------------------------------------------------

    if (
        typeof data !== "string"
    ) {

        return;
    }


    let message;

    try {

        message =
            JSON.parse(
                data
            );

    }

    catch (error) {

        logError(
            "Invalid JSON:",
            data
        );

        return;
    }


    if (!message) {

        return;
    }


    log(
        "📩 Message:",
        message.type
    );


    // ========================================================
    // SCREEN FRAME
    // ========================================================

    if (
        message.type ===
        "screen_frame"
    ) {

        handleScreenFrame(
            message
        );

        return;
    }


    // ========================================================
    // MONITOR STATUS
    // ========================================================

    if (
        message.type ===
        "monitor_status"
    ) {

        handleMonitorStatus(
            message
        );

        return;
    }


    // ========================================================
    // CONNECTED
    // ========================================================

    if (
        message.type ===
        "monitor_connected"
    ) {

        log(
            "🟢 Remote Monitor connected"
        );

        setStatus(
            "Monitor connected",
            true
        );

        return;
    }


    // ========================================================
    // ERROR
    // ========================================================

    if (
        message.type ===
        "error"
    ) {

        logError(
            "Server error:",
            message
        );

        showPlaceholder(
            message.detail
            ||
            message.message
            ||
            "Monitor error"
        );

        return;
    }


    // ========================================================
    // COMMAND STATUS
    // ========================================================

    if (
        message.type ===
        "command_status"
    ) {

        log(
            "Command status:",
            message
        );

        return;
    }


    // ========================================================
    // UNKNOWN
    // ========================================================

    log(
        "Unknown message type:",
        message.type
    );

}


// ============================================================
// HANDLE SCREEN FRAME
// ============================================================

function handleScreenFrame(
    message
) {

    if (!message.image) {

        logError(
            "screen_frame without image"
        );

        return;
    }


    // --------------------------------------------------------
    // Optional host validation
    // --------------------------------------------------------

    if (
        message.host_id
        &&
        String(
            message.host_id
        ).toLowerCase()
        !==
        String(
            HOST_ID
        ).toLowerCase()
    ) {

        logError(
            "Frame from wrong host:",
            message.host_id
        );

        return;
    }


    lastFrameTime =
        Date.now();


    monitorRunning =
        true;


    // --------------------------------------------------------
    // Base64 JPEG
    // --------------------------------------------------------

    const imageData =
        "data:image/jpeg;base64,"
        + message.image;


    if (screen) {

        screen.src =
            imageData;
    }


    showScreen();


    // --------------------------------------------------------
    // Update toggle
    // --------------------------------------------------------

    if (monitorToggle) {

        monitorToggle.checked =
            true;
    }


    setStatus(
        "Monitor streaming",
        true
    );

}


// ============================================================
// HANDLE BINARY FRAME
// ============================================================

function handleBinaryFrame(
    data
) {

    if (!screen) {

        return;
    }


    if (data instanceof Blob) {

        const url =
            URL.createObjectURL(
                data
            );

        screen.src =
            url;

        showScreen();


        screen.onload =
            function () {

                URL.revokeObjectURL(
                    url
                );

            };


        return;
    }


    if (
        data instanceof ArrayBuffer
    ) {

        const blob =
            new Blob(
                [data],
                {
                    type:
                        "image/jpeg"
                }
            );


        const url =
            URL.createObjectURL(
                blob
            );


        screen.src =
            url;

        showScreen();


        screen.onload =
            function () {

                URL.revokeObjectURL(
                    url
                );

            };

    }

}


// ============================================================
// HANDLE MONITOR STATUS
// ============================================================

function handleMonitorStatus(
    message
) {

    const running =
        Boolean(
            message.running
        );


    monitorRunning =
        running;


    if (monitorToggle) {

        monitorToggle.checked =
            running;
    }


    if (!running) {

        hideScreen(
            "Monitor is OFF"
        );

        return;
    }


    setStatus(
        "Monitor running",
        true
    );

}


// ============================================================
// START REMOTE MONITOR
// ============================================================

async function startRemoteMonitor() {

    if (!HOST_ID) {

        return;
    }


    log(
        "▶ Requesting Monitor.py start:",
        HOST_ID
    );


    showPlaceholder(
        "Starting Monitor..."
    );


    try {

        const response =
            await fetch(

                API_BASE
                + "/"
                + encodeURIComponent(
                    HOST_ID
                )
                + "/start",

                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json",

                    },

                    cache:
                        "no-store",

                }
            );


        if (
            response.status ===
            401
        ) {

            window.location.href =
                "/login";

            return;
        }


        const result =
            await response.json();


        log(
            "Start response:",
            result
        );


        if (!response.ok) {

            throw new Error(
                result.detail
                ||
                "HTTP "
                + response.status
            );
        }


        monitorRunning =
            Boolean(
                result.monitor_running
            );


        if (monitorToggle) {

            monitorToggle.checked =
                monitorRunning;
        }


        if (monitorRunning) {

            showPlaceholder(
                "Waiting for screen..."
            );

        } else {

            showPlaceholder(
                "Monitor did not start"
            );

        }

    }

    catch (error) {

        logError(
            "Start Monitor error:",
            error
        );


        showPlaceholder(
            "Failed to start Monitor"
        );

    }

}


// ============================================================
// STOP REMOTE MONITOR
// ============================================================

async function stopRemoteMonitor() {

    if (!HOST_ID) {

        return;
    }


    log(
        "⏹ Requesting Monitor.py stop:",
        HOST_ID
    );


    try {

        const response =
            await fetch(

                API_BASE
                + "/"
                + encodeURIComponent(
                    HOST_ID
                )
                + "/stop",

                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json",

                    },

                    cache:
                        "no-store",

                }
            );


        if (
            response.status ===
            401
        ) {

            window.location.href =
                "/login";

            return;
        }


        const result =
            await response.json();


        log(
            "Stop response:",
            result
        );


        if (!response.ok) {

            throw new Error(
                result.detail
                ||
                "HTTP "
                + response.status
            );
        }


        monitorRunning =
            false;


        hideScreen(
            "Monitor is OFF"
        );

    }

    catch (error) {

        logError(
            "Stop Monitor error:",
            error
        );

    }

}


// ============================================================
// TOGGLE
// ============================================================

if (monitorToggle) {

    monitorToggle.addEventListener(
        "change",
        function () {

            log(
                "Monitor toggle:",
                this.checked
            );


            if (this.checked) {

                startRemoteMonitor();

            } else {

                stopRemoteMonitor();

            }

        }
    );

}


// ============================================================
// RECONNECT
// ============================================================

function scheduleReconnect() {

    if (pageClosing) {

        return;
    }


    if (reconnectTimer) {

        return;
    }


    reconnectAttempts++;


    const delay =
        Math.min(
            RECONNECT_DELAY
            * reconnectAttempts,
            15000
        );


    log(
        `🔄 Reconnecting in ${delay} ms`
    );


    reconnectTimer =
        setTimeout(
            function () {

                reconnectTimer =
                    null;

                connectMonitor();

            },
            delay
        );

}


// ============================================================
// CHECK MONITOR
// ============================================================

async function checkMonitorStatus() {

    if (!HOST_ID) {

        return;
    }


    try {

        const response =
            await fetch(

                API_BASE
                + "/"
                + encodeURIComponent(
                    HOST_ID
                ),

                {

                    cache:
                        "no-store",

                }
            );


        if (
            response.status ===
            401
        ) {

            window.location.href =
                "/login";

            return;
        }


        if (!response.ok) {

            return;
        }


        const result =
            await response.json();


        log(
            "Monitor API status:",
            result
        );


        monitorRunning =
            result.monitor_running
            === true;


        if (monitorToggle) {

            monitorToggle.checked =
                monitorRunning;
        }


    }

    catch (error) {

        logError(
            "Monitor status error:",
            error
        );

    }

}


// ============================================================
// WATCHDOG
// ============================================================

setInterval(
    function () {

        if (
            !monitorRunning
        ) {

            return;
        }


        if (
            lastFrameTime === 0
        ) {

            return;
        }


        const elapsed =
            Date.now()
            - lastFrameTime;


        // No frame for 5 seconds

        if (
            elapsed > 5000
        ) {

            log(
                "⚠️ No screen frames received for",
                elapsed,
                "ms"
            );

            setStatus(
                "No screen data",
                false
            );

        }

    },
    2000
);


// ============================================================
// PAGE CLOSE
// ============================================================

window.addEventListener(
    "beforeunload",
    function () {

        pageClosing =
            true;


        if (reconnectTimer) {

            clearTimeout(
                reconnectTimer
            );

            reconnectTimer =
                null;
        }


        if (
            monitorSocket
            &&
            monitorSocket.readyState ===
            WebSocket.OPEN
        ) {

            try {

                monitorSocket.close();

            } catch (error) {

                // ignore
            }

        }

    }
);


// ============================================================
// START
// ============================================================

async function initMonitor() {

    log(
        "================================================"
    );

    log(
        "🖥 REMOTE DESKTOP MONITOR"
    );

    log(
        "Host:",
        HOST_ID
    );

    log(
        "================================================"
    );


    if (!HOST_ID) {

        return;
    }


    hideScreen(
        "Connecting to monitor..."
    );


    await checkMonitorStatus();


    connectMonitor();

}


// ============================================================
// INIT
// ============================================================

initMonitor();
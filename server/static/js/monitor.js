"use strict";

console.log("🔥 MONITOR.JS LOADED");


// ============================================================
// HOST ID
// ============================================================

const params = new URLSearchParams(
    window.location.search
);

const HOST_ID = params.get("host");

console.log("🆔 HOST ID:", HOST_ID);


// ============================================================
// DOM
// ============================================================

const screen = document.getElementById("screen");

const placeholder =
    document.getElementById("screen-placeholder");

const statusText =
    document.getElementById("host-status");

const statusDot =
    document.getElementById("status-dot");

const toggle =
    document.getElementById("monitor-toggle");


// ============================================================
// STATUS
// ============================================================

function setStatus(
    text,
    online = false
) {

    if (statusText) {

        statusText.textContent =
            text;
    }

    if (statusDot) {

        statusDot.classList.remove(
            "online",
            "offline"
        );

        statusDot.classList.add(
            online
                ? "online"
                : "offline"
        );
    }

}


// ============================================================
// PLACEHOLDER
// ============================================================

function showPlaceholder(
    text
) {

    if (placeholder) {

        placeholder.style.display =
            "block";

        placeholder.textContent =
            text;
    }

    if (screen) {

        screen.style.display =
            "none";
    }

}


// ============================================================
// SHOW SCREEN
// ============================================================

function showScreen(
    image
) {

    if (!screen) {

        console.error(
            "❌ #screen not found"
        );

        return;
    }

    screen.src =
        "data:image/jpeg;base64,"
        + image;

    screen.style.display =
        "block";


    if (placeholder) {

        placeholder.style.display =
            "none";
    }

}


// ============================================================
// LOAD HOST INFORMATION
// ============================================================

async function loadHost() {

    console.log(
        "📡 Loading host information..."
    );


    if (!HOST_ID) {

        console.error(
            "❌ HOST_ID is missing"
        );

        setStatus(
            "No host selected",
            false
        );

        return;
    }


    try {

        const response =
            await fetch(
                "/api/hosts?t="
                + Date.now(),
                {
                    cache:
                        "no-store"
                }
            );


        console.log(
            "📡 /api/hosts:",
            response.status
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

            throw new Error(
                "HTTP "
                + response.status
            );
        }


        const result =
            await response.json();


        console.log(
            "📦 Hosts:",
            result
        );


        const hosts =
            result.hosts || [];


        const host =
            hosts.find(
                item =>
                    String(
                        item.host_id
                    ).toLowerCase()
                    ===
                    String(
                        HOST_ID
                    ).toLowerCase()
            );


        if (!host) {

            console.error(
                "❌ Host not found:",
                HOST_ID
            );

            setStatus(
                "Offline",
                false
            );

            return;
        }


        console.log(
            "🟢 Host found:",
            host
        );


        // ----------------------------------------------------
        // COMPUTER
        // ----------------------------------------------------

        setText(
            "computer-name",
            host.computer_name
            || host.name
            || host.host_id
        );


        setText(
            "host-id",
            "Host ID: "
            + host.host_id
        );


        // ----------------------------------------------------
        // USER
        // ----------------------------------------------------

        setText(
            "username",
            host.username
        );


        // ----------------------------------------------------
        // OS
        // ----------------------------------------------------

        setText(
            "os",
            [
                host.os,
                host.os_release
            ]
            .filter(Boolean)
            .join(" ")
        );


        // ----------------------------------------------------
        // PYTHON
        // ----------------------------------------------------

        setText(
            "python",
            host.python_version
        );


        // ----------------------------------------------------
        // CPU
        // ----------------------------------------------------

        setText(
            "cpu",
            host.cpu
        );


        setText(
            "cpu-percent",
            host.cpu_percent !== null
            &&
            host.cpu_percent !== undefined
                ? Number(
                    host.cpu_percent
                ).toFixed(1) + "%"
                : "—"
        );


        // ----------------------------------------------------
        // CPU TEMPERATURE
        // ----------------------------------------------------

        setText(
            "cpu-temperature",
            host.cpu_temperature !== null
            &&
            host.cpu_temperature !== undefined
                ? host.cpu_temperature
                    + " °C"
                : "—"
        );


        // ----------------------------------------------------
        // RAM
        // ----------------------------------------------------

        if (host.memory) {

            setText(
                "ram",
                (
                    host.memory.used_gb
                    ?? "—"
                )
                + " / "
                +
                (
                    host.memory.total_gb
                    ?? "—"
                )
                + " GB ("
                +
                (
                    host.memory.percent
                    ?? "—"
                )
                + "%)"
            );

        }


        // ----------------------------------------------------
        // DISK
        // ----------------------------------------------------

        if (host.disk) {

            setText(
                "disk",
                (
                    host.disk.free_gb
                    ?? "—"
                )
                + " GB free / "
                +
                (
                    host.disk.total_gb
                    ?? "—"
                )
                + " GB"
            );

        }


        // ----------------------------------------------------
        // UPTIME
        // ----------------------------------------------------

        setText(
            "uptime",
            host.windows_uptime
        );


        // ----------------------------------------------------
        // BOOT
        // ----------------------------------------------------

        setText(
            "boot",
            host.windows_boot_time
        );


        // ----------------------------------------------------
        // STATUS
        // ----------------------------------------------------

        setStatus(
            "Online",
            true
        );


        // ----------------------------------------------------
        // MONITOR STATE
        // ----------------------------------------------------

        if (toggle) {

            toggle.checked =
                host.monitor_running
                === true;
        }


        console.log(
            "✅ Host information loaded"
        );

    }

    catch (error) {

        console.error(
            "❌ Host loading error:",
            error
        );

        setStatus(
            "Connection error",
            false
        );

    }

}


// ============================================================
// SET TEXT
// ============================================================

function setText(
    id,
    value
) {

    const element =
        document.getElementById(id);

    if (!element) {

        return;
    }


    if (
        value === null
        ||
        value === undefined
        ||
        value === ""
    ) {

        element.textContent =
            "—";

    } else {

        element.textContent =
            value;
    }

}


// ============================================================
// WEBSOCKET URL
// ============================================================

function getWebSocketURL() {

    const protocol =
        window.location.protocol ===
        "https:"
            ? "wss:"
            : "ws:";


    return (
        protocol
        + "//"
        + window.location.host
        + "/ws/monitor/"
        + encodeURIComponent(
            HOST_ID
        )
    );

}


// ============================================================
// CONNECT MONITOR WEBSOCKET
// ============================================================

function connectMonitor() {

    if (!HOST_ID) {

        console.error(
            "❌ Cannot connect: HOST_ID missing"
        );

        return;
    }


    const url =
        getWebSocketURL();


    console.log(
        "🔌 Connecting Monitor WebSocket:"
    );

    console.log(
        url
    );


    showPlaceholder(
        "Connecting to monitor..."
    );


    const ws =
        new WebSocket(
            url
        );


    window.monitorSocket =
        ws;


    // ========================================================
    // OPEN
    // ========================================================

    ws.onopen =
        function () {

            console.log(
                "🟢 MONITOR WEBSOCKET CONNECTED"
            );


            setStatus(
                "Monitor connected",
                true
            );


            try {

                ws.send(
                    JSON.stringify({

                        type:
                            "viewer_connected",

                        host_id:
                            HOST_ID,

                        timestamp:
                            Date.now()

                    })
                );

            }

            catch (error) {

                console.error(
                    "❌ viewer_connected error:",
                    error
                );

            }


            // ------------------------------------------------
            // Start Monitor.py
            // ------------------------------------------------

            startMonitor();

        };


    // ========================================================
    // MESSAGE
    // ========================================================

    ws.onmessage =
        function (event) {

            console.log(
                "📩 Monitor message received"
            );


            if (
                typeof event.data !==
                "string"
            ) {

                console.log(
                    "📦 Binary frame:",
                    event.data
                );

                return;
            }


            let data;


            try {

                data =
                    JSON.parse(
                        event.data
                    );

            }

            catch (error) {

                console.error(
                    "❌ Invalid monitor JSON:",
                    event.data
                );

                return;
            }


            console.log(
                "📦 Message type:",
                data.type
            );


            // =================================================
            // SCREEN FRAME
            // =================================================

            if (
                data.type ===
                "screen_frame"
            ) {

                console.log(
                    "📸 SCREEN FRAME RECEIVED:",
                    data.image
                        ? data.image.length
                        : 0,
                    "bytes"
                );


                if (
                    data.host_id
                    &&
                    String(
                        data.host_id
                    ).toLowerCase()
                    !==
                    String(
                        HOST_ID
                    ).toLowerCase()
                ) {

                    console.warn(
                        "⚠️ Frame from another host:",
                        data.host_id
                    );

                    return;
                }


                if (data.image) {

                    showScreen(
                        data.image
                    );


                    if (toggle) {

                        toggle.checked =
                            true;
                    }


                    setStatus(
                        "Monitor streaming",
                        true
                    );

                }


                return;
            }


            // =================================================
            // MONITOR STATUS
            // =================================================

            if (
                data.type ===
                "monitor_status"
            ) {

                console.log(
                    "🖥 Monitor status:",
                    data
                );


                if (toggle) {

                    toggle.checked =
                        data.running
                        === true;
                }


                if (
                    data.running
                    !== true
                ) {

                    showPlaceholder(
                        "Monitor is OFF"
                    );

                }


                return;
            }


            // =================================================
            // ERROR
            // =================================================

            if (
                data.type ===
                "error"
            ) {

                console.error(
                    "❌ Monitor server error:",
                    data
                );

                showPlaceholder(
                    data.detail
                    ||
                    data.message
                    ||
                    "Monitor error"
                );

            }

        };


    // ========================================================
    // ERROR
    // ========================================================

    ws.onerror =
        function (error) {

            console.error(
                "❌ Monitor WebSocket ERROR:",
                error
            );


            setStatus(
                "WebSocket error",
                false
            );

        };


    // ========================================================
    // CLOSE
    // ========================================================

    ws.onclose =
        function (event) {

            console.warn(
                "🔴 Monitor WebSocket CLOSED:",
                event.code,
                event.reason
            );


            setStatus(
                "Monitor disconnected",
                false
            );


            showPlaceholder(
                "Monitor disconnected"
            );


            setTimeout(
                function () {

                    console.log(
                        "🔄 Reconnecting Monitor..."
                    );

                    connectMonitor();

                },
                3000
            );

        };

}


// ============================================================
// START MONITOR.PY
// ============================================================

async function startMonitor() {

    if (!HOST_ID) {

        return;
    }


    console.log(
        "▶️ Requesting Monitor.py start..."
    );


    try {

        const response =
            await fetch(

                "/api/monitor/"
                + encodeURIComponent(
                    HOST_ID
                )
                + "/start",

                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    cache:
                        "no-store"

                }

            );


        console.log(
            "📡 Start Monitor HTTP:",
            response.status
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


        console.log(
            "📦 Start Monitor result:",
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


        if (toggle) {

            toggle.checked =
                result.monitor_running
                === true;
        }


        showPlaceholder(
            "Waiting for screen..."
        );


        console.log(
            "✅ Monitor.py start command sent"
        );

    }

    catch (error) {

        console.error(
            "❌ Failed to start Monitor.py:",
            error
        );


        showPlaceholder(
            "Failed to start Monitor"
        );

    }

}


// ============================================================
// TOGGLE
// ============================================================

if (toggle) {

    toggle.addEventListener(
        "change",
        function () {

            console.log(
                "🔘 Monitor toggle:",
                this.checked
            );


            if (this.checked) {

                startMonitor();

            } else {

                stopMonitor();

            }

        }
    );

}


// ============================================================
// STOP MONITOR.PY
// ============================================================

async function stopMonitor() {

    if (!HOST_ID) {

        return;
    }


    console.log(
        "⏹ Requesting Monitor.py stop..."
    );


    try {

        const response =
            await fetch(

                "/api/monitor/"
                + encodeURIComponent(
                    HOST_ID
                )
                + "/stop",

                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    cache:
                        "no-store"

                }

            );


        console.log(
            "📡 Stop Monitor HTTP:",
            response.status
        );


        if (
            response.status ===
            401
        ) {

            window.location.href =
                "/login";

            return;
        }


        if (toggle) {

            toggle.checked =
                false;
        }


        showPlaceholder(
            "Monitor is OFF"
        );

    }

    catch (error) {

        console.error(
            "❌ Stop Monitor error:",
            error
        );

    }

}


// ============================================================
// INITIALIZATION
// ============================================================

console.log(
    "🚀 Initializing Monitor page..."
);


if (HOST_ID) {

    loadHost();

    connectMonitor();

} else {

    console.error(
        "❌ No host parameter in URL"
    );

    showPlaceholder(
        "No host selected"
    );

}
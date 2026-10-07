/*
============================================================
REMOTE DESKTOP
MAIN DASHBOARD JAVASCRIPT
============================================================

Server:
    GET /api/server/info

Computers:
    GET /api/hosts

Authentication:
    POST /api/logout

Activity:
    Windows boot time

============================================================
*/


console.log(
    "🖥️ Remote Desktop main.js loaded"
);


/*
============================================================
CONFIGURATION
============================================================
*/

const REFRESH_INTERVAL = 5000;


/*
============================================================
DOM HELPER
============================================================
*/

function getElement(id) {

    return document.getElementById(id);

}


/*
============================================================
TEXT HELPER
============================================================
*/

function setText(
    id,
    value,
    fallback = "—"
) {

    const element =
        getElement(id);


    if (!element) {
        return;
    }


    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {

        element.textContent =
            fallback;

    } else {

        element.textContent =
            value;

    }

}


/*
============================================================
NUMBER FORMAT
============================================================
*/

function formatNumber(
    value,
    decimals = 1
) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {

        return "—";

    }


    const number =
        Number(value);


    if (
        Number.isNaN(number)
    ) {

        return String(value);

    }


    return number.toFixed(
        decimals
    );

}


/*
============================================================
PERCENT FORMAT
============================================================
*/

function formatPercent(
    value
) {

    if (
        value === null ||
        value === undefined
    ) {

        return "—";

    }


    return (
        formatNumber(value)
        + " %"
    );

}


/*
============================================================
DATE FORMAT
============================================================
*/

function formatDateTime(
    value
) {

    if (!value) {

        return "—";

    }


    try {

        const date =
            new Date(value);


        if (
            Number.isNaN(
                date.getTime()
            )
        ) {

            return String(value);

        }


        return date.toLocaleString();

    } catch {

        return String(value);

    }

}


/*
============================================================
ACTIVITY
============================================================

Показывает время работы Windows.

ВАЖНО:

Это НЕ время подключения host.py.

host.py передаёт:

    connected_since

как время запуска Windows.

Поэтому если host.py:

    отключился
    подключился снова

Activity НЕ сбрасывается.

============================================================
*/

function formatOnlineDuration(
    bootTime
) {

    if (!bootTime) {

        return "—";

    }


    const start =
        new Date(
            bootTime
        );


    if (
        Number.isNaN(
            start.getTime()
        )
    ) {

        return "—";

    }


    const now =
        Date.now();


    let seconds =
        Math.floor(
            (
                now -
                start.getTime()
            ) / 1000
        );


    if (seconds < 0) {

        seconds = 0;

    }


    const days =
        Math.floor(
            seconds / 86400
        );


    seconds %= 86400;


    const hours =
        Math.floor(
            seconds / 3600
        );


    seconds %= 3600;


    const minutes =
        Math.floor(
            seconds / 60
        );


    seconds %= 60;


    const result = [];


    if (days > 0) {

        result.push(
            `${days}d`
        );

    }


    if (
        hours > 0 ||
        days > 0
    ) {

        result.push(
            `${hours}h`
        );

    }


    if (
        minutes > 0 ||
        hours > 0 ||
        days > 0
    ) {

        result.push(
            `${minutes}m`
        );

    }


    result.push(
        `${seconds}s`
    );


    return result.join(
        " "
    );

}


/*
============================================================
HTML ESCAPE
============================================================
*/

function escapeHtml(
    value
) {

    return String(
        value === null ||
        value === undefined
            ? ""
            : value
    )

        .replaceAll(
            "&",
            "&amp;"
        )

        .replaceAll(
            "<",
            "&lt;"
        )

        .replaceAll(
            ">",
            "&gt;"
        )

        .replaceAll(
            '"',
            "&quot;"
        )

        .replaceAll(
            "'",
            "&#039;"
        );

}


/*
============================================================
SET STATUS
============================================================
*/

function setStatus(
    id,
    type,
    text
) {

    const element =
        getElement(id);


    if (!element) {

        return;

    }


    element.className =
        `status ${type}`;


    element.innerHTML =
        `
        <span class="status-dot"></span>
        ${escapeHtml(text)}
        `;

}


/*
============================================================
AUTHENTICATION
============================================================
*/

function redirectToLogin() {

    console.log(
        "🔐 Authentication required"
    );


    window.location.href =
        "/login";

}


/*
============================================================
SERVER INFORMATION
============================================================
*/

async function loadServerInfo() {

    try {

        const response =
            await fetch(
                "/api/server/info?t="
                + Date.now(),
                {
                    method: "GET",

                    cache: "no-store",

                    credentials:
                        "same-origin",
                }
            );


        if (
            response.status === 401
        ) {

            redirectToLogin();

            return;

        }


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const data =
            await response.json();


        console.log(
            "🖥️ SERVER INFO:",
            data
        );


        setStatus(
            "server-status",
            "online",
            "Online"
        );


        setText(
            "server-hostname",
            data.hostname
        );


        let operatingSystem =
            data.os || "—";


        if (
            data.os_release
        ) {

            operatingSystem +=
                " " +
                data.os_release;

        }


        setText(
            "server-os",
            operatingSystem
        );


        setText(
            "server-architecture",
            data.architecture
        );


        if (
            data.cpu_count !== null &&
            data.cpu_count !== undefined
        ) {

            setText(
                "server-cpu",
                `${data.cpu_count} logical cores`
            );

        } else {

            setText(
                "server-cpu",
                data.cpu
            );

        }


        setText(
            "server-cpu-usage",
            formatPercent(
                data.cpu_percent
            )
        );


        if (
            data.memory
        ) {

            const memory =
                data.memory;


            let ramText =
                "—";


            if (
                memory.used_gb !== undefined &&
                memory.total_gb !== undefined
            ) {

                ramText =
                    `${formatNumber(
                        memory.used_gb
                    )} GB / ` +
                    `${formatNumber(
                        memory.total_gb
                    )} GB`;


                if (
                    memory.percent !==
                    undefined
                ) {

                    ramText +=
                        ` (${formatNumber(
                            memory.percent
                        )} %)`;

                }

            }


            setText(
                "server-ram",
                ramText
            );

        } else {

            setText(
                "server-ram",
                "—"
            );

        }


        if (
            data.disk
        ) {

            const disk =
                data.disk;


            let diskText =
                "—";


            if (
                disk.free_gb !== undefined &&
                disk.total_gb !== undefined
            ) {

                diskText =
                    `${formatNumber(
                        disk.free_gb
                    )} GB / ` +
                    `${formatNumber(
                        disk.total_gb
                    )} GB`;

            }


            if (
                disk.percent !==
                undefined
            ) {

                diskText +=
                    ` (${formatNumber(
                        disk.percent
                    )} % used)`;

            }


            setText(
                "server-disk",
                diskText
            );

        } else {

            setText(
                "server-disk",
                "—"
            );

        }


        if (
            data.temperature !== null &&
            data.temperature !== undefined
        ) {

            setText(
                "server-temperature",
                `${formatNumber(
                    data.temperature
                )} °C`
            );

        } else {

            setText(
                "server-temperature",
                "Unavailable"
            );

        }


        setText(
            "server-python",
            data.python_version
        );


        setText(
            "server-cpu-load",
            formatPercent(
                data.cpu_percent
            )
        );


        setText(
            "server-registered",
            data.registered_users != null
                ? String(data.registered_users)
                : "—"
        );

        // Page visits must always update (never leave "Loading...")
        {
            const visits = data.page_visits;
            const uniq = data.unique_visitor_ips;
            const v = (visits !== null && visits !== undefined) ? String(visits) : "0";
            const u = (uniq !== null && uniq !== undefined) ? String(uniq) : "0";
            setText("server-page-visits", v + " · unique " + u);
            const el = document.getElementById("server-page-visits");
            if (el) {
                el.textContent = v + " · unique " + u;
            }
        }

        setText(
            "server-active-users",
            data.active_users != null
                ? String(data.active_users)
                : "—"
        );


        // DreamPUT free slots (admin)
        const freeUsed = data.free_used;
        const freeSlots = data.free_slots;
        if (freeSlots != null) {
            const used = freeUsed != null ? freeUsed : "—";
            setText(
                "server-free-slots",
                used + " / " + freeSlots
            );
            const inp = document.getElementById("free-slots-input");
            if (inp) {
                inp.value = String(freeSlots);
            }
        } else {
            setText("server-free-slots", "—");
        }


    } catch (error) {

        const pv = document.getElementById("server-page-visits");
        if (pv && (!pv.textContent || pv.textContent.indexOf("Loading") >= 0)) {
            pv.textContent = "—";
        }

        console.error(
            "❌ SERVER INFO ERROR:",
            error
        );


        setStatus(
            "server-status",
            "offline",
            "Offline"
        );

    }

}


/*
============================================================
LOAD HOSTS
============================================================
*/

async function loadHosts() {

    try {

        const response =
            await fetch(
                "/api/hosts?t="
                + Date.now(),
                {
                    method: "GET",

                    cache: "no-store",

                    credentials:
                        "same-origin",
                }
            );


        if (
            response.status === 401
        ) {

            redirectToLogin();

            return;

        }


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const data =
            await response.json();


        console.log(
            "💻 CONNECTED HOSTS:",
            data
        );


        const hosts =
            Array.isArray(
                data.hosts
            )
                ? data.hosts
                : [];


        renderHosts(
            hosts
        );


    } catch (error) {

        console.error(
            "❌ HOST LIST ERROR:",
            error
        );


        renderHosts(
            []
        );

    }

}


/*
============================================================
RENDER HOSTS
============================================================
*/

function renderHosts(
    hosts
) {

    const container =
        getElement(
            "computer-info"
        );


    if (!container) {

        console.warn(
            "#computer-info not found"
        );

        return;

    }


    const onlineHosts =
        hosts.filter(
            host =>
                host &&
                host.status ===
                "online"
        );


    /*
    --------------------------------------------------------
    TOP STATUS
    --------------------------------------------------------
    */

    if (
        onlineHosts.length
    ) {

        setStatus(
            "computer-status",
            "online",
            `${onlineHosts.length} Online`
        );

    } else {

        setStatus(
            "computer-status",
            "offline",
            "No computers online"
        );

    }


    /*
    --------------------------------------------------------
    NO HOSTS
    --------------------------------------------------------
    */

    if (
        onlineHosts.length === 0
    ) {

        container.innerHTML = `

            <div class="computer-empty">

                <div
                    style="
                        font-size: 36px;
                        margin-bottom: 10px;
                    "
                >
                    🖥️
                </div>

                <strong>
                    No computers online
                </strong>

                <div
                    style="
                        margin-top: 6px;
                        color: #64748b;
                        font-size: 13px;
                    "
                >
                    Start host.py on a computer
                    to connect it.
                </div>

            </div>

        `;


        return;

    }


    /*
    --------------------------------------------------------
    ALL HOSTS
    --------------------------------------------------------
    */

    container.innerHTML =
        onlineHosts
            .map(
                renderHostCard
            )
            .join("");

}


/*
============================================================
HOST CARD
============================================================
*/

function renderHostCard(
    host
) {

    const computerName =
        escapeHtml(
            host.computer_name ||
            "Unknown PC"
        );


    const username =
        escapeHtml(
            host.username ||
            "Unknown"
        );


    let operatingSystem =
        host.os ||
        "Unknown";


    if (
        host.os_release
    ) {

        operatingSystem +=
            " " +
            host.os_release;

    }


    operatingSystem =
        escapeHtml(
            operatingSystem
        );


    const python =
        escapeHtml(
            host.python_version ||
            "—"
        );


    /*
    --------------------------------------------------------
    CPU
    --------------------------------------------------------
    */

    let cpu =
        "—";


    if (
        host.cpu_percent !==
        undefined &&
        host.cpu_percent !==
        null
    ) {

        cpu =
            `${formatNumber(
                host.cpu_percent
            )} %`;

    }


    /*
    --------------------------------------------------------
    RAM
    --------------------------------------------------------
    */

    let ram =
        "—";


    if (
        host.memory &&
        typeof host.memory ===
        "object"
    ) {

        if (
            host.memory.used_gb !==
            undefined &&
            host.memory.total_gb !==
            undefined
        ) {

            ram =
                `${formatNumber(
                    host.memory.used_gb
                )} GB / ` +
                `${formatNumber(
                    host.memory.total_gb
                )} GB`;

        }


        if (
            host.memory.percent !==
            undefined
        ) {

            ram +=
                ` (${formatNumber(
                    host.memory.percent
                )} %)`;

        }

    }


    /*
    --------------------------------------------------------
    DISK
    --------------------------------------------------------
    */

    let disk =
        "—";


    if (
        host.disk &&
        typeof host.disk ===
        "object"
    ) {

        if (
            host.disk.free_gb !==
            undefined &&
            host.disk.total_gb !==
            undefined
        ) {

            disk =
                `${formatNumber(
                    host.disk.free_gb
                )} GB / ` +
                `${formatNumber(
                    host.disk.total_gb
                )} GB`;

        }

    }


    /*
    --------------------------------------------------------
    TEMPERATURE
    --------------------------------------------------------
    */

    let temperature =
        "—";


    if (
        host.cpu_temperature !==
        undefined &&
        host.cpu_temperature !==
        null
    ) {

        temperature =
            `${formatNumber(
                host.cpu_temperature
            )} °C`;

    }


    /*
    --------------------------------------------------------
    ACTIVITY
    --------------------------------------------------------
    */

    /*
    IMPORTANT:

    connected_since now contains
    WINDOWS BOOT TIME.

    It does NOT contain host.py
    connection time.
    */

    const bootTime =
        host.connected_since ||
        "";


    const activity =
        host.windows_uptime ||
        "—";


    /*
    --------------------------------------------------------
    HOST ID
    --------------------------------------------------------
    */

    const hostId =
        encodeURIComponent(
            host.host_id || ""
        );


    /*
    --------------------------------------------------------
    CARD
    --------------------------------------------------------
    */

    return `

        <div
            class="computer-online-card"
        >

            <div
                class="computer-online-header"
            >

                <div>

                    <div
                        class="computer-online-status"
                    >

                        <span
                            class="status-dot online"
                        ></span>

                        <strong>
                            Online
                        </strong>

                    </div>


                    <h3
                        class="computer-name-title"
                    >

                        💻 ${computerName}

                    </h3>

                </div>

            </div>


            <div
                class="computer-info-list"
            >

                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        User
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${username}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        Operating System
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${operatingSystem}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        Python
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${python}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        CPU Usage
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${cpu}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        RAM
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${escapeHtml(ram)}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        Disk
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${escapeHtml(disk)}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        Temperature
                    </span>

                    <strong
                        class="info-value"
                    >
                        ${temperature}
                    </strong>

                </div>


                <div
                    class="info-row"
                >

                    <span
                        class="info-label"
                    >
                        Activity
                    </span>

                    <strong
                        class="info-value activity-time"
                    >
                        ${escapeHtml(activity)}
                    </strong>

                </div>

            </div>


            <div
                class="computer-actions"
            >

                <button
                    type="button"
                    onclick="openControl('${hostId}')"
                >
                    Control
                </button>

                <button
                    type="button"
                    onclick="openMonitor('${hostId}')"
                >
                    🖥 Monitor
                </button>


                <button
                    type="button"
                    onclick="openWebcam('${hostId}')"
                >
                    📷 Web Camera
                </button>

                <button
                    type="button"
                    onclick="openPowerShell('${hostId}')"
                >
                    💻 PowerShell
                </button>

                <button
                    type="button"
                    onclick="openFiles('${hostId}')"
                >
                    📁 Files
                </button>

            </div>

        </div>

    `;

}


/*
============================================================
ACTIVITY TIMER
============================================================

Обновляется каждую секунду.

Используется время запуска Windows,
а НЕ время подключения host.py.

============================================================
*/

function updateActivityTimes() {

    const elements =
        document.querySelectorAll(
            "[data-boot-time]"
        );


    elements.forEach(
        element => {

            const bootTime =
                element.dataset
                    .bootTime;


            if (!bootTime) {

                return;

            }


            element.textContent =
                formatOnlineDuration(
                    bootTime
                );

        }
    );

}


/*
============================================================
MONITOR
============================================================
*/

function openMonitor(
    hostId
) {

    window.location.href =
        "/monitor?host=" +
        encodeURIComponent(
            hostId
        );

}

/*
============================================================
POWERSHELL
============================================================
*/

function openFiles(
    hostId
) {
    window.location.href =
        "/files?host=" +
        encodeURIComponent(
            hostId
        );
}


function openPowerShell(
    hostId
) {

    window.location.href =
        "/powershell?host=" +
        encodeURIComponent(
            hostId
        );

}

/*
============================================================
WEBCAM
============================================================
*/

function openWebcam(
    hostId
) {

    window.location.href =
        "/webcam?host=" +
        encodeURIComponent(
            hostId
        );

}


/*
============================================================
REMOTE CONTROL
============================================================
*/

function openControl(
    hostId
) {

    window.location.href =
        "/control?host=" +
        encodeURIComponent(
            hostId
        );

}


/*
============================================================
LOGOUT
============================================================
*/

async function logout() {

    try {

        await fetch(
            "/api/logout",
            {
                method: "POST",

                credentials:
                    "same-origin"
            }
        );

    } catch (error) {

        console.error(
            "❌ Logout error:",
            error
        );

    }


    window.location.href =
        "/login";

}


/*
============================================================
INITIALIZATION
============================================================
*/

document.addEventListener(
    "DOMContentLoaded",
    function () {

        console.log(
            "🚀 Dashboard initialized"
        );


        /*
        --------------------------------------------
        LOGOUT
        --------------------------------------------
        */

        const logoutButton =
            getElement(
                "logout-button"
            );


        if (logoutButton) {

            logoutButton.addEventListener(
                "click",
                logout
            );

        }


        /*
        --------------------------------------------
        DreamPUT free slots admin
        --------------------------------------------
        */

        const freeSlotsBtn =
            document.getElementById(
                "free-slots-save"
            );

        if (freeSlotsBtn) {

            freeSlotsBtn.addEventListener(
                "click",
                async function () {

                    const inp =
                        document.getElementById(
                            "free-slots-input"
                        );

                    const statusEl =
                        document.getElementById(
                            "free-slots-status"
                        );

                    const slots = parseInt(
                        (inp && inp.value) || "",
                        10
                    );

                    if (
                        !Number.isFinite(slots) ||
                        slots < 0
                    ) {

                        if (statusEl) {
                            statusEl.textContent =
                                "Enter a valid number";
                            statusEl.style.color =
                                "#f87171";
                        }

                        return;

                    }

                    if (statusEl) {
                        statusEl.textContent =
                            "Saving…";
                        statusEl.style.color =
                            "#94a3b8";
                    }

                    try {

                        const res =
                            await fetch(
                                "/api/admin/dreamput-free-slots",
                                {
                                    method: "POST",
                                    credentials:
                                        "same-origin",
                                    headers: {
                                        "Content-Type":
                                            "application/json",
                                    },
                                    body: JSON.stringify({
                                        slots: slots,
                                    }),
                                }
                            );

                        const data =
                            await res.json();

                        if (
                            !res.ok ||
                            !data.ok
                        ) {

                            throw new Error(
                                data.error ||
                                    data.detail ||
                                    ("HTTP " + res.status)
                            );

                        }

                        if (statusEl) {
                            statusEl.textContent =
                                "Saved: " +
                                data.free_slots +
                                " slots";
                            statusEl.style.color =
                                "#4ade80";
                        }

                        loadServerInfo();

                    } catch (e) {

                        if (statusEl) {
                            statusEl.textContent =
                                "Error: " +
                                (e.message || e);
                            statusEl.style.color =
                                "#f87171";
                        }

                    }

                }
            );

        }


        /*
        --------------------------------------------
        FIRST LOAD
        --------------------------------------------
        */

        loadServerInfo();

        loadHosts();


        /*
        --------------------------------------------
        REFRESH
        --------------------------------------------
        */

        setInterval(
            loadServerInfo,
            REFRESH_INTERVAL
        );


        setInterval(
            loadHosts,
            REFRESH_INTERVAL
        );


        /*
        --------------------------------------------
        ACTIVITY
        --------------------------------------------
        */

        setInterval(
            updateActivityTimes,
            1000
        );

    }
);
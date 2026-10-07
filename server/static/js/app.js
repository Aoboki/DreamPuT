/*
============================================================
REMOTE DESKTOP — MAIN PAGE
============================================================

Новый проект.

Этот файл НЕ является старым app.js.

Назначение:
- загрузка информации о Raspberry Pi
- загрузка информации о подключённых ПК
- обновление данных
- обработка ошибок авторизации
- подготовка кнопок функций

API:
    GET /api/server/info
    GET /api/host/status

============================================================
*/

console.log("🖥️ Remote Desktop — new app.js loaded");


/*
============================================================
CONFIGURATION
============================================================
*/

const SERVER_INFO_INTERVAL = 3000;
const HOST_INFO_INTERVAL = 3000;


/*
============================================================
HELPERS
============================================================
*/

function $(id) {
    return document.getElementById(id);
}


function setText(id, value, fallback = "—") {

    const element = $(id);

    if (!element) {
        console.warn(`Element not found: #${id}`);
        return;
    }

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        element.textContent = fallback;
    } else {
        element.textContent = value;
    }
}


function formatNumber(value, decimals = 1) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (Number.isNaN(number)) {
        return value;
    }

    return number.toFixed(decimals);
}


function formatPercent(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    return `${formatNumber(value)} %`;
}


function formatTemperature(value) {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    return `${formatNumber(value)} °C`;
}


function formatDateTime(value) {

    if (!value) {
        return "—";
    }

    try {

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return value;
        }

        return date.toLocaleString();

    } catch {

        return value;

    }
}


/*
============================================================
STATUS DOT
============================================================
*/

function setStatusDot(id, online) {

    const element = $(id);

    if (!element) {
        return;
    }

    element.classList.remove(
        "online",
        "offline"
    );

    element.classList.add(
        online ? "online" : "offline"
    );
}


/*
============================================================
SERVER STATUS
============================================================
*/

function setServerStatus(online) {

    const status = $("raspberry-status");

    const indicator =
        $("raspberry-indicator");

    if (status) {

        status.textContent =
            online
                ? "Online"
                : "Offline";

    }

    if (indicator) {

        indicator.classList.remove(
            "online",
            "offline"
        );

        indicator.classList.add(
            online
                ? "online"
                : "offline"
        );

    }

}


/*
============================================================
LOAD SERVER INFORMATION
============================================================
*/

async function loadServerInfo() {

    try {

        const response = await fetch(
            "/api/server/info?t=" +
            Date.now(),
            {
                method: "GET",

                cache: "no-store",

                credentials: "same-origin"
            }
        );


        /*
        --------------------------------------------------------
        AUTH ERROR
        --------------------------------------------------------
        */

        if (response.status === 401) {

            console.warn(
                "🔐 Authentication required"
            );

            window.location.href =
                "/login";

            return;
        }


        /*
        --------------------------------------------------------
        OTHER ERROR
        --------------------------------------------------------
        */

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


        /*
        --------------------------------------------------------
        SERVER STATUS
        --------------------------------------------------------
        */

        setServerStatus(true);


        /*
        --------------------------------------------------------
        OPERATING SYSTEM
        --------------------------------------------------------
        */

        let operatingSystem = "—";


        if (data.os) {

            operatingSystem =
                data.os;

        }


        if (
            data.os_release &&
            data.os_release !== data.os
        ) {

            operatingSystem +=
                ` ${data.os_release}`;

        }


        setText(
            "server-os",
            operatingSystem
        );


        /*
        --------------------------------------------------------
        ARCHITECTURE
        --------------------------------------------------------
        */

        setText(
            "server-architecture",
            data.architecture
        );


        /*
        --------------------------------------------------------
        CPU COUNT
        --------------------------------------------------------
        */

        let cpuCount =
            data.cpu_count;


        if (
            cpuCount === null ||
            cpuCount === undefined
        ) {

            cpuCount =
                data.cpu_cores;

        }


        if (
            cpuCount !== null &&
            cpuCount !== undefined
        ) {

            setText(
                "server-cpu",
                `${cpuCount} logical cores`
            );

        } else {

            setText(
                "server-cpu",
                "—"
            );

        }


        /*
        --------------------------------------------------------
        CPU USAGE
        --------------------------------------------------------
        */

        let cpuUsage =
            data.cpu_percent;


        if (
            cpuUsage === null ||
            cpuUsage === undefined
        ) {

            cpuUsage =
                data.cpu_usage;

        }


        if (
            cpuUsage !== null &&
            cpuUsage !== undefined
        ) {

            setText(
                "server-cpu-usage",
                formatPercent(cpuUsage)
            );

        } else {

            setText(
                "server-cpu-usage",
                "—"
            );

        }


        /*
        --------------------------------------------------------
        RAM
        --------------------------------------------------------
        */

        const memory =
            data.memory;


        if (
            memory &&
            typeof memory === "object"
        ) {

            /*
            Example:

            {
                total: ...,
                used: ...,
                available: ...,
                percent: 35.2
            }
            */

            if (
                memory.percent !==
                undefined
            ) {

                setText(
                    "server-ram",
                    formatPercent(
                        memory.percent
                    )
                );

            } else {

                setText(
                    "server-ram",
                    "—"
                );

            }

        } else if (
            memory !== null &&
            memory !== undefined
        ) {

            setText(
                "server-ram",
                formatPercent(memory)
            );

        } else {

            setText(
                "server-ram",
                "—"
            );

        }


        /*
        --------------------------------------------------------
        DISK
        --------------------------------------------------------
        */

        const disk =
            data.disk;


        if (
            disk &&
            typeof disk === "object"
        ) {

            /*
            Example:

            {
                total: ...,
                used: ...,
                free: ...,
                percent: ...
            }
            */

            let diskText = "—";


            if (
                disk.free_gb !==
                undefined
            ) {

                diskText =
                    `${formatNumber(
                        disk.free_gb,
                        1
                    )} GB free`;

            } else if (
                disk.free !==
                undefined
            ) {

                diskText =
                    `${formatNumber(
                        disk.free,
                        1
                    )} GB free`;

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


        /*
        --------------------------------------------------------
        TEMPERATURE
        --------------------------------------------------------
        */

        let temperature =
            data.temperature;


        if (
            temperature === null ||
            temperature === undefined
        ) {

            temperature =
                data.cpu_temperature;

        }


        if (
            temperature &&
            typeof temperature === "object"
        ) {

            temperature =
                temperature.value ??
                temperature.celsius ??
                temperature.temperature;

        }


        setText(
            "server-temperature",
            formatTemperature(
                temperature
            )
        );


        /*
        --------------------------------------------------------
        SERVER TIME
        --------------------------------------------------------
        */

        setText(
            "server-time",
            formatDateTime(
                data.time
            )
        );


    } catch (error) {

        console.error(
            "❌ SERVER INFO ERROR:",
            error
        );


        setServerStatus(false);


        /*
        Не затираем архитектуру/CPU,
        если они уже были показаны.
        */

        setText(
            "server-cpu-usage",
            "Unavailable"
        );

        setText(
            "server-ram",
            "Unavailable"
        );

        setText(
            "server-disk",
            "Unavailable"
        );

        setText(
            "server-time",
            "Unavailable"
        );

    }

}


/*
============================================================
LOAD HOST / PC INFORMATION
============================================================
*/

async function loadHostInfo() {

    try {

        const response = await fetch(
            "/api/host/status?t=" +
            Date.now(),
            {
                method: "GET",

                cache: "no-store",

                credentials: "same-origin"
            }
        );


        /*
        --------------------------------------------------------
        AUTH ERROR
        --------------------------------------------------------
        */

        if (response.status === 401) {

            console.warn(
                "🔐 Authentication required"
            );

            window.location.href =
                "/login";

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
            "💻 HOST INFO:",
            data
        );


        /*
        --------------------------------------------------------
        OFFLINE
        --------------------------------------------------------
        */

        if (
            data.status !==
            "online"
        ) {

            setHostOffline();

            return;

        }


        /*
        --------------------------------------------------------
        ONLINE
        --------------------------------------------------------
        */

        setHostOnline();


        /*
        USER
        */

        setText(
            "host-username",
            data.username
        );


        /*
        COMPUTER
        */

        setText(
            "host-computer",
            data.computer_name ||
            data.name
        );


        /*
        OS
        */

        let hostOS =
            data.os || "—";


        if (
            data.os_release
        ) {

            hostOS +=
                ` ${data.os_release}`;

        }


        setText(
            "host-os",
            hostOS
        );


        /*
        PYTHON
        */

        setText(
            "host-python",
            data.python_version
        );


        /*
        CPU
        */

        if (
            data.cpu_percent !==
            undefined &&
            data.cpu_percent !==
            null
        ) {

            setText(
                "host-cpu",
                formatPercent(
                    data.cpu_percent
                )
            );

        }


        /*
        RAM
        */

        if (
            data.memory !==
            undefined &&
            data.memory !==
            null
        ) {

            if (
                typeof data.memory ===
                "object"
            ) {

                setText(
                    "host-ram",
                    formatPercent(
                        data.memory.percent
                    )
                );

            } else {

                setText(
                    "host-ram",
                    formatPercent(
                        data.memory
                    )
                );

            }

        }


        /*
        DISK
        */

        if (
            data.disk &&
            typeof data.disk ===
            "object"
        ) {

            if (
                data.disk.free_gb !==
                undefined
            ) {

                setText(
                    "host-disk",
                    `${formatNumber(
                        data.disk.free_gb
                    )} GB free`
                );

            } else {

                setText(
                    "host-disk",
                    "—"
                );

            }

        }


        /*
        TEMPERATURE
        */

        if (
            data.cpu_temperature !==
            undefined &&
            data.cpu_temperature !==
            null
        ) {

            setText(
                "host-temperature",
                formatTemperature(
                    data.cpu_temperature
                )
            );

        }


        /*
        LAST SEEN
        */

        setText(
            "host-last-seen",
            formatDateTime(
                data.last_seen
            )
        );


        /*
        CONNECTED SINCE
        */

        setText(
            "host-connected-since",
            formatDateTime(
                data.connected_since
            )
        );


    } catch (error) {

        console.error(
            "❌ HOST INFO ERROR:",
            error
        );

        setHostOffline();

    }

}


/*
============================================================
HOST ONLINE
============================================================
*/

function setHostOnline() {

    setStatusDot(
        "host-indicator",
        true
    );


    setStatusDot(
        "computer-indicator",
        true
    );


    setText(
        "host-status",
        "Online"
    );


    setText(
        "computer-status",
        "Online"
    );

}


/*
============================================================
HOST OFFLINE
============================================================
*/

function setHostOffline() {

    setStatusDot(
        "host-indicator",
        false
    );


    setStatusDot(
        "computer-indicator",
        false
    );


    setText(
        "host-status",
        "Offline"
    );


    setText(
        "computer-status",
        "Offline"
    );


    setText(
        "host-username",
        "—"
    );


    setText(
        "host-computer",
        "—"
    );


    setText(
        "host-os",
        "—"
    );


    setText(
        "host-python",
        "—"
    );


    setText(
        "host-cpu",
        "—"
    );


    setText(
        "host-ram",
        "—"
    );


    setText(
        "host-disk",
        "—"
    );


    setText(
        "host-temperature",
        "—"
    );


    setText(
        "host-last-seen",
        "—"
    );


    setText(
        "host-connected-since",
        "—"
    );

}


/*
============================================================
FUNCTION BUTTONS
============================================================
*/

function setupFunctionButtons() {

    const buttons =
        document.querySelectorAll(
            "[data-function]"
        );


    buttons.forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    const functionName =
                        button.dataset.function;


                    console.log(
                        `Function selected: ${functionName}`
                    );


                    /*
                    ------------------------------------------------
                    Пока страницы функций ещё нет.
                    Поэтому просто показываем сообщение.
                    ------------------------------------------------
                    */

                    if (
                        functionName ===
                        "monitor"
                    ) {

                        window.location.href =
                            "/monitor";

                        return;

                    }


                    if (
                        functionName ===
                        "webcam"
                    ) {

                        window.location.href =
                            "/webcam";

                        return;

                    }


                    console.log(
                        `⚠️ Function not implemented: ${functionName}`
                    );

                }
            );

        }
    );

}


/*
============================================================
INITIALIZATION
============================================================
*/

async function initialize() {

    console.log(
        "🚀 Initializing Remote Desktop..."
    );


    /*
    --------------------------------------------------------
    SERVER
    --------------------------------------------------------
    */

    await loadServerInfo();


    /*
    --------------------------------------------------------
    HOST
    --------------------------------------------------------
    */

    await loadHostInfo();


    /*
    --------------------------------------------------------
    BUTTONS
    --------------------------------------------------------
    */

    setupFunctionButtons();


    /*
    --------------------------------------------------------
    AUTO REFRESH
    --------------------------------------------------------
    */

    setInterval(
        loadServerInfo,
        SERVER_INFO_INTERVAL
    );


    setInterval(
        loadHostInfo,
        HOST_INFO_INTERVAL
    );


    console.log(
        "🟢 Remote Desktop initialized"
    );

}


/*
============================================================
START
============================================================
*/

if (
    document.readyState ===
    "loading"
) {

    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );

} else {

    initialize();

}
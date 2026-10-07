"use strict";

/* ============================================================
   REMOTE POWERSHELL CONSOLE
   ============================================================ */

console.log("🔥 POWERSHELL.JS LOADED");


// ============================================================
// HOST ID
// ============================================================

const params = new URLSearchParams(
    window.location.search
);

const HOST_ID = (
    params.get("host") || ""
).trim();


// ============================================================
// ELEMENTS
// ============================================================

const hostIdElement =
    document.getElementById("hostId");

const statusDot =
    document.getElementById("statusDot");

const statusText =
    document.getElementById("statusText");

const output =
    document.getElementById("output");

const commandInput =
    document.getElementById("commandInput");

const sendButton =
    document.getElementById("sendButton");

const startButton =
    document.getElementById("startButton");

const stopButton =
    document.getElementById("stopButton");

const executeButton =
    document.getElementById("executeButton");

const clearButton =
    document.getElementById("clearButton");


// ============================================================
// STATE
// ============================================================

let powershellRunning = false;

let commandRunning = false;

let powershellSocket = null;

let reconnectTimer = null;

let manuallyClosed = false;

let commandCounter = 0;


// ============================================================
// STATUS
// ============================================================

function setStatus(
    online,
    text
) {

    if (statusText) {

        statusText.textContent =
            text;
    }

    if (statusDot) {

        statusDot.classList.remove(
            "online",
            "error"
        );

        statusDot.classList.add(
            online
                ? "online"
                : "error"
        );
    }
}


// ============================================================
// OUTPUT
// ============================================================

function addOutput(
    text,
    className = ""
) {

    if (!output) {

        console.warn(
            "PowerShell output element not found"
        );

        return;
    }

    const line =
        document.createElement("div");

    line.className =
        "output-line " +
        className;

    line.textContent =
        text;

    output.appendChild(
        line
    );

    output.scrollTop =
        output.scrollHeight;
}


// ============================================================
// FORMAT OUTPUT
// ============================================================

function addMultilineOutput(
    text,
    className = "output-result"
) {

    if (
        text === undefined ||
        text === null
    ) {

        return;
    }

    const value =
        String(text);

    if (!value) {

        return;
    }

    const lines =
        value.split(/\r?\n/);

    for (const lineText of lines) {

        addOutput(
            lineText,
            className
        );
    }
}


// ============================================================
// SET BUTTON STATE
// ============================================================

function updateButtons() {

    const running =
        powershellRunning;

    const socketOpen =
        powershellSocket &&
        powershellSocket.readyState ===
            WebSocket.OPEN;

    // --------------------------------------------------------
    // START
    // --------------------------------------------------------

    if (startButton) {

        startButton.disabled =
            running;
    }

    // --------------------------------------------------------
    // EXECUTE
    // --------------------------------------------------------

    if (executeButton) {

        executeButton.disabled =
            !running ||
            !socketOpen ||
            commandRunning;
    }

    // --------------------------------------------------------
    // SEND
    // --------------------------------------------------------

    if (sendButton) {

        sendButton.disabled =
            !running ||
            !socketOpen ||
            commandRunning;
    }

    // --------------------------------------------------------
    // STOP
    // --------------------------------------------------------

    if (stopButton) {

        stopButton.disabled =
            !running;
    }
}


// ============================================================
// BUILD WEBSOCKET URL
// ============================================================

function getWebSocketURL() {

    const protocol =
        window.location.protocol === "https:"
            ? "wss:"
            : "ws:";

    const host =
        window.location.host;

    return (
        protocol +
        "//" +
        host +
        "/api/powershell/ws/browser/" +
        encodeURIComponent(
            HOST_ID
        )
    );
}


// ============================================================
// CONNECT POWERSHELL WEBSOCKET
// ============================================================

function connectPowerShellWebSocket() {

    if (!HOST_ID) {

        return;
    }

    // --------------------------------------------------------
    // Already connected
    // --------------------------------------------------------

    if (
        powershellSocket &&
        (
            powershellSocket.readyState ===
                WebSocket.OPEN ||
            powershellSocket.readyState ===
                WebSocket.CONNECTING
        )
    ) {

        return;
    }

    manuallyClosed = false;

    const url =
        getWebSocketURL();

    console.log(
        "🔌 Connecting PowerShell WebSocket:"
    );

    console.log(
        url
    );

    setStatus(
        false,
        "Connecting..."
    );

    try {

        powershellSocket =
            new WebSocket(
                url
            );

    } catch (error) {

        console.error(
            "❌ WebSocket creation error:",
            error
        );

        setStatus(
            false,
            "WebSocket error"
        );

        scheduleReconnect();

        return;
    }


    // ========================================================
    // OPEN
    // ========================================================

    powershellSocket.onopen =
        function() {

            console.log(
                "🟢 PowerShell WebSocket connected"
            );

            setStatus(
                powershellRunning,
                powershellRunning
                    ? "PowerShell running"
                    : "Connected"
            );

            updateButtons();
        };


    // ========================================================
    // MESSAGE
    // ========================================================

    powershellSocket.onmessage =
        function(event) {

            handlePowerShellMessage(
                event.data
            );
        };


    // ========================================================
    // ERROR
    // ========================================================

    powershellSocket.onerror =
        function(error) {

            console.error(
                "❌ PowerShell WebSocket error:",
                error
            );

            setStatus(
                false,
                "WebSocket error"
            );
        };


    // ========================================================
    // CLOSE
    // ========================================================

    powershellSocket.onclose =
        function(event) {

            console.log(
                "🔴 PowerShell WebSocket closed"
            );

            console.log(
                "   Code:",
                event.code
            );

            console.log(
                "   Reason:",
                event.reason
            );

            powershellSocket =
                null;

            updateButtons();

            if (!manuallyClosed) {

                setStatus(
                    false,
                    "Disconnected"
                );

                scheduleReconnect();
            }
        };
}


// ============================================================
// RECONNECT
// ============================================================

function scheduleReconnect() {

    if (manuallyClosed) {

        return;
    }

    if (reconnectTimer) {

        return;
    }

    reconnectTimer =
        setTimeout(
            function() {

                reconnectTimer =
                    null;

                connectPowerShellWebSocket();

            },
            3000
        );
}


// ============================================================
// HANDLE WEBSOCKET MESSAGE
// ============================================================

function handlePowerShellMessage(
    rawMessage
) {

    console.log(
        "📥 PowerShell WebSocket message:",
        rawMessage
    );

    let data;

    try {

        data =
            JSON.parse(
                rawMessage
            );

    } catch (error) {

        console.error(
            "❌ Invalid PowerShell WebSocket JSON:",
            error
        );

        addOutput(
            "ERROR: Invalid message from server.",
            "output-error"
        );

        return;
    }


    const type =
        data.type;


    // ========================================================
    // STATE
    // ========================================================

    if (
        type ===
        "powershell_state"
    ) {

        powershellRunning =
            Boolean(
                data.running
            );

        commandRunning =
            false;

        console.log(
            "💻 PowerShell state:",
            data
        );

        if (powershellRunning) {

            setStatus(
                true,
                "PowerShell running"
            );

        } else {

            setStatus(
                true,
                "PowerShell stopped"
            );
        }

        updateButtons();

        return;
    }


    // ========================================================
    // STARTED
    // ========================================================

    if (
        type ===
        "powershell_started"
    ) {

        powershellRunning =
            true;

        commandRunning =
            false;

        setStatus(
            true,
            "PowerShell running"
        );

        addOutput(
            "✓ PowerShell started on host.",
            "output-success"
        );

        if (
            data.pid !== undefined &&
            data.pid !== null
        ) {

            addOutput(
                `PID: ${data.pid}`,
                "output-system"
            );
        }

        updateButtons();

        if (commandInput) {

            commandInput.focus();
        }

        return;
    }


    // ========================================================
    // STATUS
    // ========================================================

    if (
        type ===
        "powershell_status"
    ) {

        powershellRunning =
            Boolean(
                data.running
            );

        setStatus(
            true,
            powershellRunning
                ? "PowerShell running"
                : "PowerShell stopped"
        );

        updateButtons();

        return;
    }


    // ========================================================
    // OUTPUT
   // #
   // # Потоковый вывод
   // # ========================================================

    if (
        type ===
        "powershell_output"
    ) {

        const stream =
            data.stream ||
            "stdout";

        const text =
            data.output || "";

        if (text) {

            addMultilineOutput(
                text,
                stream === "stderr"
                    ? "output-error"
                    : "output-result"
            );
        }

        return;
    }


    // ========================================================
    // RESULT
    // RESULT #
    // RESULT# Основной результат команды
    // RESULT# ========================================================
    // RESULT
    if (
        type ===
        "powershell_result"
    ) {

        console.log(
            "💻 PowerShell result:",
            data
        );

        commandRunning =
            false;

        const success =
            Boolean(
                data.success
            );

        const result =
            data.output;

        const error =
            data.error;

        if (success) {

            setStatus(
                true,
                "Connected"
            );

            if (
                result !== undefined &&
                result !== null &&
                String(result).length > 0
            ) {

                addMultilineOutput(
                    result,
                    "output-result"
                );

            } else {

                addOutput(
                    "✓ Command completed.",
                    "output-success"
                );
            }

        } else {

            setStatus(
                true,
                "Command error"
            );

            if (
                error !== undefined &&
                error !== null &&
                String(error).length > 0
            ) {

                addMultilineOutput(
                    error,
                    "output-error"
                );

            } else {

                addOutput(
                    "✗ PowerShell command failed.",
                    "output-error"
                );
            }
        }

        updateButtons();

        if (commandInput) {

            commandInput.focus();
        }

        return;
    }


    // ========================================================
    // FINISHED
    //# ========================================================

    if (
        type ===
        "powershell_finished"
    ) {

        powershellRunning =
            false;

        commandRunning =
            false;

        const exitCode =
            data.exit_code;

        setStatus(
            true,
            "PowerShell stopped"
        );

        if (
            exitCode !== undefined &&
            exitCode !== null
        ) {

            addOutput(
                `PowerShell exited with code ${exitCode}.`,
                exitCode === 0
                    ? "output-success"
                    : "output-error"
            );
        } else {

            addOutput(
                "PowerShell process finished.",
                "output-system"
            );
        }

        updateButtons();

        return;
    }


    // ========================================================
    // UNKNOWN MESSAGE
    // ========================================================

    console.warn(
        "⚠️ Unknown PowerShell message type:",
        type,
        data
    );
}


// ============================================================
// START POWERSHELL
// ============================================================

async function startPowerShell() {

    if (!HOST_ID) {

        return false;
    }

    if (powershellRunning) {

        addOutput(
            "PowerShell is already running.",
            "output-system"
        );

        return true;
    }

    if (startButton) {

        startButton.disabled =
            true;
    }

    setStatus(
        false,
        "Starting PowerShell..."
    );

    addOutput(
        "▶ Starting PowerShell...",
        "output-system"
    );

    try {

        const response =
            await fetch(
                "/api/powershell/start/" +
                encodeURIComponent(
                    HOST_ID
                ),
                {
                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    headers: {
                        "Content-Type":
                            "application/json"
                    }
                }
            );

        let data = {};

        try {

            data =
                await response.json();

        } catch {

            data = {};
        }

        console.log(
            "📥 PowerShell start response:",
            data
        );

        if (!response.ok) {

            throw new Error(
                data.error ||
                data.detail ||
                `HTTP ${response.status}`
            );
        }

        // ----------------------------------------------------
        // НЕ считаем PowerShell запущенным окончательно
        // до получения powershell_started.
        // ----------------------------------------------------

        addOutput(
            "✓ Start command sent to host.",
            "output-success"
        );

        setStatus(
            true,
            "Starting..."
        );

        updateButtons();

        return true;

    } catch (error) {

        console.error(
            "PowerShell start error:",
            error
        );

        powershellRunning =
            false;

        setStatus(
            false,
            "Host unavailable"
        );

        addOutput(
            `✗ Start error: ${error.message}`,
            "output-error"
        );

        if (startButton) {

            startButton.disabled =
                false;
        }

        updateButtons();

        return false;
    }
}


// ============================================================
// EXECUTE COMMAND
// ============================================================

async function executeCommand() {

    if (!commandInput) {

        return;
    }

    const command =
        commandInput.value.trim();

    if (!command) {

        return;
    }

    if (!HOST_ID) {

        addOutput(
            "ERROR: Host ID is missing.",
            "output-error"
        );

        return;
    }

    if (!powershellRunning) {

        addOutput(
            "ERROR: PowerShell is not running.",
            "output-error"
        );

        return;
    }

    if (
        !powershellSocket ||
        powershellSocket.readyState !==
            WebSocket.OPEN
    ) {

        addOutput(
            "ERROR: PowerShell WebSocket is not connected.",
            "output-error"
        );

        return;
    }

    // --------------------------------------------------------
    // COMMAND ID
    // --------------------------------------------------------

    commandCounter++;

    const localCommandId =
        commandCounter;

    // --------------------------------------------------------
    // SHOW COMMAND
    // --------------------------------------------------------

    addOutput(
        `PS ${HOST_ID}> ${command}`,
        "output-command"
    );

    commandInput.value = "";

    commandRunning =
        true;

    updateButtons();

    // --------------------------------------------------------
    // SEND HTTP REQUEST
   // #
   // # ВАЖНО:
    //#
   // # Здесь мы НЕ ждём PowerShell output.
    //#
    //# HTTP response = команда принята сервером.
   // #
    //# Реальный output придёт через WebSocket.
   // # --------------------------------------------------------

    try {

        const response =
            await fetch(
                `/api/powershell/execute/${encodeURIComponent(
                    HOST_ID
                )}`,
                {
                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            command:
                                command
                        })
                }
            );

        let data = {};

        try {

            data =
                await response.json();

        } catch {

            data = {};
        }

        console.log(
            "📥 PowerShell execute HTTP response:",
            data
        );

        if (!response.ok) {

            throw new Error(
                data.error ||
                data.detail ||
                `HTTP ${response.status}`
            );
        }

        // ----------------------------------------------------
        // Команда передана сервером.
        //
        // Не показываем здесь результат.
        // Он придёт через WebSocket.
        // ----------------------------------------------------

        console.log(
            `✓ PowerShell command ${localCommandId} accepted`
        );

        setStatus(
            true,
            "Command running..."
        );

    } catch (error) {

        console.error(
            "❌ PowerShell execute error:",
            error
        );

        commandRunning =
            false;

        addOutput(
            `ERROR: ${error.message}`,
            "output-error"
        );

        setStatus(
            false,
            "Connection error"
        );

        updateButtons();

        if (commandInput) {

            commandInput.focus();
        }
    }
}


// ============================================================
// STOP CURRENT COMMAND
// ============================================================

async function stopCurrentCommand() {

    if (!HOST_ID) {

        return;
    }

    addOutput(
        "⏹ Stopping current PowerShell command...",
        "output-system"
    );

    try {

        const response =
            await fetch(
                "/api/powershell/stop-command/" +
                encodeURIComponent(
                    HOST_ID
                ),
                {
                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    headers: {
                        "Content-Type":
                            "application/json"
                    }
                }
            );

        let data = {};

        try {

            data =
                await response.json();

        } catch {

            data = {};
        }

        if (!response.ok) {

            throw new Error(
                data.error ||
                data.detail ||
                `HTTP ${response.status}`
            );
        }

        commandRunning =
            false;

        addOutput(
            "✓ Stop command sent to host.",
            "output-system"
        );

        updateButtons();

    } catch (error) {

        console.error(
            "PowerShell stop command error:",
            error
        );

        addOutput(
            `✗ Stop error: ${error.message}`,
            "output-error"
        );
    }
}


// ============================================================
// STOP POWERSHELL COMPLETELY
// ============================================================

async function stopPowerShell() {

    if (!HOST_ID) {

        return;
    }

    addOutput(
        "■ Stopping PowerShell...",
        "output-system"
    );

    try {

        const response =
            await fetch(
                "/api/powershell/stop/" +
                encodeURIComponent(
                    HOST_ID
                ),
                {
                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    headers: {
                        "Content-Type":
                            "application/json"
                    }
                }
            );

        let data = {};

        try {

            data =
                await response.json();

        } catch {

            data = {};
        }

        console.log(
            "📥 PowerShell stop response:",
            data
        );

        if (!response.ok) {

            throw new Error(
                data.error ||
                data.detail ||
                `HTTP ${response.status}`
            );
        }

        commandRunning =
            false;

        addOutput(
            "✓ Stop command sent to host.",
            "output-system"
        );

        setStatus(
            true,
            "Stopping..."
        );

        updateButtons();

    } catch (error) {

        console.error(
            "PowerShell stop error:",
            error
        );

        addOutput(
            `✗ Stop error: ${error.message}`,
            "output-error"
        );
    }
}


// ============================================================
// CLEAR
// ============================================================

function clearTerminal() {

    if (!output) {

        return;
    }

    output.innerHTML = "";

    addOutput(
        "Terminal cleared.",
        "output-system"
    );

    if (commandInput) {

        commandInput.focus();
    }
}


// ============================================================
// BUTTONS
// ============================================================

if (sendButton) {

    sendButton.addEventListener(
        "click",
        executeCommand
    );
}


if (startButton) {

    startButton.addEventListener(
        "click",
        startPowerShell
    );
}


if (stopButton) {

    stopButton.addEventListener(
        "click",
        stopPowerShell
    );
}


if (executeButton) {

    executeButton.addEventListener(
        "click",
        executeCommand
    );
}


if (clearButton) {

    clearButton.addEventListener(
        "click",
        clearTerminal
    );
}


// ============================================================
// ENTER
// ============================================================

if (commandInput) {

    commandInput.addEventListener(
        "keydown",
        function(event) {

            if (
                event.key === "Enter" &&
                !event.shiftKey
            ) {

                event.preventDefault();

                executeCommand();
            }
        }
    );
}


// ============================================================
// PAGE CLOSE
// ============================================================

window.addEventListener(
    "beforeunload",
    function() {

        manuallyClosed =
            true;

        if (reconnectTimer) {

            clearTimeout(
                reconnectTimer
            );

            reconnectTimer =
                null;
        }

        if (powershellSocket) {

            try {

                powershellSocket.close();

            } catch (error) {

                // ignore
            }
        }
    }
);


// ============================================================
// INITIALIZE
// ============================================================

function initialize() {

    console.log(
        "💻 PowerShell page initialized"
    );

    console.log(
        "🆔 Host ID:",
        HOST_ID
    );

    if (!HOST_ID) {

        if (hostIdElement) {

            hostIdElement.textContent =
                "HOST NOT SPECIFIED";
        }

        setStatus(
            false,
            "Host ID отсутствует"
        );

        if (sendButton) {

            sendButton.disabled =
                true;
        }

        if (startButton) {

            startButton.disabled =
                true;
        }

        if (executeButton) {

            executeButton.disabled =
                true;
        }

        if (stopButton) {

            stopButton.disabled =
                true;
        }

        addOutput(
            "ERROR: Host ID is missing.",
            "output-error"
        );

        return;
    }

    if (hostIdElement) {

        hostIdElement.textContent =
            HOST_ID;
    }

    addOutput(
        `PS ${HOST_ID}> Remote PowerShell`,
        "output-system"
    );

    addOutput(
        "Connecting to host...",
        "output-system"
    );

    setStatus(
        false,
        "Connecting..."
    );

    updateButtons();

    // --------------------------------------------------------
    // СНАЧАЛА WebSocket
    // --------------------------------------------------------

    connectPowerShellWebSocket();

    // --------------------------------------------------------
    // Затем запускаем PowerShell
    // --------------------------------------------------------

    startPowerShell();
}



function insertQuickCommand(cmd) {
    const input =
        document.getElementById("commandInput") ||
        commandInput;

    if (!input) {
        console.warn("commandInput not found");
        return;
    }

    input.value = String(cmd || "");
    input.focus();

    try {
        const q = String(cmd || "").indexOf('"000000"');
        if (q >= 0) {
            input.setSelectionRange(q + 1, q + 7);
        } else {
            const len = input.value.length;
            input.setSelectionRange(len, len);
        }
    } catch (e) {}
}

function bindQuickPanel() {
    const panel = document.getElementById("quickPanel");
    if (!panel) {
        console.warn("quickPanel not found");
        return;
    }

    // Event delegation — works even if buttons re-render
    panel.addEventListener("click", function (e) {
        const btn = e.target.closest("[data-cmd]");
        if (!btn || !panel.contains(btn)) {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        const cmd = btn.getAttribute("data-cmd") || "";
        if (cmd) {
            insertQuickCommand(cmd);
        }
    });

    console.log(
        "✓ Quick panel bound:",
        panel.querySelectorAll("[data-cmd]").length,
        "buttons"
    );
}


// ============================================================
// START
// ============================================================

bindQuickPanel();
initialize();

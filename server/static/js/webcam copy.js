/*
============================================================
REMOTE DESKTOP — WEBCAM
============================================================

URL:

    /webcam?host=HOST_ID

Пример:

    /webcam?host=MUKM0502

WebRTC:
    browser <-> signaling server <-> webcam.py

============================================================
*/

console.log(
    "📷 Remote Desktop webcam.js loaded"
);


/*
============================================================
STATE
============================================================
*/

let peerConnection = null;
let signalingSocket = null;
let hostId = null;

let connecting = false;
let viewerReadySent = false;

let connectionGeneration = 0;


/*
============================================================
DOM
============================================================
*/

const video =
    document.getElementById(
        "webcam-video"
    );


const placeholder =
    document.getElementById(
        "video-placeholder"
    );


const statusElement =
    document.getElementById(
        "camera-status"
    );


const hostNameElement =
    document.getElementById(
        "host-name"
    );


const hostUserElement =
    document.getElementById(
        "host-user"
    );


const muteButton =
    document.getElementById(
        "mute-button"
    );


const volumeSlider =
    document.getElementById(
        "volume-slider"
    );


const fullscreenButton =
    document.getElementById(
        "fullscreen-button"
    );


/*
============================================================
URL
============================================================
*/

function getHostId() {

    const params =
        new URLSearchParams(
            window.location.search
        );


    return params.get(
        "host"
    );

}


/*
============================================================
STATUS
============================================================
*/

function setStatus(
    type,
    text
) {

    if (!statusElement) {
        return;
    }


    statusElement.className =
        "camera-status";


    if (type) {

        statusElement.classList.add(
            type
        );

    }


    statusElement.innerHTML =
        `
        <span class="status-dot"></span>
        ${text}
        `;

}


/*
============================================================
HOST INFORMATION
============================================================
*/

async function loadHostInfo() {

    if (!hostId) {
        return;
    }


    try {

        const response =
            await fetch(
                "/api/host/info/"
                +
                encodeURIComponent(
                    hostId
                )
                +
                "?t="
                +
                Date.now(),
                {
                    cache:
                        "no-store",

                    credentials:
                        "same-origin"
                }
            );


        /*
        --------------------------------------------
        AUTH
        --------------------------------------------
        */

        if (
            response.status === 401
        ) {

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


        if (hostNameElement) {

            hostNameElement.textContent =
                data.computer_name
                ||
                hostId;

        }


        if (hostUserElement) {

            hostUserElement.textContent =
                "User: "
                +
                (
                    data.username
                    ||
                    "—"
                );

        }


    } catch (error) {

        console.error(
            "❌ Host info error:",
            error
        );

    }

}


/*
============================================================
START WEBCAM PROCESS
============================================================
*/

async function startWebcam() {

    if (!hostId) {

        setStatus(
            "error",
            "No computer selected"
        );

        return false;

    }


    console.log(
        "📷 Requesting webcam start:",
        hostId
    );


    try {

        const response =
            await fetch(
                "/api/webcam/start/"
                +
                encodeURIComponent(
                    hostId
                ),
                {
                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    cache:
                        "no-store"
                }
            );


        /*
        --------------------------------------------------------
        AUTH
        --------------------------------------------------------
        */

        if (
            response.status === 401
        ) {

            window.location.href =
                "/login";

            return false;

        }


        const data =
            await response.json();


        console.log(
            "📷 Webcam start response:",
            data
        );


        if (!response.ok) {

            setStatus(
                "error",
                data.detail
                ||
                "Cannot start webcam"
            );

            return false;

        }


        if (!data.success) {

            setStatus(
                "error",
                "Webcam could not be started"
            );

            return false;

        }


        console.log(
            "🟢 webcam.py started:",
            hostId
        );


        setStatus(
            "",
            "Starting camera..."
        );


        return true;


    } catch (error) {

        console.error(
            "❌ Webcam start error:",
            error
        );


        setStatus(
            "error",
            "Cannot start camera"
        );


        return false;

    }

}


/*
============================================================
START WEBCAM ON HOST
============================================================
*/

async function startHostWebcam() {

    if (!hostId) {

        return false;

    }


    console.log(
        "📷 Requesting webcam start:",
        hostId
    );


    try {

        const response =
            await fetch(

                "/api/webcam/start/"
                +
                encodeURIComponent(
                    hostId
                ),

                {

                    method:
                        "POST",

                    credentials:
                        "same-origin",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    cache:
                        "no-store"

                }

            );


        /*
        --------------------------------------------------------
        AUTH
        --------------------------------------------------------
        */

        if (
            response.status ===
            401
        ) {

            window.location.href =
                "/login";

            return false;

        }


        const data =
            await response.json();


        console.log(
            "📷 Webcam start response:",
            data
        );


        /*
        --------------------------------------------------------
        HTTP ERROR
        --------------------------------------------------------
        */

        if (
            !response.ok
        ) {

            throw new Error(

                data.detail
                ||
                `HTTP ${response.status}`

            );

        }


        /*
        --------------------------------------------------------
        SERVER ACCEPTED COMMAND
        --------------------------------------------------------
        */

        if (
            data.success === true
        ) {

            console.log(
                "🟢 webcam.py start command accepted"
            );


            setStatus(
                "",
                "Starting camera..."
            );


            return true;

        }


        /*
        --------------------------------------------------------
        FAILED
        --------------------------------------------------------
        */

        console.error(
            "❌ Webcam start rejected:",
            data
        );


        return false;


    } catch (error) {

        console.error(
            "❌ Webcam start error:",
            error
        );


        setStatus(
            "error",
            "Cannot start webcam"
        );


        return false;

    }

}


/*
============================================================
CLOSE WEBRTC
============================================================
*/

function closeWebRTC() {

    console.log(
        "⏹ Closing WebRTC connection..."
    );


    if (peerConnection) {

        try {

            peerConnection.ontrack = null;

            peerConnection.onconnectionstatechange =
                null;

            peerConnection.oniceconnectionstatechange =
                null;

            peerConnection.onicegatheringstatechange =
                null;

            peerConnection.onicecandidate =
                null;

            peerConnection.close();

        } catch (error) {

            console.warn(
                "⚠️ PeerConnection close error:",
                error
            );

        }

    }


    peerConnection =
        null;

}


/*
============================================================
CLOSE SIGNALING
============================================================
*/

function closeSignaling() {

    if (!signalingSocket) {
        return;
    }


    console.log(
        "🔴 Closing signaling socket..."
    );


    try {

        signalingSocket.onopen = null;
        signalingSocket.onmessage = null;
        signalingSocket.onerror = null;
        signalingSocket.onclose = null;

        signalingSocket.close();

    } catch (error) {

        console.warn(
            "⚠️ Signaling close error:",
            error
        );

    }


    signalingSocket =
        null;

}


/*
============================================================
CONNECT WEBRTC
============================================================
*/

async function connectWebRTC() {

    if (!hostId) {

        setStatus(
            "error",
            "No computer selected"
        );

        return;

    }


    /*
    ============================================================
    PREVENT DOUBLE CONNECT
    ============================================================
    */

    if (connecting) {

        console.warn(
            "⚠️ WebRTC connection already in progress"
        );

        return;

    }


    connecting =
        true;


    viewerReadySent =
        false;


    connectionGeneration++;


    const currentGeneration =
        connectionGeneration;


    console.log(
        "================================================"
    );

    console.log(
        "🔗 Starting WebRTC connection"
    );

    console.log(
        "🆔 Generation:",
        currentGeneration
    );

    console.log(
        "💻 Host:",
        hostId
    );

    console.log(
        "================================================"
    );


    /*
    ============================================================
    CLOSE OLD CONNECTIONS
    ============================================================
    */

    closeSignaling();

    closeWebRTC();


    /*
    ============================================================
    CREATE PEER CONNECTION
    ============================================================
    */

    try {

        /*
        --------------------------------------------------------
        IMPORTANT:
        STUN is required for phones / NAT / external networks.
        --------------------------------------------------------
        */

        peerConnection =
            new RTCPeerConnection({

                iceServers: [

                    {
                        urls:
                            "stun:stun.l.google.com:19302"
                    },

                    {
                        urls:
                            "stun:stun1.l.google.com:19302"
                    }

                ],

                iceCandidatePoolSize:
                    10

            });


    } catch (error) {

        console.error(
            "❌ Cannot create RTCPeerConnection:",
            error
        );


        connecting =
            false;


        setStatus(
            "error",
            "WebRTC initialization failed"
        );


        return;

    }


    const pc =
        peerConnection;


    console.log(
        "🟢 New RTCPeerConnection created"
    );


    /*
    ============================================================
    VIDEO SETTINGS
    ============================================================
    */

    if (video) {

        video.autoplay =
            true;

        video.playsInline =
            true;

        video.muted =
            true;

    }


    /*
    ============================================================
    REMOTE VIDEO TRACK
    ============================================================
    */

    pc.ontrack =
        function(event) {

            /*
            ----------------------------------------------------
            Ignore old PeerConnection events.
            ----------------------------------------------------
            */

            if (
                peerConnection !== pc
            ) {

                console.warn(
                    "⚠️ Ignoring track from old PeerConnection"
                );

                return;

            }


            console.log(
                "🎥 Remote track:",
                event.track.kind
            );


            /*
            ----------------------------------------------------
            CREATE / GET MEDIA STREAM
            ----------------------------------------------------
            */

            let stream = null;


            if (
                event.streams &&
                event.streams.length > 0
            ) {

                stream =
                    event.streams[0];

            }

            else {

                if (
                    !video.srcObject
                ) {

                    video.srcObject =
                        new MediaStream();

                }


                stream =
                    video.srcObject;


                stream.addTrack(
                    event.track
                );

            }


            /*
            ----------------------------------------------------
            SET VIDEO SOURCE
            ----------------------------------------------------
            */

            video.srcObject =
                stream;


            video.autoplay =
                true;

            video.playsInline =
                true;

            video.muted =
                true;


            console.log(
                "🎬 Video source assigned"
            );


            /*
            ----------------------------------------------------
            VIDEO METADATA
            ----------------------------------------------------
            */

            video.onloadedmetadata =
                function() {

                    console.log(
                        "🎬 Video metadata:",
                        video.videoWidth,
                        "x",
                        video.videoHeight
                    );


                    video.play()
                        .then(
                            function() {

                                console.log(
                                    "▶️ Video playback started"
                                );

                            }
                        )
                        .catch(
                            function(error) {

                                console.warn(
                                    "⚠️ Autoplay blocked. "
                                    +
                                    "Waiting for user interaction.",
                                    error
                                );

                            }
                        );

                };


            /*
            ----------------------------------------------------
            TRACK UNMUTE
            ----------------------------------------------------
            */

            event.track.onunmute =
                function() {

                    console.log(
                        "🟢 Remote video track active"
                    );


                    video.play()
                        .then(
                            function() {

                                console.log(
                                    "▶️ Video playing"
                                );

                            }
                        )
                        .catch(
                            function() {

                                console.log(
                                    "👆 Waiting for user interaction"
                                );

                            }
                        );

                };


            /*
            ----------------------------------------------------
            TRACK MUTE
            ----------------------------------------------------
            */

            event.track.onmute =
                function() {

                    console.log(
                        "🔇 Remote video track muted"
                    );

                };


            /*
            ----------------------------------------------------
            TRACK ENDED
            ----------------------------------------------------
            */

            event.track.onended =
                function() {

                    console.log(
                        "🔴 Remote video track ended"
                    );

                };


            /*
            ----------------------------------------------------
            HIDE PLACEHOLDER
            ----------------------------------------------------
            */

            if (placeholder) {

                placeholder.style.display =
                    "none";

            }


            /*
            ----------------------------------------------------
            STATUS
            ----------------------------------------------------
            */

            setStatus(
                "online",
                "Live"
            );


            console.log(
                "📺 Remote video ready"
            );

        };


    /*
    ============================================================
    CONNECTION STATE
    ============================================================
    */

    pc.onconnectionstatechange =
        function() {

            if (
                peerConnection !== pc
            ) {

                return;

            }


            const state =
                pc.connectionState;


            console.log(
                "🌐 WebRTC connection state:",
                state
            );


            switch (state) {

                case "new":

                    setStatus(
                        "",
                        "Preparing connection..."
                    );

                    break;


                case "connecting":

                    setStatus(
                        "",
                        "Connecting..."
                    );

                    break;


                case "connected":

                    console.log(
                        "🟢 WEBRTC CONNECTED"
                    );


                    connecting =
                        false;


                    setStatus(
                        "online",
                        "Live"
                    );

                    break;


                case "disconnected":

                    console.warn(
                        "🟠 WEBRTC DISCONNECTED"
                    );


                    setStatus(
                        "",
                        "Connection interrupted..."
                    );

                    break;


                case "failed":

                    console.error(
                        "🔴 WEBRTC FAILED"
                    );


                    connecting =
                        false;


                    setStatus(
                        "error",
                        "Connection failed"
                    );

                    break;


                case "closed":

                    console.log(
                        "🔴 WEBRTC CLOSED"
                    );


                    connecting =
                        false;


                    setStatus(
                        "",
                        "Disconnected"
                    );

                    break;

            }

        };


    /*
    ============================================================
    ICE CONNECTION STATE
    ============================================================
    */

    pc.oniceconnectionstatechange =
        function() {

            if (
                peerConnection !== pc
            ) {

                return;

            }


            const state =
                pc.iceConnectionState;


            console.log(
                "🧊 ICE state:",
                state
            );


            if (
                state ===
                "checking"
            ) {

                console.log(
                    "🧊 ICE is checking available network paths..."
                );

            }


            if (
                state ===
                "connected"
            ) {

                console.log(
                    "🟢 ICE CONNECTED"
                );

            }


            if (
                state ===
                "completed"
            ) {

                console.log(
                    "🟢 ICE COMPLETED"
                );

            }


            if (
                state ===
                "disconnected"
            ) {

                console.warn(
                    "🟠 ICE DISCONNECTED"
                );

            }


            if (
                state ===
                "failed"
            ) {

                console.error(
                    "🔴 ICE FAILED"
                );


                console.error(
                    "❗ Browser could not establish "
                    +
                    "a WebRTC network connection."
                );


                setStatus(
                    "error",
                    "Connection failed"
                );

            }


            if (
                state ===
                "closed"
            ) {

                console.log(
                    "🔴 ICE CLOSED"
                );

            }

        };


    /*
    ============================================================
    ICE GATHERING STATE
    ============================================================
    */

    pc.onicegatheringstatechange =
        function() {

            if (
                peerConnection !== pc
            ) {

                return;

            }


            console.log(
                "🧊 ICE gathering state:",
                pc.iceGatheringState
            );

        };


    /*
    ============================================================
    LOCAL ICE CANDIDATE
    ============================================================
    */

    pc.onicecandidate =
        function(event) {

            if (
                peerConnection !== pc
            ) {

                return;

            }


            if (
                event.candidate
            ) {

                console.log(
                    "🧊 Local ICE candidate generated"
                );

            }

            else {

                console.log(
                    "🧊 ICE candidate gathering complete"
                );

            }

        };


    /*
    ============================================================
    SIGNALING URL
    ============================================================
    */

    const protocol =
        location.protocol === "https:"
            ? "wss:"
            : "ws:";


    const signalingUrl =
        protocol
        +
        "//"
        +
        location.host
        +
        "/ws/webcam/browser/"
        +
        encodeURIComponent(
            hostId
        );


    console.log(
        "🔌 Signaling:",
        signalingUrl
    );


    /*
    ============================================================
    CREATE SIGNALING SOCKET
    ============================================================
    */

    let socket;


    try {

        socket =
            new WebSocket(
                signalingUrl
            );

    } catch (error) {

        console.error(
            "❌ Cannot create WebSocket:",
            error
        );


        connecting =
            false;


        setStatus(
            "error",
            "Signaling connection failed"
        );


        return;

    }


    signalingSocket =
        socket;


    /*
    ============================================================
    SOCKET OPEN
    ============================================================
    */

    socket.onopen =
        function() {

            /*
            ----------------------------------------------------
            Ignore old socket.
            ----------------------------------------------------
            */

            if (
                signalingSocket !== socket
                ||
                connectionGeneration !==
                    currentGeneration
            ) {

                console.warn(
                    "⚠️ Old signaling socket opened"
                );


                try {

                    socket.close();

                } catch (error) {

                }


                return;

            }


            console.log(
                "🟢 Signaling connected"
            );


            setStatus(
                "",
                "Connecting..."
            );


            /*
            ----------------------------------------------------
            IMPORTANT:
            Send viewer_ready ONLY ONCE.
            ----------------------------------------------------
            */

            if (
                viewerReadySent
            ) {

                console.warn(
                    "⚠️ viewer_ready already sent"
                );

                return;

            }


            viewerReadySent =
                true;


            console.log(
                "📤 Sending viewer_ready"
            );


            socket.send(

                JSON.stringify({

                    type:
                        "viewer_ready",

                    host_id:
                        hostId

                })

            );


            console.log(
                "🟢 viewer_ready sent"
            );

        };


    /*
    ============================================================
    SOCKET MESSAGE
    ============================================================
    */

    socket.onmessage =
        async function(event) {

            /*
            ----------------------------------------------------
            Ignore old socket.
            ----------------------------------------------------
            */

            if (
                signalingSocket !== socket
                ||
                connectionGeneration !==
                    currentGeneration
            ) {

                console.warn(
                    "⚠️ Ignoring message from old signaling socket"
                );

                return;

            }


            try {

                const message =
                    JSON.parse(
                        event.data
                    );


                console.log(
                    "📩 Signaling:",
                    message.type
                );


                /*
                ==================================================
                OFFER
                ==================================================
                */

                if (
                    message.type ===
                    "offer"
                ) {

                    console.log(
                        "📥 WebRTC offer received"
                    );


                    /*
                    ------------------------------------------------
                    Make absolutely sure this is the current PC.
                    ------------------------------------------------
                    */

                    if (
                        signalingSocket !== socket
                        ||
                        peerConnection !== pc
                    ) {

                        console.warn(
                            "⚠️ Ignoring offer for old connection"
                        );

                        return;

                    }


                    /*
                    ------------------------------------------------
                    Do not process another offer if one is already
                    being negotiated.
                    ------------------------------------------------
                    */

                    if (
                        pc.signalingState !==
                        "stable"
                    ) {

                        console.warn(
                            "⚠️ Ignoring duplicate/late offer"
                        );


                        console.warn(
                            "Current signaling state:",
                            pc.signalingState
                        );


                        return;

                    }


                    /*
                    ------------------------------------------------
                    SET REMOTE OFFER
                    ------------------------------------------------
                    */

                    await pc.setRemoteDescription({

                        type:
                            "offer",

                        sdp:
                            message.sdp

                    });


                    console.log(
                        "🟢 Remote offer set"
                    );


                    /*
                    ------------------------------------------------
                    CREATE ANSWER
                    ------------------------------------------------
                    */

                    const answer =
                        await pc.createAnswer();


                    await pc.setLocalDescription(
                        answer
                    );


                    console.log(
                        "📤 Sending answer"
                    );


                    /*
                    ------------------------------------------------
                    Make sure socket/PC is still current.
                    ------------------------------------------------
                    */

                    if (
                        signalingSocket !== socket
                        ||
                        peerConnection !== pc
                    ) {

                        console.warn(
                            "⚠️ Connection changed while creating answer"
                        );

                        return;

                    }


                    socket.send(

                        JSON.stringify({

                            type:
                                "answer",

                            host_id:
                                hostId,

                            sdp:
                                pc.localDescription
                                    .sdp

                        })

                    );


                    console.log(
                        "🟢 WebRTC answer sent"
                    );

                }


                /*
                ==================================================
                ICE CANDIDATE
                ==================================================
                */

                else if (
                    message.type ===
                    "candidate"
                ) {

                    if (
                        signalingSocket !== socket
                        ||
                        peerConnection !== pc
                    ) {

                        console.warn(
                            "⚠️ Ignoring ICE candidate from old connection"
                        );

                        return;

                    }


                    if (
                        !message.candidate
                    ) {

                        console.log(
                            "🧊 Empty ICE candidate received"
                        );

                        return;

                    }


                    try {

                        await pc.addIceCandidate(
                            message.candidate
                        );


                        console.log(
                            "🧊 ICE candidate added"
                        );

                    } catch (error) {

                        console.warn(
                            "⚠️ ICE candidate error:",
                            error
                        );

                    }

                }


                /*
                ==================================================
                ERROR
                ==================================================
                */

                else if (
                    message.type ===
                    "error"
                ) {

                    console.error(
                        "❌ Webcam signaling error:",
                        message.message
                    );


                    connecting =
                        false;


                    setStatus(
                        "error",
                        message.message
                        ||
                        "Camera error"
                    );

                }


                /*
                ==================================================
                OTHER
                ==================================================
                */

                else {

                    console.log(
                        "ℹ️ Unknown signaling message:",
                        message
                    );

                }


            } catch (error) {

                console.error(
                    "❌ Signaling message error:",
                    error
                );

            }

        };


    /*
    ============================================================
    SOCKET ERROR
    ============================================================
    */

    socket.onerror =
        function(error) {

            console.error(
                "❌ Signaling error:",
                error
            );


            if (
                signalingSocket === socket
            ) {

                setStatus(
                    "error",
                    "Signaling error"
                );

            }

        };


    /*
    ============================================================
    SOCKET CLOSED
    ============================================================
    */

    socket.onclose =
        function(event) {

            console.log(
                "🔴 Signaling closed"
            );


            console.log(
                "   Code:",
                event.code
            );


            console.log(
                "   Reason:",
                event.reason
                ||
                "none"
            );


            if (
                signalingSocket === socket
            ) {

                signalingSocket =
                    null;

            }

        };


    /*
    ============================================================
    CONNECTION TIMEOUT DIAGNOSTICS
    ============================================================
    */

    setTimeout(
        function() {

            if (
                signalingSocket !== socket
                ||
                peerConnection !== pc
            ) {

                return;

            }


            const iceState =
                pc.iceConnectionState;


            const connectionState =
                pc.connectionState;


            console.log(
                "================================================"
            );

            console.log(
                "⏱ WebRTC diagnostic after 10 seconds"
            );

            console.log(
                "🧊 ICE:",
                iceState
            );

            console.log(
                "🌐 Connection:",
                connectionState
            );

            console.log(
                "📡 Signaling:",
                socket.readyState
            );

            console.log(
                "================================================"
            );


            if (
                iceState ===
                    "checking"
                ||
                connectionState ===
                    "connecting"
            ) {

                console.warn(
                    "⚠️ WebRTC is still connecting after 10 seconds"
                );

                console.warn(
                    "⚠️ This usually indicates an ICE/NAT/TURN problem."
                );

            }

        },
        10000
    );


    /*
    ============================================================
    LONG TIMEOUT
    ============================================================
    */

    setTimeout(
        function() {

            if (
                signalingSocket !== socket
                ||
                peerConnection !== pc
            ) {

                return;

            }


            const iceState =
                pc.iceConnectionState;


            const connectionState =
                pc.connectionState;


            console.log(
                "================================================"
            );

            console.log(
                "⏱ WebRTC diagnostic after 20 seconds"
            );

            console.log(
                "🧊 ICE:",
                iceState
            );

            console.log(
                "🌐 Connection:",
                connectionState
            );

            console.log(
                "================================================"
            );


            if (
                iceState ===
                "checking"
            ) {

                console.error(
                    "🔴 ICE is still CHECKING after 20 seconds"
                );

                console.error(
                    "🔴 STUN/TURN or NAT connectivity should be investigated."
                );

            }

        },
        20000
    );

}


/*
============================================================
ENABLE VIDEO AFTER USER INTERACTION
============================================================
*/

async function startVideoPlayback() {

    if (!video) {

        return;

    }


    if (!video.srcObject) {

        console.log(
            "⚠️ No video stream yet"
        );

        return;

    }


    try {

        video.muted =
            true;


        await video.play();


        console.log(
            "▶️ Video playback started by user"
        );


    } catch (error) {

        console.error(
            "❌ Video playback error:",
            error
        );

    }

}


/*
============================================================
USER INTERACTION
============================================================
*/

document.addEventListener(
    "click",
    startVideoPlayback,
    {
        once: true
    }
);


document.addEventListener(
    "keydown",
    startVideoPlayback,
    {
        once: true
    }
);


/*
============================================================
VOLUME
============================================================
*/

if (volumeSlider) {

    volumeSlider.addEventListener(
        "input",
        function() {

            const value =
                Number(
                    volumeSlider.value
                )
                / 100;


            if (video) {

                video.volume =
                    value;


                video.muted =
                    value === 0;

            }


            if (muteButton) {

                muteButton.textContent =
                    value === 0
                        ? "🔇"
                        : "🔊";

            }

        }
    );

}


/*
============================================================
MUTE
============================================================
*/

if (muteButton) {

    muteButton.addEventListener(
        "click",
        function() {

            if (!video) {

                return;

            }


            video.muted =
                !video.muted;


            muteButton.textContent =
                video.muted
                    ? "🔇"
                    : "🔊";


            if (!video.muted) {

                video.play().catch(
                    function(error) {

                        console.warn(
                            "Playback blocked:",
                            error
                        );

                    }
                );

            }

        }
    );

}


/*
============================================================
FULLSCREEN
============================================================
*/

if (fullscreenButton) {

    fullscreenButton.addEventListener(
        "click",
        async function() {

            if (!video) {

                return;

            }


            try {

                if (
                    document.fullscreenElement
                ) {

                    await document.exitFullscreen();

                }

                else {

                    await video.requestFullscreen();

                }

            } catch (error) {

                console.error(
                    "Fullscreen error:",
                    error
                );

            }

        }
    );

}


/*
============================================================
CLEANUP
============================================================
*/

window.addEventListener(
    "beforeunload",
    function() {

        console.log(
            "🔴 Closing webcam..."
        );


        connectionGeneration++;


        viewerReadySent =
            false;


        connecting =
            false;


        /*
        --------------------------------------------------------
        SIGNALING
        --------------------------------------------------------
        */

        if (signalingSocket) {

            try {

                signalingSocket.onopen =
                    null;

                signalingSocket.onmessage =
                    null;

                signalingSocket.onerror =
                    null;

                signalingSocket.onclose =
                    null;

                signalingSocket.close();

            } catch (error) {

                console.warn(
                    "⚠️ Signaling cleanup error:",
                    error
                );

            }


            signalingSocket =
                null;

        }


        /*
        --------------------------------------------------------
        WEBRTC
        --------------------------------------------------------
        */

        if (peerConnection) {

            try {

                peerConnection.ontrack =
                    null;

                peerConnection.onconnectionstatechange =
                    null;

                peerConnection.oniceconnectionstatechange =
                    null;

                peerConnection.onicegatheringstatechange =
                    null;

                peerConnection.onicecandidate =
                    null;

                peerConnection.close();

            } catch (error) {

                console.warn(
                    "⚠️ WebRTC cleanup error:",
                    error
                );

            }


            peerConnection =
                null;

        }


        /*
        --------------------------------------------------------
        VIDEO
        --------------------------------------------------------
        */

        if (video) {

            try {

                video.pause();

                video.srcObject =
                    null;

            } catch (error) {

                console.warn(
                    "⚠️ Video cleanup error:",
                    error
                );

            }

        }

    }
);


/*
============================================================
INITIALIZATION
============================================================
*/

document.addEventListener(
    "DOMContentLoaded",
    async function() {

        hostId =
            getHostId();


        console.log(
            "📷 Selected host:",
            hostId
        );


        if (!hostId) {

            setStatus(
                "error",
                "No computer selected"
            );

            return;

        }


        /*
        --------------------------------------------------------
        HOST INFORMATION
        --------------------------------------------------------
        */

        await loadHostInfo();


        /*
        --------------------------------------------------------
        START webcam.py ON WINDOWS HOST
        --------------------------------------------------------
        */

        const started =
            await startHostWebcam();


        if (!started) {

            setStatus(
                "error",
                "Cannot start webcam"
            );

            return;

        }


        /*
        --------------------------------------------------------
        GIVE webcam.py A MOMENT TO CONNECT
        --------------------------------------------------------
        */

        console.log(
            "⏳ Waiting for webcam.py..."
        );


        await new Promise(
            resolve =>
                setTimeout(
                    resolve,
                    1000
                )
        );


        /*
        --------------------------------------------------------
        CONNECT BROWSER TO WEBRTC
        --------------------------------------------------------
        */

        await connectWebRTC();

    }
);
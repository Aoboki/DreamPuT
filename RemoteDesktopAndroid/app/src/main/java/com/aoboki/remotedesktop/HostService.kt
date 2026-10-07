package com.aoboki.remotedesktop

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.Log
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class HostService : Service() {

    companion object {
        private const val TAG = "HostService"
        private const val CHANNEL_ID = "host_connection"
        private const val NOTIF_ID = 1001
        private const val HEARTBEAT_MS = 10_000L
        private const val HOST_INFO_MS = 25_000L
        private const val RECONNECT_MS = 3_000L

        const val ACTION_STATUS = "com.aoboki.remotedesktop.HOST_STATUS"
        const val EXTRA_STATUS = "status"
        const val EXTRA_DETAIL = "detail"

        @Volatile
        var isRunning: Boolean = false
            private set

        @Volatile
        var lastStatus: String = "offline"
            private set

        @Volatile
        var instance: HostService? = null
            private set

        fun start(ctx: Context) {
            val i = Intent(ctx, HostService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                ctx.startForegroundService(i)
            } else {
                ctx.startService(i)
            }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, HostService::class.java))
        }
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private var webSocket: SimpleWebSocket? = null
    private val connecting = AtomicBoolean(false)
    private val gen = AtomicInteger(0)
    private var hostId: String = ""
    private var serverBase: String = HostPrefs.DEFAULT_SERVER
    private var currentGen = 0

    private val heartbeatRunnable = object : Runnable {
        override fun run() {
            if (!isRunning) return
            sendText(DeviceInfo.buildHeartbeat(hostId).toString())
            mainHandler.postDelayed(this, HEARTBEAT_MS)
        }
    }

    private val hostInfoRunnable = object : Runnable {
        override fun run() {
            if (!isRunning) return
            sendText(DeviceInfo.buildHostInfo(this@HostService, hostId).toString())
            mainHandler.postDelayed(this, HOST_INFO_MS)
        }
    }

    private val reconnectRunnable = Runnable {
        if (isRunning) connect()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "host_connection", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        isRunning = true
        hostId = HostPrefs.getHostId(this)
        serverBase = HostPrefs.getServer(this).trimEnd('/')
        startForeground(NOTIF_ID, buildNotification("Connecting…"))
        publishStatus("connecting", "Connecting to $serverBase …")
        connect()
        return START_STICKY
    }

    override fun onDestroy() {
        isRunning = false
        instance = null
        mainHandler.removeCallbacksAndMessages(null)
        gen.incrementAndGet()
        try {
            webSocket?.close()
        } catch (e: Exception) {
            Log.w(TAG, "close: ${e.message}")
        }
        webSocket = null
        lastStatus = "offline"
        publishStatus("offline", "Stopped")
        super.onDestroy()
    }

    private fun wsUrl(): String {
        val base = serverBase
            .replace("https://", "wss://")
            .replace("http://", "ws://")
            .trimEnd('/')
        return "$base/ws/host/$hostId"
    }

    private fun connect() {
        if (!isRunning) return
        if (!connecting.compareAndSet(false, true)) return

        currentGen = gen.incrementAndGet()
        val myGen = currentGen

        try {
            webSocket?.close()
        } catch (_: Exception) {
        }
        webSocket = null

        val url = wsUrl()
        Log.i(TAG, "Connecting gen=$myGen $url")
        publishStatus("connecting", url)

        val ws = SimpleWebSocket(url, object : SimpleWebSocket.Listener {
            override fun onOpen() {
                if (myGen != gen.get()) return
                connecting.set(false)
                Log.i(TAG, "WebSocket open gen=$myGen")
                lastStatus = "online"
                mainHandler.post {
                    publishStatus("online", "Connected as $hostId")
                    updateNotification("Online · $hostId")
                }
                mainHandler.removeCallbacks(heartbeatRunnable)
                mainHandler.removeCallbacks(hostInfoRunnable)
                mainHandler.removeCallbacks(reconnectRunnable)
                sendText(DeviceInfo.buildHostInfo(this@HostService, hostId).toString())
                sendText(DeviceInfo.buildHeartbeat(hostId).toString())
                mainHandler.postDelayed(heartbeatRunnable, HEARTBEAT_MS)
                mainHandler.postDelayed(hostInfoRunnable, HOST_INFO_MS)
            }

            override fun onMessage(text: String) {
                if (myGen != gen.get()) return
                handleServerMessage(text)
            }

            override fun onClosing(code: Int, reason: String) {
                if (myGen != gen.get()) return
                connecting.set(false)
                mainHandler.post { onDisconnected("Closed ($code) $reason") }
            }

            override fun onFailure(t: Throwable) {
                if (myGen != gen.get()) return
                connecting.set(false)
                Log.e(TAG, "Failure: ${t.message}", t)
                mainHandler.post { onDisconnected(t.message ?: "Connection failed") }
            }
        })
        webSocket = ws
        ws.connect()
    }

    private fun onDisconnected(reason: String) {
        mainHandler.removeCallbacks(heartbeatRunnable)
        mainHandler.removeCallbacks(hostInfoRunnable)
        lastStatus = "offline"
        publishStatus("offline", reason)
        updateNotification("Reconnecting…")
        if (isRunning) {
            mainHandler.removeCallbacks(reconnectRunnable)
            mainHandler.postDelayed(reconnectRunnable, RECONNECT_MS)
        }
    }

    private fun handleServerMessage(text: String) {
        try {
            val data = JSONObject(text)
            // Server sends: {"command":"monitor_start"} or files_* with extra fields
            val command = data.optString("command", "")
            if (command.isEmpty()) {
                Log.d(TAG, "← (no command) $text")
                return
            }
            Log.i(TAG, "← command=$command")
            when {
                command.startsWith("files_") -> {
                    val result = FilesHandler.handle(command, data)
                    sendText(result.toString())
                }
                command == "monitor_start" -> {
                    MonitorController.start(this, hostId, serverBase)
                    sendStatus("monitor_status", true)
                }
                command == "monitor_stop" -> {
                    MonitorController.stop(this)
                    sendStatus("monitor_status", false)
                }
                command == "webcam_start" -> {
                    WebcamController.start(this, hostId, serverBase)
                    sendStatus("webcam_status", true)
                }
                command == "webcam_stop" -> {
                    WebcamController.stop(this)
                    sendStatus("webcam_status", false)
                }
                command == "control_start" || command == "control" -> {
                    // Control needs WebRTC — start monitor-like stream for now
                    MonitorController.start(this, hostId, serverBase)
                    sendText(
                        JSONObject()
                            .put("type", "command_status")
                            .put("command", command)
                            .put("status", "android_monitor_fallback")
                            .put("host_id", hostId)
                            .toString()
                    )
                }
                command == "control_stop" -> {
                    MonitorController.stop(this)
                }
                command == "host_info" -> {
                    sendText(DeviceInfo.buildHostInfo(this, hostId).toString())
                }
                else -> {
                    sendText(
                        JSONObject()
                            .put("type", "command_status")
                            .put("command", command)
                            .put("status", "not_implemented_android")
                            .put("host_id", hostId)
                            .toString()
                    )
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "handle message: ${e.message}", e)
        }
    }

    private fun sendStatus(type: String, running: Boolean) {
        sendText(
            JSONObject()
                .put("type", type)
                .put("host_id", hostId)
                .put("running", running)
                .put("status", if (running) "running" else "stopped")
                .put("timestamp", System.currentTimeMillis() / 1000.0)
                .toString()
        )
    }

    fun sendText(text: String) {
        try {
            val ws = webSocket
            if (ws != null && ws.isOpen) {
                ws.send(text)
            } else {
                Log.w(TAG, "send skipped (not open)")
            }
        } catch (e: Exception) {
            Log.e(TAG, "send error", e)
        }
    }

    private fun publishStatus(status: String, detail: String) {
        lastStatus = status
        val i = Intent(ACTION_STATUS).apply {
            setPackage(packageName)
            putExtra(EXTRA_STATUS, status)
            putExtra(EXTRA_DETAIL, detail)
        }
        sendBroadcast(i)
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Connected to Remote Desktop")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_info_details)
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIF_ID, buildNotification(text))
    }
}

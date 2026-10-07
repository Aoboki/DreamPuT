package com.aoboki.remotedesktop

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import org.json.JSONObject
import java.io.ByteArrayOutputStream

/**
 * Screen monitor → /ws/monitor-host/{hostId} as screen_frame JSON (base64 JPEG).
 * Requires MediaProjection permission granted via MainActivity.
 */
object MonitorController {
    private const val TAG = "MonitorCtrl"

    @Volatile
    private var projection: MediaProjection? = null

    @Volatile
    private var virtualDisplay: VirtualDisplay? = null

    @Volatile
    private var imageReader: ImageReader? = null

    @Volatile
    private var monitorWs: SimpleWebSocket? = null

    @Volatile
    private var running = false

    private var handlerThread: HandlerThread? = null
    private var handler: Handler? = null
    private var width = 720
    private var height = 1280
    private var density = 320

    fun hasPermission(): Boolean = projection != null || pendingResultCode != 0

    @Volatile
    private var pendingResultCode: Int = 0

    @Volatile
    private var pendingData: Intent? = null

    fun onPermissionResult(resultCode: Int, data: Intent?) {
        if (resultCode == Activity.RESULT_OK && data != null) {
            pendingResultCode = resultCode
            pendingData = data
            Log.i(TAG, "MediaProjection permission OK")
        } else {
            pendingResultCode = 0
            pendingData = null
            Log.w(TAG, "MediaProjection permission denied")
        }
    }

    fun start(ctx: Context, hostId: String, serverBase: String) {
        if (running) {
            Log.i(TAG, "already running")
            return
        }
        val app = ctx.applicationContext
        val metrics = DisplayMetrics()
        val wm = app.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealMetrics(metrics)
        density = metrics.densityDpi
        // scale down for bandwidth
        val maxW = 720
        if (metrics.widthPixels > maxW) {
            val scale = maxW.toFloat() / metrics.widthPixels
            width = maxW
            height = (metrics.heightPixels * scale).toInt()
        } else {
            width = metrics.widthPixels
            height = metrics.heightPixels
        }

        val data = pendingData
        val code = pendingResultCode
        if (data == null || code == 0) {
            Log.w(TAG, "No MediaProjection — ask user in app (button Grant screen)")
            // Still connect and send a placeholder notice frame text as tiny jpeg? skip
            HostService.instance?.sendText(
                JSONObject()
                    .put("type", "monitor_status")
                    .put("host_id", hostId)
                    .put("running", false)
                    .put("status", "need_screen_permission")
                    .toString()
            )
            return
        }

        val mpm = app.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        try {
            projection = mpm.getMediaProjection(code, data)
        } catch (e: Exception) {
            Log.e(TAG, "getMediaProjection failed", e)
            return
        }

        handlerThread = HandlerThread("monitor-capture").also { it.start() }
        handler = Handler(handlerThread!!.looper)

        imageReader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
        virtualDisplay = projection?.createVirtualDisplay(
            "DreamPUTMonitor",
            width,
            height,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader!!.surface,
            null,
            handler
        )

        val base = serverBase.replace("https://", "wss://").replace("http://", "ws://").trimEnd('/')
        val url = "$base/ws/monitor-host/$hostId"
        Log.i(TAG, "monitor WS $url ${width}x$height")

        running = true
        monitorWs = SimpleWebSocket(url, object : SimpleWebSocket.Listener {
            override fun onOpen() {
                Log.i(TAG, "monitor WS open")
                scheduleFrame()
            }

            override fun onMessage(text: String) {}
            override fun onClosing(code: Int, reason: String) {
                Log.w(TAG, "monitor WS closing $code")
            }

            override fun onFailure(t: Throwable) {
                Log.e(TAG, "monitor WS fail ${t.message}")
            }
        })
        monitorWs?.connect()
    }

    private fun scheduleFrame() {
        if (!running) return
        handler?.postDelayed({
            captureAndSend()
            scheduleFrame()
        }, 400)
    }

    private fun captureAndSend() {
        if (!running) return
        val reader = imageReader ?: return
        val image = try {
            reader.acquireLatestImage()
        } catch (e: Exception) {
            return
        } ?: return
        try {
            val plane = image.planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * width
            val bmp = Bitmap.createBitmap(
                width + rowPadding / pixelStride,
                height,
                Bitmap.Config.ARGB_8888
            )
            bmp.copyPixelsFromBuffer(buffer)
            val cropped = Bitmap.createBitmap(bmp, 0, 0, width, height)
            bmp.recycle()
            val baos = ByteArrayOutputStream()
            cropped.compress(Bitmap.CompressFormat.JPEG, 55, baos)
            cropped.recycle()
            val b64 = Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
            val msg = JSONObject()
                .put("type", "screen_frame")
                .put("image", b64)
                .put("width", width)
                .put("height", height)
                .toString()
            monitorWs?.send(msg)
        } catch (e: Exception) {
            Log.e(TAG, "frame: ${e.message}")
        } finally {
            image.close()
        }
    }

    fun stop(ctx: Context) {
        running = false
        try {
            monitorWs?.close()
        } catch (_: Exception) {
        }
        monitorWs = null
        try {
            virtualDisplay?.release()
        } catch (_: Exception) {
        }
        virtualDisplay = null
        try {
            imageReader?.close()
        } catch (_: Exception) {
        }
        imageReader = null
        try {
            projection?.stop()
        } catch (_: Exception) {
        }
        // keep pendingData so user doesn't re-grant every time until process dies
        projection = null
        handlerThread?.quitSafely()
        handlerThread = null
        handler = null
        Log.i(TAG, "monitor stopped")
    }
}

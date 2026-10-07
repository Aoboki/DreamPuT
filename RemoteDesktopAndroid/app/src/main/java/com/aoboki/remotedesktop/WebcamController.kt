package com.aoboki.remotedesktop

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.media.ImageReader
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import android.util.Log
//
import org.json.JSONObject
import java.io.ByteArrayOutputStream

/**
 * Front/back camera → JPEG frames on /ws/webcam/host/{hostId} if server expects it,
 * else also notify host channel.
 *
 * Note: full WebRTC webcam path is PC-oriented; we send simple JPEG frames.
 */
object WebcamController {
    private const val TAG = "WebcamCtrl"

    @Volatile
    private var running = false
    private var cameraDevice: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var imageReader: ImageReader? = null
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var webcamWs: SimpleWebSocket? = null

    fun start(ctx: Context, hostId: String, serverBase: String) {
        if (running) return
        val app = ctx.applicationContext
        if (app.checkSelfPermission(Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) {
            Log.w(TAG, "CAMERA permission missing")
            HostService.instance?.sendText(
                JSONObject()
                    .put("type", "webcam_status")
                    .put("host_id", hostId)
                    .put("running", false)
                    .put("status", "need_camera_permission")
                    .toString()
            )
            return
        }

        thread = HandlerThread("webcam").also { it.start() }
        handler = Handler(thread!!.looper)

        val base = serverBase.replace("https://", "wss://").replace("http://", "ws://").trimEnd('/')
        // PC stack uses dedicated webcam signaling; try host webcam path
        val url = "$base/ws/webcam/host/$hostId"
        webcamWs = SimpleWebSocket(url, object : SimpleWebSocket.Listener {
            override fun onOpen() {
                Log.i(TAG, "webcam WS open")
            }
            override fun onMessage(text: String) {
                Log.d(TAG, "webcam ← $text")
            }
            override fun onClosing(code: Int, reason: String) {}
            override fun onFailure(t: Throwable) {
                Log.e(TAG, "webcam WS ${t.message}")
            }
        })
        webcamWs?.connect()

        val cm = app.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val cameraId = cm.cameraIdList.firstOrNull { id ->
            val facing = cm.getCameraCharacteristics(id)
                .get(CameraCharacteristics.LENS_FACING)
            facing == CameraCharacteristics.LENS_FACING_FRONT ||
                facing == CameraCharacteristics.LENS_FACING_BACK
        } ?: cm.cameraIdList.firstOrNull()

        if (cameraId == null) {
            Log.e(TAG, "no camera")
            return
        }

        val w = 640
        val h = 480
        imageReader = ImageReader.newInstance(w, h, ImageFormat.YUV_420_888, 2)
        imageReader?.setOnImageAvailableListener({ reader ->
            val image = reader.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val jpeg = yuvToJpeg(image, 50) ?: return@setOnImageAvailableListener
                val b64 = Base64.encodeToString(jpeg, Base64.NO_WRAP)
                // Best-effort frame message (PC uses WebRTC; server may ignore)
                val msg = JSONObject()
                    .put("type", "webcam_frame")
                    .put("image", b64)
                    .toString()
                webcamWs?.send(msg)
            } catch (e: Exception) {
                Log.e(TAG, "frame ${e.message}")
            } finally {
                image.close()
            }
        }, handler)

        cm.openCamera(cameraId, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                cameraDevice = camera
                try {
                    camera.createCaptureSession(
                        listOf(imageReader!!.surface),
                        object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(s: CameraCaptureSession) {
                                session = s
                                val req = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                                req.addTarget(imageReader!!.surface)
                                s.setRepeatingRequest(req.build(), null, handler)
                                running = true
                                Log.i(TAG, "camera streaming")
                            }

                            override fun onConfigureFailed(session: CameraCaptureSession) {
                                Log.e(TAG, "camera configure failed")
                            }
                        },
                        handler
                    )
                } catch (e: Exception) {
                    Log.e(TAG, "session ${e.message}")
                }
            }

            override fun onDisconnected(camera: CameraDevice) {
                stop(app)
            }

            override fun onError(camera: CameraDevice, error: Int) {
                Log.e(TAG, "camera error $error")
                stop(app)
            }
        }, handler)
    }

    fun stop(ctx: Context) {
        running = false
        try {
            session?.close()
        } catch (_: Exception) {
        }
        session = null
        try {
            cameraDevice?.close()
        } catch (_: Exception) {
        }
        cameraDevice = null
        try {
            imageReader?.close()
        } catch (_: Exception) {
        }
        imageReader = null
        try {
            webcamWs?.close()
        } catch (_: Exception) {
        }
        webcamWs = null
        thread?.quitSafely()
        thread = null
        handler = null
        Log.i(TAG, "webcam stopped")
    }

    private fun yuvToJpeg(image: android.media.Image, quality: Int): ByteArray? {
        return try {
            val yBuffer = image.planes[0].buffer
            val uBuffer = image.planes[1].buffer
            val vBuffer = image.planes[2].buffer
            val ySize = yBuffer.remaining()
            val uSize = uBuffer.remaining()
            val vSize = vBuffer.remaining()
            val nv21 = ByteArray(ySize + uSize + vSize)
            yBuffer.get(nv21, 0, ySize)
            vBuffer.get(nv21, ySize, vSize)
            uBuffer.get(nv21, ySize + vSize, uSize)
            val yuv = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
            val out = ByteArrayOutputStream()
            yuv.compressToJpeg(Rect(0, 0, image.width, image.height), quality, out)
            out.toByteArray()
        } catch (e: Exception) {
            Log.e(TAG, "yuv ${e.message}")
            null
        }
    }
}

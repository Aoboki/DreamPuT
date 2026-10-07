package com.aoboki.remotedesktop

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.util.TypedValue
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.media.projection.MediaProjectionManager

class MainActivity : Activity() {

    private lateinit var editServer: EditText
    private lateinit var editHostId: EditText
    private lateinit var textStatus: TextView
    private lateinit var textDevice: TextView

    companion object {
        private const val REQUEST_SCREEN = 1001
        private const val REQUEST_CAMERA = 1002
    }

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != HostService.ACTION_STATUS) return
            val status = intent.getStringExtra(HostService.EXTRA_STATUS) ?: "offline"
            val detail = intent.getStringExtra(HostService.EXTRA_DETAIL) ?: ""
            applyStatus(status, detail)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val pad = dp(16)
        val match = ViewGroup.LayoutParams.MATCH_PARENT
        val wrap = ViewGroup.LayoutParams.WRAP_CONTENT

        fun lp(top: Int = 0): LinearLayout.LayoutParams {
            return LinearLayout.LayoutParams(match, wrap).apply {
                topMargin = top
            }
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#0F172A"))
            setPadding(pad, pad, pad, pad)
            layoutParams = ViewGroup.LayoutParams(match, wrap)
        }

        fun addLabel(t: String) {
            val v = TextView(this).apply {
                text = t
                setTextColor(Color.parseColor("#CBD5E1"))
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            }
            root.addView(v, lp(dp(12)))
        }

        fun addField(): EditText {
            val e = EditText(this).apply {
                setBackgroundColor(Color.parseColor("#1E293B"))
                setTextColor(Color.parseColor("#E2E8F0"))
                setHintTextColor(Color.parseColor("#64748B"))
                setPadding(dp(12), dp(12), dp(12), dp(12))
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            }
            root.addView(e, lp(dp(4)))
            return e
        }

        val title = TextView(this).apply {
            text = "DreamPUT Host"
            setTextColor(Color.parseColor("#F1F5F9"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 22f)
        }
        root.addView(title, lp())

        val sub = TextView(this).apply {
            text = "Phone card on remote.aoboki.pp.ua"
            setTextColor(Color.parseColor("#94A3B8"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        }
        root.addView(sub, lp(dp(4)))

        addLabel("Server URL")
        editServer = addField().also {
            it.hint = "wss://remote.aoboki.pp.ua"
            it.setText(HostPrefs.getServer(this))
        }

        addLabel("Host ID")
        editHostId = addField().also {
            it.hint = "phone_id"
            it.setText(HostPrefs.getHostId(this))
        }

        textStatus = TextView(this).apply {
            setBackgroundColor(Color.parseColor("#1E293B"))
            setPadding(dp(14), dp(14), dp(14), dp(14))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        }
        root.addView(textStatus, lp(dp(16)))

        textDevice = TextView(this).apply {
            text = DeviceInfo.shortSummary(this@MainActivity)
            setTextColor(Color.parseColor("#94A3B8"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        }
        root.addView(textDevice, lp(dp(10)))

        val btnStart = Button(this).apply {
            text = "Start / Connect"
            setBackgroundColor(Color.parseColor("#2563EB"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                saveFields()
                requestNotifPermissionIfNeeded()
                HostService.start(this@MainActivity)
                applyStatus("connecting", "Starting…")
            }
        }
        root.addView(btnStart, lp(dp(20)))

        val btnStop = Button(this).apply {
            text = "Stop"
            setBackgroundColor(Color.parseColor("#334155"))
            setTextColor(Color.parseColor("#E2E8F0"))
            setOnClickListener {
                HostService.stop(this@MainActivity)
                applyStatus("offline", "Stopped")
            }
        }
        root.addView(btnStop, lp(dp(10)))

        val btnScreen = Button(this).apply {
            text = "Grant screen capture (for Monitor)"
            setBackgroundColor(Color.parseColor("#0F766E"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                val mpm = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                startActivityForResult(mpm.createScreenCaptureIntent(), REQUEST_SCREEN)
            }
        }
        root.addView(btnScreen, lp(dp(10)))

        val btnCam = Button(this).apply {
            text = "Grant camera (for Webcam)"
            setBackgroundColor(Color.parseColor("#7C3AED"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                if (checkSelfPermission(android.Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(arrayOf(android.Manifest.permission.CAMERA), REQUEST_CAMERA)
                } else {
                    applyStatus("online", "Camera already granted")
                }
            }
        }
        root.addView(btnCam, lp(dp(10)))

        val hint = TextView(this).apply {
            text = "1) Start/Connect  2) Grant screen + camera  3) Use site buttons Monitor/Webcam/Files"
            setTextColor(Color.parseColor("#64748B"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
        }
        root.addView(hint, lp(dp(16)))

        val scroll = ScrollView(this).apply {
            setBackgroundColor(Color.parseColor("#0F172A"))
            addView(root)
        }
        setContentView(scroll)

        if (HostService.isRunning) {
            applyStatus(HostService.lastStatus, "Service running")
        } else {
            applyStatus("offline", "Not connected")
        }
    }

    override fun onStart() {
        super.onStart()
        val filter = IntentFilter(HostService.ACTION_STATUS)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(statusReceiver, filter, RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(statusReceiver, filter)
        }
    }

    override fun onStop() {
        try {
            unregisterReceiver(statusReceiver)
        } catch (e: Exception) {
            // ignore
        }
        super.onStop()
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_SCREEN) {
            MonitorController.onPermissionResult(resultCode, data)
            if (resultCode == RESULT_OK) {
                applyStatus(HostService.lastStatus, "Screen capture granted")
            } else {
                applyStatus("offline", "Screen capture denied")
            }
        }
    }

    private fun saveFields() {
        HostPrefs.setServer(this, editServer.text.toString())
        HostPrefs.setHostId(this, editHostId.text.toString())
        editHostId.setText(HostPrefs.getHostId(this))
        editServer.setText(HostPrefs.getServer(this))
    }

    private fun applyStatus(status: String, detail: String) {
        val color = when (status) {
            "online" -> Color.parseColor("#4ADE80")
            "connecting" -> Color.parseColor("#FBBF24")
            else -> Color.parseColor("#F87171")
        }
        textStatus.setTextColor(color)
        textStatus.text = "Status: $status\n$detail"
    }

    private fun requestNotifPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 100)
            }
        }
    }

    private fun dp(v: Int): Int =
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP,
            v.toFloat(),
            resources.displayMetrics
        ).toInt()
}

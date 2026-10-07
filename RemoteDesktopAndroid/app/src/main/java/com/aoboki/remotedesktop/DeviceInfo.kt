package com.aoboki.remotedesktop

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.Environment
import android.os.StatFs
import android.os.SystemClock
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object DeviceInfo {

    fun buildHostInfo(ctx: Context, hostId: String): JSONObject {
        val mem = memoryInfo(ctx)
        val disk = diskInfo()
        val uptimeSec = TimeUnit.MILLISECONDS.toSeconds(SystemClock.elapsedRealtime())
        val uptimeText = formatUptime(uptimeSec)

        return JSONObject()
            .put("type", "host_info")
            .put("host_id", hostId)
            .put("name", Build.MODEL ?: "Android")
            .put("computer_name", Build.MODEL ?: "Android")
            .put("username", Build.MANUFACTURER ?: "user")
            .put("os", "Android")
            .put("os_version", Build.VERSION.RELEASE ?: "")
            .put("os_release", "Android ${Build.VERSION.RELEASE}")
            .put("architecture", Build.SUPPORTED_ABIS.getOrNull(0) ?: "arm64")
            .put("python_version", "Android/${Build.VERSION.SDK_INT}")
            .put("cpu", Build.HARDWARE ?: "arm")
            .put("cpu_count", Runtime.getRuntime().availableProcessors())
            .put("cpu_percent", estimateCpuPercent())
            .put("cpu_temperature", JSONObject.NULL)
            .put("memory", mem)
            .put("disk", disk)
            .put("windows_boot_time", JSONObject.NULL)
            .put("windows_uptime", uptimeText)
            .put("uptime_seconds", uptimeSec)
            .put("boot_time", System.currentTimeMillis() / 1000.0 - uptimeSec)
            .put("monitor_running", false)
            .put("webcam_running", false)
            .put("powershell_running", false)
            .put("platform", "android")
    }

    fun buildHeartbeat(hostId: String): JSONObject =
        JSONObject()
            .put("type", "heartbeat")
            .put("host_id", hostId)
            .put("timestamp", System.currentTimeMillis() / 1000.0)

    private fun memoryInfo(ctx: Context): JSONObject {
        return try {
            val am = ctx.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
            val mi = ActivityManager.MemoryInfo()
            am.getMemoryInfo(mi)
            val total = mi.totalMem.toDouble()
            val avail = mi.availMem.toDouble()
            val used = (total - avail).coerceAtLeast(0.0)
            val totalGb = total / (1024.0 * 1024.0 * 1024.0)
            val usedGb = used / (1024.0 * 1024.0 * 1024.0)
            val freeGb = avail / (1024.0 * 1024.0 * 1024.0)
            val percent = if (total > 0) (used / total) * 100.0 else 0.0
            JSONObject()
                .put("total_gb", round1(totalGb))
                .put("used_gb", round1(usedGb))
                .put("free_gb", round1(freeGb))
                .put("percent", round1(percent))
        } catch (e: Exception) {
            JSONObject()
                .put("total_gb", JSONObject.NULL)
                .put("used_gb", JSONObject.NULL)
                .put("free_gb", JSONObject.NULL)
                .put("percent", JSONObject.NULL)
        }
    }

    private fun diskInfo(): JSONObject {
        return try {
            val path = Environment.getDataDirectory()
            val st = StatFs(path.path)
            val total = st.blockCountLong * st.blockSizeLong.toDouble()
            val free = st.availableBlocksLong * st.blockSizeLong.toDouble()
            val used = total - free
            JSONObject()
                .put("total_gb", round1(total / (1024.0 * 1024.0 * 1024.0)))
                .put("used_gb", round1(used / (1024.0 * 1024.0 * 1024.0)))
                .put("free_gb", round1(free / (1024.0 * 1024.0 * 1024.0)))
                .put("percent", if (total > 0) round1(used / total * 100.0) else 0.0)
        } catch (e: Exception) {
            JSONObject()
                .put("total_gb", JSONObject.NULL)
                .put("used_gb", JSONObject.NULL)
                .put("free_gb", JSONObject.NULL)
                .put("percent", JSONObject.NULL)
        }
    }

    /** Lightweight load estimate (not exact system CPU). */
    private fun estimateCpuPercent(): Double {
        return try {
            val runtime = Runtime.getRuntime()
            val used = (runtime.totalMemory() - runtime.freeMemory()).toDouble()
            val max = runtime.maxMemory().toDouble().coerceAtLeast(1.0)
            round1((used / max) * 100.0).coerceIn(1.0, 99.0)
        } catch (e: Exception) {
            0.0
        }
    }

    private fun formatUptime(seconds: Long): String {
        val d = seconds / 86400
        val h = (seconds % 86400) / 3600
        val m = (seconds % 3600) / 60
        val s = seconds % 60
        return if (d > 0) "${d}d ${h}h ${m}m ${s}s" else "${h}h ${m}m ${s}s"
    }

    private fun round1(v: Double): Double = kotlin.math.round(v * 10.0) / 10.0

    fun shortSummary(ctx: Context): String {
        val model = Build.MODEL ?: "?"
        val ver = Build.VERSION.RELEASE ?: "?"
        return "$model · Android $ver · SDK ${Build.VERSION.SDK_INT}"
    }
}

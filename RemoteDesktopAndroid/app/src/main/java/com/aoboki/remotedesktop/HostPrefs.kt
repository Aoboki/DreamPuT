package com.aoboki.remotedesktop

import android.content.Context
import android.os.Build
import android.provider.Settings

object HostPrefs {
    private const val PREFS = "host_prefs"
    private const val KEY_SERVER = "server_url"
    private const val KEY_HOST_ID = "host_id"
    private const val KEY_AUTO = "auto_start"

    const val DEFAULT_SERVER = "wss://remote.aoboki.pp.ua"

    fun getServer(ctx: Context): String {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return p.getString(KEY_SERVER, DEFAULT_SERVER)?.trim()?.ifEmpty { DEFAULT_SERVER }
            ?: DEFAULT_SERVER
    }

    fun setServer(ctx: Context, url: String) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_SERVER, url.trim())
            .apply()
    }

    fun getHostId(ctx: Context): String {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val saved = p.getString(KEY_HOST_ID, null)?.trim()
        if (!saved.isNullOrEmpty()) return saved
        val generated = defaultHostId(ctx)
        setHostId(ctx, generated)
        return generated
    }

    fun setHostId(ctx: Context, id: String) {
        val clean = id.trim()
            .lowercase()
            .replace(Regex("[^a-z0-9_\\-]"), "_")
            .take(48)
            .ifEmpty { defaultHostId(ctx) }
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_HOST_ID, clean)
            .apply()
    }

    fun isAutoStart(ctx: Context): Boolean =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_AUTO, true)

    fun setAutoStart(ctx: Context, enabled: Boolean) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_AUTO, enabled)
            .apply()
    }

    private fun defaultHostId(ctx: Context): String {
        val model = (Build.MODEL ?: "android")
            .lowercase()
            .replace(Regex("[^a-z0-9]"), "")
            .take(12)
            .ifEmpty { "phone" }
        val androidId = Settings.Secure.getString(
            ctx.contentResolver,
            Settings.Secure.ANDROID_ID
        ) ?: "000000"
        val shortId = androidId.takeLast(6).lowercase()
        return "${model}_$shortId"
    }
}

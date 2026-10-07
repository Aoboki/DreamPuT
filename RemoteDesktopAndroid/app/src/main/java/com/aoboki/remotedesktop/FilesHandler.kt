package com.aoboki.remotedesktop

import android.os.Environment
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

/**
 * Android equivalent of agent files_* commands.
 * Paths use Android storage roots, not Windows drives.
 */
object FilesHandler {

    fun handle(command: String, data: JSONObject): JSONObject {
        val requestId = data.optString("request_id", data.optString("id", ""))
        return try {
            val result = when (command) {
                "files_drives" -> drives()
                "files_list" -> list(data.optString("path", defaultRoot()))
                "files_mkdir" -> mkdir(data.optString("path"))
                "files_delete" -> delete(data.optString("path"))
                "files_rename" -> rename(data.optString("path"), data.optString("new_path"))
                else -> JSONObject().put("ok", false).put("error", "unsupported: $command")
            }
            result.put("type", "files_result")
            if (requestId.isNotEmpty()) result.put("request_id", requestId)
            result.put("command", command)
            result
        } catch (e: Exception) {
            JSONObject()
                .put("type", "files_result")
                .put("ok", false)
                .put("error", e.message ?: "error")
                .put("command", command)
                .put("request_id", requestId)
        }
    }

    private fun defaultRoot(): String {
        return Environment.getExternalStorageDirectory()?.absolutePath
            ?: "/storage/emulated/0"
    }

    private fun drives(): JSONObject {
        val arr = JSONArray()
        val roots = mutableListOf<File>()
        Environment.getExternalStorageDirectory()?.let { roots.add(it) }
        roots.add(File("/storage/emulated/0"))
        roots.add(File("/sdcard"))
        val seen = HashSet<String>()
        for (r in roots) {
            if (!r.exists()) continue
            val path = try { r.canonicalPath } catch (_: Exception) { r.absolutePath }
            if (!seen.add(path)) continue
            arr.put(
                JSONObject()
                    .put("name", r.name.ifEmpty { "storage" })
                    .put("path", path)
                    .put("type", "dir")
            )
        }
        return JSONObject().put("ok", true).put("drives", arr).put("items", arr)
    }

    private fun list(pathRaw: String): JSONObject {
        val path = safePath(pathRaw.ifBlank { defaultRoot() })
        val dir = File(path)
        if (!dir.exists() || !dir.isDirectory) {
            return JSONObject().put("ok", false).put("error", "not a directory").put("path", path)
        }
        val items = JSONArray()
        val files = dir.listFiles() ?: emptyArray()
        files.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase(Locale.US) }))
            .forEach { f ->
                items.put(
                    JSONObject()
                        .put("name", f.name)
                        .put("path", f.absolutePath)
                        .put("type", if (f.isDirectory) "dir" else "file")
                        .put("size", if (f.isFile) f.length() else 0)
                        .put("mtime", f.lastModified())
                )
            }
        return JSONObject()
            .put("ok", true)
            .put("path", path)
            .put("items", items)
            .put("files", items)
    }

    private fun mkdir(pathRaw: String): JSONObject {
        val path = safePath(pathRaw)
        val ok = File(path).mkdirs() || File(path).isDirectory
        return JSONObject().put("ok", ok).put("path", path)
    }

    private fun delete(pathRaw: String): JSONObject {
        val path = safePath(pathRaw)
        val f = File(path)
        val ok = if (f.isDirectory) f.deleteRecursively() else f.delete()
        return JSONObject().put("ok", ok).put("path", path)
    }

    private fun rename(srcRaw: String, dstRaw: String): JSONObject {
        val src = File(safePath(srcRaw))
        val dst = File(safePath(dstRaw))
        val ok = src.renameTo(dst)
        return JSONObject().put("ok", ok).put("path", dst.absolutePath)
    }

    private fun safePath(path: String): String {
        val p = path.trim()
        // block obvious traversal outside storage roots
        if (p.contains("..")) {
            throw SecurityException("invalid path")
        }
        return p
    }
}

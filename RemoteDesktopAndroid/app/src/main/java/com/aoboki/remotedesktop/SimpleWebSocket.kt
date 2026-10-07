package com.aoboki.remotedesktop

import android.util.Base64 as AndroidBase64
import android.util.Log
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URI
import java.nio.charset.StandardCharsets
import java.security.SecureRandom
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * Minimal WSS client (text + ping/pong). Pure Android/JDK APIs.
 */
class SimpleWebSocket(
    private val url: String,
    private val listener: Listener
) {
    interface Listener {
        fun onOpen()
        fun onMessage(text: String)
        fun onClosing(code: Int, reason: String)
        fun onFailure(t: Throwable)
    }

    companion object {
        private const val TAG = "SimpleWS"
    }

    private val open = AtomicBoolean(false)
    private var socket: Socket? = null
    private var input: InputStream? = null
    private var output: OutputStream? = null
    private var readerThread: Thread? = null
    private var pingThread: Thread? = null
    private val writeLock = Any()

    val isOpen: Boolean get() = open.get()

    fun connect() {
        Thread({
            try {
                doConnect()
            } catch (t: Throwable) {
                open.set(false)
                closeQuietly()
                listener.onFailure(t)
            }
        }, "ws-connect").start()
    }

    fun send(text: String) {
        if (!open.get()) return
        try {
            writeFrame(0x1, text.toByteArray(StandardCharsets.UTF_8))
        } catch (t: Throwable) {
            open.set(false)
            listener.onFailure(t)
            closeQuietly()
        }
    }

    fun close() {
        try {
            if (open.get()) writeFrame(0x8, ByteArray(0))
        } catch (_: Exception) {
        }
        open.set(false)
        closeQuietly()
    }

    private fun doConnect() {
        val uri = URI(url)
        val scheme = (uri.scheme ?: "ws").lowercase()
        val host = uri.host ?: throw IllegalArgumentException("no host in $url")
        val port = when {
            uri.port > 0 -> uri.port
            scheme == "wss" -> 443
            else -> 80
        }
        val path = buildString {
            append(if (uri.rawPath.isNullOrEmpty()) "/" else uri.rawPath)
            if (!uri.rawQuery.isNullOrEmpty()) append("?").append(uri.rawQuery)
        }

        val sock: Socket = if (scheme == "wss") {
            val factory = SSLSocketFactory.getDefault() as SSLSocketFactory
            val ssl = factory.createSocket() as SSLSocket
            ssl.connect(InetSocketAddress(host, port), 20_000)
            ssl.startHandshake()
            ssl
        } else {
            val s = Socket()
            s.connect(InetSocketAddress(host, port), 20_000)
            s
        }
        sock.tcpNoDelay = true
        sock.keepAlive = true
        // no read timeout — long-lived socket
        sock.soTimeout = 0
        socket = sock
        input = BufferedInputStream(sock.getInputStream())
        output = BufferedOutputStream(sock.getOutputStream())

        val keyBytes = ByteArray(16)
        SecureRandom().nextBytes(keyBytes)
        val secKey = AndroidBase64.encodeToString(keyBytes, AndroidBase64.NO_WRAP)

        val handshake = buildString {
            append("GET ").append(path).append(" HTTP/1.1\r\n")
            append("Host: ").append(host)
            if (!(port == 80 && scheme == "ws") && !(port == 443 && scheme == "wss")) {
                append(":").append(port)
            }
            append("\r\n")
            append("Upgrade: websocket\r\n")
            append("Connection: Upgrade\r\n")
            append("Sec-WebSocket-Key: ").append(secKey).append("\r\n")
            append("Sec-WebSocket-Version: 13\r\n")
            append("\r\n")
        }
        output!!.write(handshake.toByteArray(StandardCharsets.US_ASCII))
        output!!.flush()

        val statusLine = readLine(input!!)
            ?: throw IllegalStateException("empty handshake response")
        if (!statusLine.contains("101")) {
            throw IllegalStateException("WS handshake failed: $statusLine")
        }
        while (true) {
            val line = readLine(input!!) ?: break
            if (line.isEmpty()) break
        }

        open.set(true)
        listener.onOpen()
        startPingLoop()

        readerThread = Thread({
            try {
                readLoop()
            } catch (t: Throwable) {
                if (open.get()) {
                    open.set(false)
                    listener.onFailure(t)
                }
            } finally {
                open.set(false)
                stopPingLoop()
                closeQuietly()
            }
        }, "ws-read").also { it.isDaemon = true; it.start() }
    }

    private fun startPingLoop() {
        stopPingLoop()
        pingThread = Thread({
            try {
                while (open.get()) {
                    Thread.sleep(8_000)
                    if (!open.get()) break
                    // WebSocket protocol ping — keeps Cloudflare/NAT alive
                    writeFrame(0x9, "hb".toByteArray(StandardCharsets.US_ASCII))
                }
            } catch (_: InterruptedException) {
            } catch (t: Throwable) {
                if (open.get()) {
                    open.set(false)
                    listener.onFailure(t)
                }
            }
        }, "ws-ping").also { it.isDaemon = true; it.start() }
    }

    private fun stopPingLoop() {
        try {
            pingThread?.interrupt()
        } catch (_: Exception) {
        }
        pingThread = null
    }

    private fun readLoop() {
        val inp = input ?: return
        while (open.get()) {
            val b0 = inp.read()
            if (b0 < 0) break
            val b1 = inp.read()
            if (b1 < 0) break
            val opcode = b0 and 0x0f
            val masked = (b1 and 0x80) != 0
            var len = (b1 and 0x7f).toLong()
            when (len) {
                126L -> {
                    val b = readFully(inp, 2)
                    len = ((b[0].toInt() and 0xff) shl 8 or (b[1].toInt() and 0xff)).toLong()
                }
                127L -> {
                    val b = readFully(inp, 8)
                    len = 0
                    for (i in 0 until 8) {
                        len = (len shl 8) or (b[i].toInt() and 0xff).toLong()
                    }
                }
            }
            val mask = if (masked) readFully(inp, 4) else null
            if (len > 16_000_000) throw IllegalStateException("frame too large: $len")
            val payload = if (len > 0) readFully(inp, len.toInt()) else ByteArray(0)
            if (mask != null) {
                for (i in payload.indices) {
                    payload[i] = (payload[i].toInt() xor mask[i % 4].toInt()).toByte()
                }
            }
            when (opcode) {
                0x1 -> listener.onMessage(String(payload, StandardCharsets.UTF_8))
                0x2 -> { /* binary ignored */ }
                0x8 -> {
                    open.set(false)
                    listener.onClosing(1000, "peer closed")
                    return
                }
                0x9 -> writeFrame(0xA, payload) // pong
                0xA -> { /* pong ok */ }
                else -> Log.d(TAG, "opcode $opcode ignored")
            }
        }
        if (open.get()) {
            open.set(false)
            listener.onClosing(1000, "EOF")
        }
    }

    private fun writeFrame(opcode: Int, payload: ByteArray) {
        val out = output ?: return
        synchronized(writeLock) {
            val maskKey = ByteArray(4)
            SecureRandom().nextBytes(maskKey)
            val header = ByteArrayOutputStream()
            header.write(0x80 or (opcode and 0x0f))
            val len = payload.size
            when {
                len < 126 -> header.write(0x80 or len)
                len <= 0xffff -> {
                    header.write(0x80 or 126)
                    header.write((len shr 8) and 0xff)
                    header.write(len and 0xff)
                }
                else -> {
                    header.write(0x80 or 127)
                    var v = len.toLong()
                    val eight = ByteArray(8)
                    for (i in 7 downTo 0) {
                        eight[i] = (v and 0xff).toByte()
                        v = v shr 8
                    }
                    header.write(eight)
                }
            }
            header.write(maskKey)
            val masked = ByteArray(payload.size)
            for (i in payload.indices) {
                masked[i] = (payload[i].toInt() xor maskKey[i % 4].toInt()).toByte()
            }
            out.write(header.toByteArray())
            out.write(masked)
            out.flush()
        }
    }

    private fun readLine(inp: InputStream): String? {
        val buf = ByteArrayOutputStream()
        while (true) {
            val c = inp.read()
            if (c < 0) {
                return if (buf.size() == 0) null else buf.toString(StandardCharsets.US_ASCII.name())
            }
            if (c == '\n'.code) break
            if (c != '\r'.code) buf.write(c)
        }
        return buf.toString(StandardCharsets.US_ASCII.name())
    }

    private fun readFully(inp: InputStream, n: Int): ByteArray {
        val buf = ByteArray(n)
        var off = 0
        while (off < n) {
            val r = inp.read(buf, off, n - off)
            if (r < 0) throw IllegalStateException("EOF reading frame")
            off += r
        }
        return buf
    }

    private fun closeQuietly() {
        stopPingLoop()
        try { input?.close() } catch (_: Exception) {}
        try { output?.close() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}
        input = null
        output = null
        socket = null
    }
}

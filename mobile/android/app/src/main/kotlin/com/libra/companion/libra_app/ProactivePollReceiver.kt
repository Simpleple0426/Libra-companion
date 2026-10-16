package com.libra.companion.libra_app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Notification
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

class ProactivePollReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        thread {
            try {
                poll(context)
            } finally {
                pending.finish()
            }
        }
    }

    private fun poll(context: Context) {
        val preferences = context.getSharedPreferences("libra_privacy", Context.MODE_PRIVATE)
        if (!preferences.getBoolean("proactive_enabled", false)) return
        val baseUrl = preferences.getString("api_base_url", "")?.trimEnd('/') ?: return
        if (baseUrl.isBlank()) return
        val afterId = preferences.getInt("last_proactive_message_id", 0)
        val connection = URL("$baseUrl/messages/updates?after_id=$afterId")
            .openConnection() as HttpURLConnection
        connection.connectTimeout = 10_000
        connection.readTimeout = 10_000
        connection.requestMethod = "GET"
        try {
            if (connection.responseCode !in 200..299) return
            val payload = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            val messages = payload.optJSONArray("messages") ?: return
            var newestId = afterId
            val texts = mutableListOf<String>()
            for (index in 0 until messages.length()) {
                val message = messages.optJSONObject(index) ?: continue
                newestId = maxOf(newestId, message.optInt("id", 0))
                val content = message.optString("content").trim()
                if (content.isNotEmpty()) texts.add(content)
            }
            if (newestId > afterId) {
                preferences.edit().putInt("last_proactive_message_id", newestId).apply()
            }
            if (texts.isNotEmpty()) showNotification(context, texts)
        } finally {
            connection.disconnect()
        }
    }

    private fun showNotification(context: Context, messages: List<String>) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "libra_proactive"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "左然的消息",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                description = "Libra 主动发来的消息"
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                enableVibration(true)
            }
            manager.createNotificationChannel(channel)
        }
        val openIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
        val pendingIntent = PendingIntent.getActivity(
            context,
            2720,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val body = messages.last()
        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(context.applicationInfo.icon)
            .setContentTitle("左然")
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setNumber(messages.size)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
        manager.notify(2721, notification)
    }
}

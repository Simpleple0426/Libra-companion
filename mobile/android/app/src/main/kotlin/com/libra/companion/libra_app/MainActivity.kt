package com.libra.companion.libra_app

import android.app.AlarmManager
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.CalendarContract
import android.util.Log
import androidx.core.content.ContextCompat
import android.content.pm.PackageManager
import androidx.core.app.NotificationCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.Calendar

class MainActivity : FlutterActivity() {
    private val channelName = "com.libra.companion/app_usage"
    private val privateDataSaveRequest = 2721
    private var pendingPrivateDataResult: MethodChannel.Result? = null
    private var pendingPrivateDataUrl: String? = null
    private var focusWakeLock: PowerManager.WakeLock? = null

    @Suppress("DEPRECATION")
    private fun setFocusScreenAwake(enabled: Boolean) {
        if (enabled) {
            window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            if (focusWakeLock?.isHeld != true) {
                val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
                focusWakeLock = powerManager.newWakeLock(
                    PowerManager.SCREEN_BRIGHT_WAKE_LOCK or PowerManager.ON_AFTER_RELEASE,
                    "Libra:StudyRoomFocus",
                ).also { it.acquire() }
            }
        } else {
            window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            focusWakeLock?.let { if (it.isHeld) it.release() }
            focusWakeLock = null
        }
    }

    override fun onDestroy() {
        stopService(Intent(this, FocusPlaybackService::class.java))
        setFocusScreenAwake(false)
        super.onDestroy()
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        createProactiveNotificationChannel()
        val privacy = getSharedPreferences("libra_privacy", Context.MODE_PRIVATE)
        configureProactivePolling(
            privacy.getBoolean("proactive_enabled", false) &&
                privacy.getBoolean("push_fallback_enabled", false),
        )
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "setFocusBackgroundPlayback" -> {
                        try {
                            val intent = Intent(this, FocusPlaybackService::class.java)
                            if (call.argument<Boolean>("enabled") == true) {
                                ContextCompat.startForegroundService(this, intent)
                            } else {
                                stopService(intent)
                            }
                            result.success(null)
                        } catch (error: Exception) {
                            result.error("focus_playback_service", error.message, null)
                        }
                    }
                    "getTodayEvents" -> result.success(getTodayEvents())
                    "getCalendarEvents" -> {
                        val startMillis = call.argument<Number>("startMillis")?.toLong() ?: 0L
                        val endMillis = call.argument<Number>("endMillis")?.toLong() ?: 0L
                        if (startMillis <= 0L || endMillis <= startMillis) {
                            result.error("invalid_range", "日历查询范围无效", null)
                        } else {
                            try {
                                result.success(getCalendarEvents(startMillis, endMillis))
                            } catch (error: SecurityException) {
                                result.error("calendar_permission", "没有系统日历读取权限", null)
                            } catch (error: Exception) {
                                result.error("calendar_read_failed", error.message, null)
                            }
                        }
                    }
                    "recordRoomEvent" -> {
                        val roomName = call.argument<String>("roomName")?.trim().orEmpty()
                        if (roomName.isNotEmpty()) recordRoomEvent(roomName)
                        result.success(null)
                    }
                    "recordFocusEvent" -> {
                        val description = call.argument<String>("description")?.trim().orEmpty()
                        if (description.isNotEmpty()) recordActivityEvent(description)
                        result.success(null)
                    }
                    "setKeepScreenOn" -> {
                        val enabled = call.argument<Boolean>("enabled") ?: false
                        setFocusScreenAwake(enabled)
                        result.success(null)
                    }
                    "getProactiveEnabled" -> {
                        val enabled = getSharedPreferences("libra_privacy", Context.MODE_PRIVATE)
                            .getBoolean("proactive_enabled", false)
                        result.success(enabled)
                    }
                    "setProactiveEnabled" -> {
                        val enabled = call.argument<Boolean>("enabled") ?: false
                        val baseUrl = call.argument<String>("baseUrl") ?: ""
                        getSharedPreferences("libra_privacy", Context.MODE_PRIVATE)
                            .edit()
                            .putBoolean("proactive_enabled", enabled)
                            .putString("api_base_url", baseUrl)
                            .apply()
                        val fallbackEnabled = getSharedPreferences(
                            "libra_privacy",
                            Context.MODE_PRIVATE,
                        ).getBoolean("push_fallback_enabled", false)
                        configureProactivePolling(enabled && fallbackEnabled)
                        if (enabled && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 2719)
                        }
                        result.success(null)
                    }
                    "setPushFallbackEnabled" -> {
                        val enabled = call.argument<Boolean>("enabled") ?: false
                        val baseUrl = call.argument<String>("baseUrl")
                        val latestMessageId = call.argument<Int>("latestMessageId")
                        val preferences = getSharedPreferences(
                            "libra_privacy",
                            Context.MODE_PRIVATE,
                        )
                        val editor = preferences.edit()
                            .putBoolean("push_fallback_enabled", enabled)
                        if (!baseUrl.isNullOrBlank()) {
                            editor.putString("api_base_url", baseUrl)
                        }
                        if (latestMessageId != null && latestMessageId > 0) {
                            editor.putInt("last_proactive_message_id", latestMessageId)
                        }
                        editor.apply()
                        configureProactivePolling(
                            enabled && preferences.getBoolean("proactive_enabled", false),
                        )
                        result.success(null)
                    }
                    "showProactiveNotification" -> {
                        val title = call.argument<String>("title") ?: "左然"
                        val body = call.argument<String>("body")?.trim().orEmpty()
                        val messageId = call.argument<String>("messageId").orEmpty()
                        if (body.isNotEmpty()) {
                            showProactiveNotification(title, body, messageId)
                        }
                        result.success(null)
                    }
                    "downloadPrivateData" -> {
                        val downloadUrl = call.argument<String>("url").orEmpty()
                        val fileName = call.argument<String>("fileName")
                            ?.takeIf { it.isNotBlank() }
                            ?: "libra-private-data.zip"
                        if (!downloadUrl.startsWith("http://") &&
                            !downloadUrl.startsWith("https://")) {
                            result.error("missing_file", "待导出的 ZIP 文件不存在", null)
                        } else if (pendingPrivateDataResult != null) {
                            result.error("save_in_progress", "已有文件正在保存", null)
                        } else {
                            pendingPrivateDataResult = result
                            pendingPrivateDataUrl = downloadUrl
                            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                                addCategory(Intent.CATEGORY_OPENABLE)
                                type = "application/zip"
                                putExtra(Intent.EXTRA_TITLE, fileName)
                            }
                            try {
                                startActivityForResult(intent, privateDataSaveRequest)
                            } catch (error: Exception) {
                                pendingPrivateDataResult = null
                                pendingPrivateDataUrl = null
                                result.error("save_unavailable", error.message, null)
                            }
                        }
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun getCalendarEvents(
        startMillis: Long,
        endMillis: Long,
    ): List<Map<String, Any?>> {
        if (ContextCompat.checkSelfPermission(
                this,
                android.Manifest.permission.READ_CALENDAR,
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            throw SecurityException("READ_CALENDAR not granted")
        }
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon()
            .appendPath(startMillis.toString())
            .appendPath(endMillis.toString())
            .build()
        val projection = arrayOf(
            CalendarContract.Instances.EVENT_ID,
            CalendarContract.Instances.TITLE,
            CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END,
            CalendarContract.Instances.ALL_DAY,
            CalendarContract.Instances.EVENT_LOCATION,
            CalendarContract.Instances.CALENDAR_ID,
        )
        val rows = mutableListOf<Map<String, Any?>>()
        contentResolver.query(uri, projection, null, null, "${CalendarContract.Instances.BEGIN} ASC")
            ?.use { cursor ->
                val eventIdIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.EVENT_ID)
                val titleIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.TITLE)
                val beginIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.BEGIN)
                val endIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.END)
                val allDayIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.ALL_DAY)
                val locationIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.EVENT_LOCATION)
                val calendarIdIndex = cursor.getColumnIndexOrThrow(CalendarContract.Instances.CALENDAR_ID)
                while (cursor.moveToNext()) {
                    val title = cursor.getString(titleIndex)?.trim().orEmpty()
                    if (title.isEmpty()) continue
                    val eventId = cursor.getLong(eventIdIndex)
                    val begin = cursor.getLong(beginIndex)
                    rows.add(
                        mapOf(
                            "id" to "android:${cursor.getLong(calendarIdIndex)}:$eventId:$begin",
                            "title" to title,
                            "startMillis" to begin,
                            "endMillis" to cursor.getLong(endIndex),
                            "allDay" to (cursor.getInt(allDayIndex) == 1),
                            "location" to cursor.getString(locationIndex),
                        ),
                    )
                }
            }
        Log.i(
            "LibraCalendar",
            "Loaded ${rows.size} native calendar instances; " +
                "test=${rows.count { it["title"].toString().equals("test", ignoreCase = true) }}",
        )
        return rows
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != privateDataSaveRequest) return
        val result = pendingPrivateDataResult
        val downloadUrl = pendingPrivateDataUrl
        pendingPrivateDataResult = null
        pendingPrivateDataUrl = null
        if (result == null) return
        val destination: Uri? = data?.data
        if (resultCode != Activity.RESULT_OK || destination == null || downloadUrl == null) {
            result.success(false)
            return
        }
        Thread {
            var connection: HttpURLConnection? = null
            try {
                connection = URL(downloadUrl).openConnection() as HttpURLConnection
                connection.connectTimeout = 30_000
                connection.readTimeout = 10 * 60_000
                connection.requestMethod = "GET"
                connection.setRequestProperty("Accept", "application/zip")
                connection.connect()
                val status = connection.responseCode
                if (status !in 200..299) error("Backend export failed (HTTP $status)")
                connection.inputStream.use { input ->
                    contentResolver.openOutputStream(destination, "w").use { output ->
                        if (output == null) error("无法打开所选保存位置")
                        input.copyTo(output)
                    }
                }
                runOnUiThread { result.success(true) }
            } catch (error: Exception) {
                runOnUiThread {
                    result.error("save_failed", error.message ?: "保存失败", null)
                }
            } finally {
                connection?.disconnect()
            }
        }.start()
    }

    private fun showProactiveNotification(title: String, body: String, messageId: String) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "libra_proactive"
        createProactiveNotificationChannel()
        val openIntent = packageManager.getLaunchIntentForPackage(packageName)
            ?: Intent(this, MainActivity::class.java)
        openIntent.flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
        val pendingIntent = PendingIntent.getActivity(
            this,
            2720,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()
        val notificationId = messageId.toIntOrNull() ?: messageId.hashCode()
        manager.notify(notificationId, notification)
    }

    private fun createProactiveNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(
                    "libra_proactive",
                    "左然的消息",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "Libra 主动发送的消息"
                    enableVibration(true)
                    lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
                },
            )
        }
    }

    private fun configureProactivePolling(enabled: Boolean) {
        val alarmManager = getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val intent = Intent(this, ProactivePollReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            this,
            2718,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        alarmManager.cancel(pendingIntent)
        if (!enabled) return
        val interval = 60 * 1000L
        alarmManager.setInexactRepeating(
            AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis() + interval,
            interval,
            pendingIntent,
        )
    }

    private fun getTodayEvents(): List<Map<String, Any>> {
        val calendar = Calendar.getInstance().apply {
            if (get(Calendar.HOUR_OF_DAY) < 4) add(Calendar.DAY_OF_MONTH, -1)
            set(Calendar.HOUR_OF_DAY, 4)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        val rows = mutableListOf<Map<String, Any>>()
        val roomEvents = getSharedPreferences("libra_activity", Context.MODE_PRIVATE)
            .getStringSet("room_events", emptySet())
            .orEmpty()
        roomEvents.forEach { stored ->
            val timestamp = stored.substringBefore('|').toLongOrNull() ?: return@forEach
            if (timestamp < calendar.timeInMillis) return@forEach
            val description = stored.substringAfter('|')
            if (description == "simple正在自习室") return@forEach
            rows.add(
                mapOf(
                    "timestamp" to timestamp,
                    "action" to "room",
                    "appName" to "",
                    "description" to description,
                )
            )
        }
        return rows.sortedBy { it["timestamp"] as Long }.takeLast(30)
    }

    private fun recordRoomEvent(roomName: String) {
        val preferences = getSharedPreferences("libra_activity", Context.MODE_PRIVATE)
        val events = preferences.getStringSet("room_events", emptySet())!!.toMutableSet()
        events.add("${System.currentTimeMillis()}|${userDisplayName(this)}正在$roomName")
        val trimmed = events
            .sortedByDescending { it.substringBefore('|').toLongOrNull() ?: 0L }
            .take(100)
            .toSet()
        preferences.edit().putStringSet("room_events", trimmed).apply()
    }

    private fun recordActivityEvent(description: String) {
        val preferences = getSharedPreferences("libra_activity", Context.MODE_PRIVATE)
        val events = preferences.getStringSet("room_events", emptySet())!!.toMutableSet()
        events.add("${System.currentTimeMillis()}|$description")
        val trimmed = events
            .sortedByDescending { it.substringBefore('|').toLongOrNull() ?: 0L }
            .take(100)
            .toSet()
        preferences.edit().putStringSet("room_events", trimmed).apply()
    }

}

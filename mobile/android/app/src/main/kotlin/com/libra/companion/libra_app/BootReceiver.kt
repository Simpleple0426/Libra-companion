package com.libra.companion.libra_app

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val preferences = context.getSharedPreferences("libra_privacy", Context.MODE_PRIVATE)
        if (!preferences.getBoolean("proactive_enabled", false)) return
        if (!preferences.getBoolean("push_fallback_enabled", false)) return

        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val pollIntent = Intent(context, ProactivePollReceiver::class.java)
        val pendingIntent = PendingIntent.getBroadcast(
            context,
            2718,
            pollIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val interval = 60 * 1000L
        alarmManager.setInexactRepeating(
            AlarmManager.RTC_WAKEUP,
            System.currentTimeMillis() + interval,
            interval,
            pendingIntent,
        )
    }
}

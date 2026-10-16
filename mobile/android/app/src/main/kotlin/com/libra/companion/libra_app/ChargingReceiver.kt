package com.libra.companion.libra_app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager

class ChargingReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val started = intent.action == Intent.ACTION_POWER_CONNECTED
        val batteryIntent = context.registerReceiver(
            null,
            IntentFilter(Intent.ACTION_BATTERY_CHANGED),
        )
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        val percentage = if (level >= 0 && scale > 0) level * 100 / scale else 0
        val description = if (started) {
            "${userDisplayName(context)}手机开始充电了：当前电量$percentage%"
        } else {
            "${userDisplayName(context)}手机结束充电了：当前电量$percentage%"
        }

        val preferences = context.getSharedPreferences("libra_activity", Context.MODE_PRIVATE)
        val events = preferences.getStringSet("charging_events", emptySet())!!.toMutableSet()
        events.add("${System.currentTimeMillis()}|$description")
        val trimmed = events
            .sortedByDescending { it.substringBefore('|').toLongOrNull() ?: 0L }
            .take(100)
            .toSet()
        preferences.edit().putStringSet("charging_events", trimmed).apply()
    }
}

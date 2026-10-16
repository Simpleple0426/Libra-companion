package com.libra.companion.libra_app

import android.content.Context

fun userDisplayName(context: Context): String =
    context.getSharedPreferences("FlutterSharedPreferences", Context.MODE_PRIVATE)
        .getString("flutter.profile_user_nickname", null)
        ?.trim()?.takeIf { it.isNotEmpty() } ?: "我"

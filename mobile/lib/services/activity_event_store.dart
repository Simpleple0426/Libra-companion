import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/app_usage_event.dart';

class ActivityEventStore {
  static const _key = 'local_home_activity_events';

  Future<List<AppUsageEvent>> loadToday() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return [];
    try {
      final now = DateTime.now();
      final day = now.subtract(const Duration(hours: 4));
      final start = DateTime(day.year, day.month, day.day, 4);
      final end = start.add(const Duration(days: 1));
      final events =
          (jsonDecode(raw) as List)
              .whereType<Map<String, dynamic>>()
              .map(AppUsageEvent.fromJson)
              .where(
                (event) =>
                    !event.timestamp.isBefore(start) &&
                    event.timestamp.isBefore(end),
              )
              .toList()
            ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
      return events;
    } catch (_) {
      return [];
    }
  }

  Future<void> add(AppUsageEvent event) async {
    final prefs = await SharedPreferences.getInstance();
    final current = await loadToday();
    current.add(event);
    await prefs.setString(
      _key,
      jsonEncode(current.take(200).map((item) => item.toJson()).toList()),
    );
  }
}

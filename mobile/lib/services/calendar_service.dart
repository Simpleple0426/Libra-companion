import 'dart:convert';
import 'dart:io';

import 'package:device_calendar/device_calendar.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:lunar/lunar.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/calendar_entry.dart';

class CalendarLoadResult {
  const CalendarLoadResult({required this.events, required this.hasPermission});
  final List<CalendarEntry> events;
  final bool hasPermission;
}

class ChineseCalendarInfo {
  const ChineseCalendarInfo({required this.dayLabel, required this.festivals});
  final String dayLabel;
  final List<String> festivals;
}

class CalendarService {
  final DeviceCalendarPlugin _plugin = DeviceCalendarPlugin();
  static const _nativeChannel = MethodChannel('com.libra.companion/app_usage');

  static ChineseCalendarInfo chineseInfo(DateTime date) {
    final solar = Solar.fromYmd(date.year, date.month, date.day);
    final lunar = solar.getLunar();
    final solarFestivals = <String>{...solar.getFestivals()};
    final lunarFestivals = <String>{...lunar.getFestivals()};
    final jieQi = lunar.getJieQi().trim();
    final festivals = <String>{
      ...solarFestivals,
      ...lunarFestivals,
      if (jieQi.isNotEmpty) jieQi,
    }.where((name) => name.trim().isNotEmpty).toList();
    final dayLabel = jieQi.isNotEmpty
        ? jieQi
        : lunarFestivals.isNotEmpty
        ? lunarFestivals.first
        : solarFestivals.isNotEmpty
        ? solarFestivals.first
        : lunar.getDayInChinese();
    return ChineseCalendarInfo(dayLabel: dayLabel, festivals: festivals);
  }

  static bool _isLowPriorityObservance(String title) {
    return title.contains('逝世') ||
        title.contains('诞辰纪念') ||
        title.contains('宣传日');
  }

  Future<CalendarLoadResult> loadMonth(
    DateTime month, {
    bool requestPermission = false,
  }) async {
    final start = DateTime(month.year, month.month - 1, 20);
    final end = DateTime(month.year, month.month + 2, 10);
    return loadRange(start, end, requestPermission: requestPermission);
  }

  Future<CalendarLoadResult> loadRange(
    DateTime start,
    DateTime end, {
    bool requestPermission = false,
  }) async {
    var permission = await _plugin.hasPermissions();
    if (permission.data != true && requestPermission) {
      permission = await _plugin.requestPermissions();
    }
    final events = _festivalEvents(start, end);

    if (Platform.isAndroid) {
      try {
        final rows =
            await _nativeChannel
                .invokeListMethod<Object?>('getCalendarEvents', {
                  'startMillis': start.millisecondsSinceEpoch,
                  'endMillis': end.millisecondsSinceEpoch,
                }) ??
            const [];
        debugPrint(
          'Native calendar returned ${rows.length} rows; '
          'test=${rows.whereType<Map<Object?, Object?>>().where((row) => '${row['title']}'.toLowerCase() == 'test').length}',
        );
        for (final raw in rows.whereType<Map<Object?, Object?>>()) {
          final title = (raw['title'] as String? ?? '').trim();
          final startMillis = (raw['startMillis'] as num?)?.toInt();
          final endMillis = (raw['endMillis'] as num?)?.toInt();
          final allDay = raw['allDay'] as bool? ?? false;
          if (title.isEmpty ||
              startMillis == null ||
              (allDay && _isLowPriorityObservance(title))) {
            continue;
          }
          final eventStart = DateTime.fromMillisecondsSinceEpoch(startMillis);
          events.add(
            CalendarEntry(
              id: raw['id'] as String? ?? 'android:$startMillis:$title',
              title: title,
              start: eventStart,
              end: endMillis == null
                  ? eventStart
                  : DateTime.fromMillisecondsSinceEpoch(endMillis),
              allDay: allDay,
              location: raw['location'] as String?,
            ),
          );
        }
        events.sort((a, b) => a.start.compareTo(b.start));
        return CalendarLoadResult(events: events, hasPermission: true);
      } on PlatformException catch (error, stackTrace) {
        debugPrint('Native calendar bridge failed: $error');
        debugPrintStack(stackTrace: stackTrace);
        // Fall through to the plugin path on devices without the native bridge.
      }
    }

    if (permission.data != true) {
      return CalendarLoadResult(events: events, hasPermission: false);
    }

    final calendars = await _plugin.retrieveCalendars();
    for (final calendar in calendars.data ?? const <Calendar>[]) {
      if (calendar.id == null) continue;
      final result = await _plugin.retrieveEvents(
        calendar.id,
        RetrieveEventsParams(startDate: start, endDate: end),
      );
      for (final event in result.data ?? const <Event>[]) {
        final eventStart = event.start;
        final title = (event.title ?? '').trim();
        if (eventStart == null ||
            title.isEmpty ||
            ((event.allDay ?? false) && _isLowPriorityObservance(title))) {
          continue;
        }
        events.add(
          CalendarEntry(
            id: '${calendar.id}:${event.eventId ?? eventStart.millisecondsSinceEpoch}',
            title: title,
            start: eventStart,
            end: event.end ?? eventStart,
            allDay: event.allDay ?? false,
            location: event.location,
          ),
        );
      }
    }
    events.sort((a, b) => a.start.compareTo(b.start));
    return CalendarLoadResult(events: events, hasPermission: true);
  }

  List<CalendarEntry> _festivalEvents(DateTime start, DateTime end) {
    final events = <CalendarEntry>[];
    for (
      var date = start;
      date.isBefore(end);
      date = date.add(const Duration(days: 1))
    ) {
      for (final festival in chineseInfo(date).festivals) {
        events.add(
          CalendarEntry(
            id: 'festival:${date.year}-${date.month}-${date.day}:$festival',
            title: festival,
            start: date,
            end: date,
            allDay: true,
            source: 'festival',
          ),
        );
      }
    }
    return events;
  }

  Future<List<TodoItem>> loadTodos() async {
    final raw = (await SharedPreferences.getInstance()).getString(
      'calendar_todos',
    );
    if (raw == null) return [];
    try {
      return (jsonDecode(raw) as List)
          .whereType<Map<String, dynamic>>()
          .map(TodoItem.fromJson)
          .toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> saveTodos(List<TodoItem> todos) async {
    await (await SharedPreferences.getInstance()).setString(
      'calendar_todos',
      jsonEncode(todos.map((todo) => todo.toJson()).toList()),
    );
  }

  Future<List<HabitItem>> loadHabits() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('calendar_habits');
    if (raw == null) {
      // The backend is the source of truth.  A first launch must stay empty
      // until the user's own habits arrive instead of showing sample data.
      return const [];
    }
    try {
      final habits = (jsonDecode(raw) as List)
          .whereType<Map<String, dynamic>>()
          .map(HabitItem.fromJson)
          .toList();
      final normalized = habits.where((habit) {
        if (habit.activeUntil == null || habit.completedDates.isNotEmpty) {
          return true;
        }
        final title = habit.title.trim();
        return !habits.any(
          (other) =>
              other.id != habit.id &&
              other.title.trim() == title &&
              other.activeFrom.isAfter(habit.activeFrom),
        );
      }).toList();
      if (normalized.length != habits.length) {
        await prefs.setString(
          'calendar_habits',
          jsonEncode(normalized.map((habit) => habit.toJson()).toList()),
        );
      }
      return normalized;
    } catch (_) {
      return const [];
    }
  }

  Future<void> saveHabits(List<HabitItem> habits) async {
    await (await SharedPreferences.getInstance()).setString(
      'calendar_habits',
      jsonEncode(habits.map((habit) => habit.toJson()).toList()),
    );
  }
}

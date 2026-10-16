import 'package:flutter/material.dart';
import '../models/timeline_event.dart';
import '../services/display_names.dart';
import '../services/libra_schedule_day.dart';
import '../services/libra_api.dart';

/// A short preview of committed facts; tapping the parent opens the full feed.
class HomeLifeEvents extends StatelessWidget {
  const HomeLifeEvents({
    super.key,
    this.events,
    this.coarseActivity,
    this.coarsePlans = const [],
    this.loading = false,
    required this.scale,
    this.now,
  });

  final List<TimelineEvent>? events;
  final LifeCoarseActivity? coarseActivity;
  final List<LifeScheduleEntry> coarsePlans;
  final bool loading;
  final double scale;
  final DateTime? now;

  String _label(TimelineEvent event) {
    final text = DisplayNames.companionText(event.event.trim());
    final body = text.startsWith('左然')
        ? text.substring(2)
        : text.startsWith('Libra')
        ? text.substring(5)
        : text;
    return '${DisplayNames.libra}$body';
  }

  @override
  Widget build(BuildContext context) {
    const accent = Color(0xFFDE776C);
    final instant = now ?? DateTime.now();
    final rows = <({DateTime time, String text, bool location})>[
      for (final event in events ?? const <TimelineEvent>[])
        if (libraScheduleDay(event.occurredAt) == libraScheduleDay(instant) &&
            !event.occurredAt.isAfter(instant) &&
            const {
              'moving_start',
              'arrived',
              'at_place',
              'reading_start',
              'watching_start',
              'housework_start',
              'care_start',
              'woke',
              'sleep_started',
              'user_time_start',
              'companion_update',
            }.contains(event.kind))
          (
            time: event.occurredAt,
            text: _label(event),
            location: !{
              'user_time_start',
              'companion_update',
              'woke',
              'sleep_started',
            }.contains(event.kind),
          ),
    ]..sort((a, b) => a.time.compareTo(b.time));
    final visibleRows = rows.length > 10
        ? rows.sublist(rows.length - 10)
        : rows;
    if (visibleRows.isNotEmpty) {
      return ListView.separated(
        reverse: true,
        padding: EdgeInsets.symmetric(vertical: 8 * scale),
        itemCount: visibleRows.length,
        separatorBuilder: (_, _) => SizedBox(height: 4 * scale),
        itemBuilder: (_, index) {
          final row = visibleRows[visibleRows.length - 1 - index];
          return Container(
            padding: EdgeInsets.symmetric(
              horizontal: 7 * scale,
              vertical: 7 * scale,
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: EdgeInsets.only(top: 1.5 * scale),
                  child: Icon(
                    row.location
                        ? Icons.location_on_rounded
                        : Icons.auto_awesome_rounded,
                    color: accent.withValues(alpha: .78),
                    size: 20 * scale,
                  ),
                ),
                SizedBox(width: 6 * scale),
                SizedBox(
                  width: 48 * scale,
                  child: Text(
                    '${row.time.hour.toString().padLeft(2, '0')}:${row.time.minute.toString().padLeft(2, '0')}',
                    style: TextStyle(
                      fontSize: 15 * scale,
                      color: accent.withValues(alpha: .72),
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                SizedBox(width: 5 * scale),
                Expanded(
                  child: Text(
                    row.text,
                    style: TextStyle(
                      fontSize: 17 * scale,
                      height: 1.42,
                      color: const Color(0xFF5D5755),
                    ),
                  ),
                ),
              ],
            ),
          );
        },
      );
    }
    final today = libraScheduleDay(instant);
    final recent =
        (events ?? const <TimelineEvent>[])
            .where(
              (event) =>
                  libraScheduleDay(event.occurredAt) == today &&
                  !event.occurredAt.isAfter(instant) &&
                  event.kind != 'agenda_changed',
            )
            .toList()
          ..sort((a, b) => a.occurredAt.compareTo(b.occurredAt));
    final visible = recent.reversed.take(3).toList().reversed.toList();
    if (visible.isEmpty) {
      return Center(
        child: Text(
          events == null
              ? (loading ? '正在获取生活动态…' : '生活动态暂时无法获取')
              : '${DisplayNames.libra}今天还没有动态',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 14 * scale,
            color: const Color(0xFF9DAAAD),
          ),
        ),
      );
    }
    return ListView.separated(
      reverse: true,
      padding: EdgeInsets.symmetric(vertical: 8 * scale),
      itemCount: visible.length,
      separatorBuilder: (_, _) => SizedBox(height: 14 * scale),
      itemBuilder: (_, index) {
        final event = visible[visible.length - 1 - index];
        final time = event.occurredAt;
        final movement = {
          'moving_start',
          'arrived',
          'work_arrival',
          'work_departure',
          'at_place',
        }.contains(event.kind);
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.only(top: 2 * scale),
              child: Icon(
                movement ? Icons.location_on_rounded : Icons.auto_awesome,
                color: accent,
                size: 15 * scale,
              ),
            ),
            SizedBox(width: 5 * scale),
            Text(
              '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}',
              style: TextStyle(
                fontSize: 12 * scale,
                color: accent,
                height: 1.5,
              ),
            ),
            SizedBox(width: 10 * scale),
            Expanded(
              child: Text(
                _label(event),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 14 * scale,
                  color: const Color(0xFF756A65),
                  height: 1.4,
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

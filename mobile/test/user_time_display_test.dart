import 'package:flutter/material.dart';
import 'package:libra_app/services/display_names.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:libra_app/models/timeline_event.dart';
import 'package:libra_app/screens/home_life_events.dart';
import 'package:libra_app/screens/life_schedule_sheet.dart';
import 'package:libra_app/services/libra_api.dart';
import 'package:libra_app/services/life_status_display.dart';

void main() {
  setUp(() => DisplayNames.user = 'simple');
  tearDown(() => DisplayNames.user = '我');
  final start = DateTime(2026, 9, 29, 14);
  final end = start.add(const Duration(hours: 2));
  Map<String, dynamic> response() => {
    'mode': 'enabled',
    'status': 'ready',
    'sleep': {'status': 'awake'},
    'coarse_activity': {'id': 'slot', 'kind': 'user_time', 'title': '陪用户逛漫展'},
    'daily_agenda': {
      'items': [
        {
          'id': 'slot',
          'state_type': 'free',
          'activity': 'user_time',
          'intent': '陪用户逛漫展',
          'title': '陪用户逛漫展',
          'place': null,
          'place_name': '',
          'start_at': start.toIso8601String(),
          'end_at': end.toIso8601String(),
          'constraints': {'required_routine': 'user_time'},
        },
      ],
    },
  };

  test(
    'specific appointment title survives API parsing and status display',
    () {
      final status = LifeSystemStatus.fromJson(response());
      expect(status.schedule.single.kind, 'user_time');
      expect(status.schedule.single.title, '陪用户逛漫展');
      expect(status.schedule.single.place, isEmpty);
      expect(coarseLifeStatusLabel(status), '陪simple逛漫展');
    },
  );

  testWidgets(
    'schedule card shows the subject without a location placeholder',
    (tester) async {
      final status = LifeSystemStatus.fromJson(response());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: LifeScheduleSheet(entries: status.schedule)),
        ),
      );
      expect(find.text('陪simple逛漫展'), findsOneWidget);
      expect(find.text('14:00—16:00'), findsOneWidget);
      expect(find.textContaining('地点未知'), findsNothing);
    },
  );

  testWidgets(
    'home shows one committed appointment dynamic with its exact subject',
    (tester) async {
      final status = LifeSystemStatus.fromJson(response());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: HomeLifeEvents(
              scale: 1,
              now: start.add(const Duration(minutes: 1)),
              coarsePlans: status.schedule,
              events: [
                TimelineEvent(
                  id: 'start',
                  occurredAt: start,
                  event: '左然正在陪用户逛漫展',
                  kind: 'user_time_start',
                ),
              ],
            ),
          ),
        ),
      );
      expect(find.text('左然正在陪simple逛漫展'), findsOneWidget);
      expect(find.text('左然正在自由安排'), findsNothing);
      expect(find.byIcon(Icons.location_on_rounded), findsNothing);
    },
  );

  testWidgets('an unstarted reservation does not invent an activity dynamic', (
    tester,
  ) async {
    final status = LifeSystemStatus.fromJson(response());
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: HomeLifeEvents(
            scale: 1,
            now: start,
            coarsePlans: status.schedule,
            events: const [],
          ),
        ),
      ),
    );
    expect(find.text('左然正在陪simple逛漫展'), findsNothing);
  });

  test('active companionship has a shared status even across sleep', () {
    final body = response();
    body['companion'] = {'id': 'companion:one'};
    body['sleep'] = {'status': 'sleeping'};
    final status = LifeSystemStatus.fromJson(body);
    expect(status.companionSessionId, 'companion:one');
    expect(coarseLifeStatusLabel(status), '陪伴中');
    expect(status.coarseActivity!.title, '陪用户逛漫展');
  });

  testWidgets('open ended companionship has no invented deadline', (
    tester,
  ) async {
    final body = response();
    body['daily_agenda']['items'][0]['open_ended'] = true;
    final status = LifeSystemStatus.fromJson(body);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: LifeScheduleSheet(entries: status.schedule)),
      ),
    );
    expect(find.text('14:00—结束时间未定'), findsOneWidget);
  });
  testWidgets('elapsed shower plan is not an observed shower event', (
    tester,
  ) async {
    final data = response();
    final agenda = data['daily_agenda'] as Map<String, dynamic>;
    final item = (agenda['items'] as List).single as Map<String, dynamic>;
    item.addAll({
      'state_type': 'free',
      'activity': 'shower',
      'intent': '洗澡',
      'title': '洗澡',
      'place': 'home.f2.bathroom',
      'place_name': '家',
      'constraints': <String, dynamic>{},
    });
    final status = LifeSystemStatus.fromJson(data);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: HomeLifeEvents(
            scale: 1,
            now: start.add(const Duration(minutes: 40)),
            coarsePlans: status.schedule,
            events: [
              TimelineEvent(
                id: 'home',
                occurredAt: start.add(const Duration(minutes: 35)),
                event: '左然回到了家',
                kind: 'arrived',
              ),
            ],
          ),
        ),
      ),
    );
    expect(find.text('左然回到了家'), findsOneWidget);
    expect(find.textContaining('洗澡'), findsNothing);
  });
  testWidgets('home retains wake time alongside later morning care', (
    tester,
  ) async {
    final wake = DateTime(2026, 9, 30, 7);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: HomeLifeEvents(
            scale: 1,
            now: wake.add(const Duration(minutes: 10)),
            events: [
              TimelineEvent(
                id: 'wake',
                occurredAt: wake,
                event: '左然起床了',
                kind: 'woke',
              ),
              TimelineEvent(
                id: 'wash',
                occurredAt: wake.add(const Duration(minutes: 1)),
                event: '左然正在刷牙',
                kind: 'care_start',
              ),
            ],
          ),
        ),
      ),
    );
    expect(find.text('左然起床了'), findsOneWidget);
    expect(find.text('07:00'), findsOneWidget);
    expect(find.text('左然正在刷牙'), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('左然起床了')).dy,
      lessThan(tester.getTopLeft(find.text('左然正在刷牙')).dy),
    );
  });
}

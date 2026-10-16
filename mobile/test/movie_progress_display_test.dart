import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/screens/libra_activity_page.dart';
import 'package:libra_app/services/libra_api.dart';

void main() {
  testWidgets('movie progress updates above the unchanged event history', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    var seconds = 1200;
    final now = DateTime.now();
    const history = '左然正在观看《乱世佳人》，进度：00:00:00 / 03:41:00';
    final api = LibraApi(
      client: MockClient((request) async {
        final data = request.url.path == '/life-system/status'
            ? {
                'mode': 'enabled',
                'status': 'ready',
                'place_name': '影音区',
                'sleep': {'status': 'awake'},
                'coarse_activity': {
                  'id': 'movie-slot',
                  'kind': 'free',
                  'title': '看电影',
                },
                'activity': {
                  'id': 'movie-session',
                  'kind': 'watching',
                  'status': 'running',
                  'target_name': '乱世佳人',
                  'progress': seconds,
                  'total': 13260,
                },
              }
            : {
                'events': [
                  {
                    'id': 'movie-start',
                    'occurred_at': now.toIso8601String(),
                    'event': history,
                    'kind': 'watching_start',
                  },
                ],
              };
        return http.Response(
          jsonEncode(data),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    await tester.pumpWidget(MaterialApp(home: LibraActivityPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('已看 00:20:00 / 03:41:00'), findsOneWidget);
    expect(find.text('当前安排：看电影'), findsNothing);
    expect(find.textContaining(history), findsOneWidget);
    expect(tester.takeException(), isNull);
    seconds = 1210;
    await tester.pump(const Duration(seconds: 10));
    await tester.pumpAndSettle();
    expect(find.textContaining('已看 00:20:10 / 03:41:00'), findsOneWidget);
    expect(find.textContaining(history), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}

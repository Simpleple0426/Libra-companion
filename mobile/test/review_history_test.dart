import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/screens/diary_reading.dart';
import 'package:libra_app/services/libra_api.dart';

void main() {
  testWidgets('review shows only current content and no history controls on phone layout', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final requests = <Uri>[];
    final api = LibraApi(client: MockClient((request) async {
      requests.add(request.url);
      final history = request.url.queryParameters['kind'] == 'dreams';
      return http.Response(jsonEncode({'items': [{
        'id': history ? 'snapshot' : 'current', 'period_type': 'day',
        'period_start': '2026-10-03', 'period_end': '2026-10-04',
        'generated_at': '2026-10-04T00:00:00Z', 'available': true,
        'complete_period': true, 'content': history ? '旧版本原文' : '当前回顾原文',
        'reflection': '', 'scenes': [], 'foresight': [],
      }], 'has_more': false}), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    }));
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: ReviewReading(api: api))));
    await tester.pumpAndSettle();
    expect(find.text('历史版本'), findsNothing);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('当前回顾原文'));
    await tester.pumpAndSettle();
    expect(find.text('回望时的想法'), findsNothing);
    expect(find.text('查看这一天的历史版本'), findsNothing);
    expect(requests.every((uri) => uri.queryParameters['kind'] == 'reviews'), isTrue);
    expect(find.text('当前回顾原文'), findsWidgets);
    expect(find.text('梦中片刻'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

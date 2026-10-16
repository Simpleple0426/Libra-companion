import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/screens/timeline_page.dart';
import 'package:libra_app/services/libra_api.dart';

void main() {
  testWidgets('returning to timeline and resuming reloads shared memories', (tester) async {
    var requests = 0;
    final api = LibraApi(client: MockClient((request) async {
      requests++;
      return http.Response(jsonEncode({'success': true, 'shared_memories': []}), 200);
    }));
    addTearDown(api.close);
    Widget page(bool active) => MaterialApp(home: Scaffold(body: TimelinePage(api: api, active: active)));
    await tester.pumpWidget(page(false));
    await tester.pumpAndSettle();
    expect(requests, 1);
    await tester.pumpWidget(page(true));
    await tester.pumpAndSettle();
    expect(requests, 2);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pumpAndSettle();
    expect(requests, 3);
  });
}

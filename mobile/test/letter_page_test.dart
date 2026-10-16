import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/screens/timeline_page.dart';
import 'package:libra_app/services/libra_api.dart';

void main() {
  testWidgets('letter detail labels my replies and retains the original across rounds', (tester) async {
    final letters = [
      {'id': 1, 'sender': 'libra', 'content': '原信全文', 'reply_to_id': null},
      {'id': 2, 'sender': 'user', 'content': '我的第一次回复', 'reply_to_id': 1},
      {'id': 3, 'sender': 'libra', 'content': '他的后续回复', 'reply_to_id': 2},
    ].map((item) => {...item, 'created_at': '2026-10-04T12:00:00',
      'read_at': '2026-10-04T12:00:00', 'favorite': false, 'subject': ''}).toList();
    final api = LibraApi(client: MockClient((request) async => http.Response(
      jsonEncode(request.url.path == '/letters'
          ? {'success': true, 'letters': letters}
          : {'success': true, 'shared_memories': []}), 200,
      headers: {'content-type': 'application/json; charset=utf-8'},
    )));
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: TimelinePage(api: api))));
    await tester.pumpAndSettle();
    await tester.tap(find.text('信件'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('原信全文'));
    await tester.pumpAndSettle();
    expect(find.text('我的信'), findsOneWidget);
    expect(find.text('原信全文'), findsWidgets);
    expect(find.text('我的第一次回复'), findsOneWidget);
    expect(find.text('他的后续回复'), findsOneWidget);
  });
}

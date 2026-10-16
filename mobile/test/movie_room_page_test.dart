import 'dart:convert';
import 'dart:async';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/screens/movie_room_page.dart';
import 'package:libra_app/screens/movie_library_page.dart';
import 'package:libra_app/services/movie_room_api.dart';

http.Response response(Object data) => http.Response(
  jsonEncode(data),
  200,
  headers: {'content-type': 'application/json; charset=utf-8'},
);

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  testWidgets('room sends to movie endpoint and filters by selected day', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final requests = <http.Request>[];
    final api = MovieRoomApi(
      client: MockClient((request) async {
        requests.add(request);
        if (request.method == 'POST') {
          final body = jsonDecode(request.body);
          expect(body['message'], '这个镜头很好看');
          expect(body['viewing_id'], 'view-1');
          expect(body['request_id'], startsWith('movie-'));
          return response({'success': true});
        }
        return response({
          'messages': [
            {
              'id': 1,
              'role': 'assistant',
              'content': '我也留意到了。',
              'created_at': '2026-09-30T18:10:00',
            },
          ],
          'current': {'id': 'view-1', 'title': '测试电影', 'paused': false},
          'next_before': null,
        });
      }),
    );
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: MovieRoomPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('正在观看 · 测试电影'), findsOneWidget);
    await tester.enterText(find.byType(TextField), '这个镜头很好看');
    await tester.tap(find.byTooltip('发送'));
    await tester.pumpAndSettle();
    expect(
      requests.any(
        (r) => r.url.path == '/movie-room/chat' && r.method == 'POST',
      ),
      isTrue,
    );
    await tester.tap(find.byTooltip('按天查找聊天'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('查看'));
    await tester.pumpAndSettle();
    expect(requests.last.url.queryParameters['date'], isNotNull);
    expect(find.byType(TextField), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('sent bubble appears before reply and polling reconciles it', (
    tester,
  ) async {
    final reply = Completer<http.Response>();
    String? requestId;
    final api = MovieRoomApi(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          requestId = jsonDecode(request.body)['request_id'] as String;
          return reply.future;
        }
        return response({
          'messages': [
            if (requestId != null)
              {
                'id': 10,
                'role': 'user',
                'content': '立即显示这句话',
                'request_id': requestId,
                'created_at': '2026-09-30T20:00:00',
              },
          ],
          'current': null,
          'next_before': null,
        });
      }),
    );
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: MovieRoomPage(api: api)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '立即显示这句话');
    await tester.tap(find.byTooltip('发送'));
    await tester.pump();
    expect(find.widgetWithText(SelectableText, '立即显示这句话'), findsOneWidget);
    expect(
      tester.widget<TextField>(find.byType(TextField)).controller!.text,
      isEmpty,
    );
    expect(find.text('左然正在想怎么和你说…'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
    await tester.pump();
    expect(find.widgetWithText(SelectableText, '立即显示这句话'), findsOneWidget);
    reply.complete(response({'success': true}));
    await tester.pumpAndSettle();
    expect(find.widgetWithText(SelectableText, '立即显示这句话'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'outbox survives reopen and receipt unlocks before late failed POST',
    (tester) async {
      final ids = <String>[];
      final lateReply = Completer<http.Response>();
      bool completed = false;
      final api = MovieRoomApi(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            ids.add(jsonDecode(request.body)['request_id'] as String);
            if (ids.length == 1) throw http.ClientException('offline');
            return lateReply.future;
          }
          return response({
            'messages': [],
            'current': null,
            'next_before': null,
            if (completed)
              'request_state': {
                'request_id': ids.first,
                'completed': true,
                'messages': [
                  {
                    'id': 20,
                    'role': 'user',
                    'content': '断网后保留',
                    'request_id': ids.first,
                    'created_at': '2026-09-30T20:00:00',
                  },
                  {
                    'id': 21,
                    'role': 'assistant',
                    'content': '已收到你的消息',
                    'created_at': '2026-09-30T20:00:01',
                  },
                ],
              },
          });
        }),
      );
      addTearDown(api.close);
      await tester.pumpWidget(MaterialApp(home: MovieRoomPage(api: api)));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '断网后保留');
      await tester.tap(find.byTooltip('发送'));
      await tester.pumpAndSettle();
      final prefs = await SharedPreferences.getInstance();
      expect(
        prefs.getKeys().any((key) => key.startsWith('movie_room_outbox:')),
        isTrue,
      );
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(MaterialApp(home: MovieRoomPage(api: api)));
      await tester.pumpAndSettle();
      expect(find.widgetWithText(SelectableText, '断网后保留'), findsOneWidget);
      await tester.tap(find.text('回复暂未完成，点击重试'));
      await tester.pump();
      await tester.pump();
      expect(ids, [ids.first, ids.first]);
      completed = true;
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(find.byType(TextField)).enabled, isTrue);
      expect(find.text('回复暂未完成，点击重试'), findsNothing);
      expect(find.widgetWithText(SelectableText, '断网后保留'), findsOneWidget);
      expect(find.text('已收到你的消息'), findsOneWidget);
      expect(
        prefs.getKeys().any((key) => key.startsWith('movie_room_outbox:')),
        isFalse,
      );
      lateReply.completeError(http.ClientException('late disconnect'));
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(find.byType(TextField)).enabled, isTrue);
      expect(find.text('回复暂未完成，点击重试'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('shared movie shows date quotes and review inside detail', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final api = MovieRoomApi(
      client: MockClient(
        (_) async => response({
          'solo': [],
          'shared': [
            {
              'id': 'one',
              'title': '共同电影',
              'started_at': '2026-09-30T18:00:00',
              'position': 1200,
              'status': 'completed',
              'review_status': 'ready',
              'review': '留在心里的影评',
              'quotes': [
                {'text': '实际字幕原句', 'thought': '他的感触'},
              ],
            },
          ],
          'solo_available': true,
        }),
      ),
    );
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: MovieLibraryPage(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('我们一起看'));
    await tester.pumpAndSettle();
    expect(find.text('2026-09-30 · 已一起看完'), findsOneWidget);
    await tester.tap(find.text('共同电影'));
    await tester.pumpAndSettle();
    expect(find.textContaining('实际字幕原句'), findsOneWidget);
    expect(find.textContaining('留在心里的影评'), findsOneWidget);
    expect(find.text('我们已经看完了'), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });
}

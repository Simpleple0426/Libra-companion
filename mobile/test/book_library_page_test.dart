import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/screens/book_library_page.dart';
import 'package:libra_app/services/libra_api.dart';

void main() {
  testWidgets('opens book detail and preserves search on return', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final response = Completer<http.Response>();
    final api = LibraApi(
      client: MockClient((request) {
        expect(request.url.path, '/reading/library');
        return response.future;
      }),
    );
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: BookLibraryPage(api: api)));
    expect(find.text('左然的书库'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    response.complete(
      http.Response(
        jsonEncode({
          'books': [
            {
              'id': 'one',
              'title': '测试书',
              'author': '作者',
              'reading_status': 'unread',
              'progress_percent': 0,
              'introduction': '这本书的简介',
              'introduction_status': 'ready',
              'quotes': [
                {'text': '摘抄原句', 'thought': '他的阅读想法', 'translation': '译文内容'},
              ],
            },
          ],
        }),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('未开始阅读'), findsOneWidget);
    expect(find.text('这本书的简介'), findsNothing);
    await tester.tap(find.text('测试书'));
    await tester.pumpAndSettle();
    expect(find.text('这本书的简介'), findsOneWidget);
    expect(find.text('阅读手记'), findsOneWidget);
    expect(find.text('“摘抄原句”'), findsOneWidget);
    expect(find.text('译文内容'), findsOneWidget);
    expect(find.text('他的阅读想法'), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, '不存在的书');
    await tester.pumpAndSettle();
    expect(find.text('没有找到这本书'), findsOneWidget);
    await tester.enterText(find.byType(TextField).first, '作者');
    await tester.pumpAndSettle();
    expect(find.text('测试书'), findsOneWidget);
  });

  testWidgets('failed request offers retry', (tester) async {
    var attempts = 0;
    final api = LibraApi(
      client: MockClient((_) async {
        attempts++;
        return http.Response(
          attempts == 1 ? '{}' : '{"books":[]}',
          attempts == 1 ? 500 : 200,
        );
      }),
    );
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: BookLibraryPage(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重新加载'));
    await tester.pumpAndSettle();
    expect(attempts, 2);
    expect(find.text('书架上暂时还没有书'), findsOneWidget);
  });

  testWidgets('imports title and author without making a quote', (
    tester,
  ) async {
    var imported = false;
    final api = LibraApi(
      client: MockClient((request) async {
        if (request.method == 'POST') {
          expect(request.url.path, '/reading/library');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['title'], '新书');
          expect(body['author'], '新作者');
          imported = true;
          return http.Response(
            '{"book":{"title":"新书","author":"新作者"}}',
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response(
          jsonEncode({
            'books': imported
                ? [
                    {
                      'id': 'new',
                      'title': '新书',
                      'author': '新作者',
                      'reading_status': 'unread',
                      'progress_percent': 0,
                      'introduction': '',
                      'quotes': [],
                    },
                  ]
                : [],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    addTearDown(api.close);
    await tester.pumpWidget(MaterialApp(home: BookLibraryPage(api: api)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('导入'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).at(1), '新书');
    await tester.enterText(find.byType(TextField).at(2), '新作者');
    await tester.tap(find.text('加入书库'));
    await tester.pumpAndSettle();
    expect(find.text('新书'), findsOneWidget);
    expect(find.text('未开始阅读'), findsOneWidget);
    expect(find.text('名句摘抄与想法'), findsNothing);
  });
}

import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/models/chat_message.dart';
import 'package:libra_app/screens/chat_page.dart';
import 'package:libra_app/services/libra_api.dart';

class ClosingClient extends MockClient {
  ClosingClient(super.handler);
  bool closed = false;
  @override
  void close() {
    closed = true;
    super.close();
  }
}

class PollingChatApi extends LibraApi {
  final sends = <Completer<List<ChatMessage>>>[];
  bool committed = false;
  final reply = ChatMessage(id: 2, role: 'assistant', content: '已经回复了');
  @override
  Future<List<ChatMessage>> getMessagesForDate(DateTime date) async => [];
  @override
  Future<LibraSleepStatus> getSleepStatus() async =>
      const LibraSleepStatus(sleeping: false);
  @override
  Future<List<ChatMessage>> getMessageUpdates(int afterId) async =>
      committed && afterId < 2 ? [reply] : [];
  @override
  Future<Map<String, dynamic>> getChatStatus({String? requestId}) async => {
    'success': true,
    'pending': sends.isNotEmpty && !committed,
    'accepted': requestId != null,
    'reply_messages': committed && requestId != null
        ? [
            {'id': 2},
          ]
        : [],
  };
  @override
  Future<List<ChatMessage>> sendMessage(
    String message, {
    String? requestId,
    bool deviceContextEnabled = false,
    String replyMode = 'auto',
    String musicContext = '',
    bool fromMusicRoom = false,
    XhsCardData? xhsAttachment,
  }) {
    committed = false;
    final send = Completer<List<ChatMessage>>();
    sends.add(send);
    return send.future;
  }
}

void main() {
  test('poll reconnects after a broken read and closes both clients', () async {
    final clients = <ClosingClient>[];
    final api = LibraApi(
      pollingClientFactory: () {
        final attempt = clients.length;
        final client = ClosingClient((request) async {
          expect(request.headers['connection'], 'close');
          if (attempt == 0) throw http.ClientException('reset');
          return http.Response(jsonEncode({'messages': []}), 200);
        });
        clients.add(client);
        return client;
      },
    );
    addTearDown(api.close);
    await expectLater(
      api.getMessageUpdates(0),
      throwsA(isA<http.ClientException>()),
    );
    expect(await api.getMessageUpdates(0), isEmpty);
    expect(clients.every((client) => client.closed), isTrue);
  });

  testWidgets(
    'committed reply appears before POST completes; old POST cannot clear next reply',
    (tester) async {
      final api = PollingChatApi();
      addTearDown(api.close);
      await tester.pumpWidget(
        MaterialApp(
          home: ChatPage(
            api: api,
            deviceContextEnabled: false,
            refreshToken: 0,
            libraStatus: '在线',
            onAssistantMessagesReceived: (_) {},
          ),
        ),
      );
      await tester.pump();
      await tester.enterText(find.byType(TextField).first, '第一条');
      await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
      await tester.pump();
      expect(api.sends, hasLength(1));
      api.committed = true;
      await tester.pump(const Duration(seconds: 2));
      await tester.pump();
      expect(find.text('已经回复了'), findsOneWidget);
      expect(find.text('左然正在回复…'), findsNothing);
      await tester.enterText(find.byType(TextField).first, '第二条');
      await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
      await tester.pump();
      expect(api.sends, hasLength(2));
      api.sends.first.complete([api.reply]);
      await tester.pump();
      expect(find.text('左然正在回复…'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      for (final send in api.sends) {
        if (!send.isCompleted) send.complete([]);
      }
      await tester.pump();
    },
  );
}

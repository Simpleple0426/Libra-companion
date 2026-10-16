import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:libra_app/services/movie_room_api.dart';

void main() {
  test('a reset read reconnects once without reusing keep-alive', () async {
    var attempts = 0;
    final api = MovieRoomApi(
      client: MockClient((request) async {
        expect(request.headers['connection'], 'close');
        if (++attempts == 1)
          throw http.ClientException('Connection reset by peer');
        return http.Response('{"messages":[]}', 200);
      }),
    );
    addTearDown(api.close);
    expect(await api.request('/messages'), {'messages': []});
    expect(attempts, 2);
  });

  test('chat is never automatically resent after a connection reset', () async {
    var attempts = 0;
    final api = MovieRoomApi(
      client: MockClient((_) async {
        attempts++;
        throw http.ClientException('Connection reset by peer');
      }),
    );
    addTearDown(api.close);
    await expectLater(
      api.request('/chat', {'message': 'hello'}),
      throwsA(isA<MovieRoomException>()),
    );
    expect(attempts, 1);
  });

  test('read retry is bounded and service errors preserve status', () async {
    var attempts = 0;
    final api = MovieRoomApi(
      client: MockClient((_) async {
        attempts++;
        throw http.ClientException('reset');
      }),
    );
    addTearDown(api.close);
    await expectLater(
      api.request('/messages'),
      throwsA(isA<MovieRoomException>()),
    );
    expect(attempts, 2);
    final broken = MovieRoomApi(
      client: MockClient((_) async => http.Response('oops', 503)),
    );
    addTearDown(broken.close);
    await expectLater(
      broken.request('/messages'),
      throwsA(predicate((e) => e.toString().contains('503'))),
    );
  });
}

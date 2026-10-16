import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:libra_app/config/api_config.dart';
import 'package:libra_app/services/backend_connection.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'libra_api_base_url': 'http://192.168.1.10:8000',
      'profile_user_name': 'existing name',
    });
    await ApiConfig.initialize();
  });

  test(
    'upgrade requests reconnection and preserves existing phone data',
    () async {
      expect(ApiConfig.isConfigured, isFalse);
      expect(ApiConfig.baseUrl, 'http://192.168.1.10:8000');
      await ApiConfig.saveBaseUrl('https://example.com/connect/private-key/');
      await ApiConfig.initialize();
      expect(ApiConfig.isConfigured, isTrue);
      expect(ApiConfig.baseUrl, 'https://example.com/connect/private-key');
      final preferences = await SharedPreferences.getInstance();
      expect(preferences.getString('profile_user_name'), 'existing name');
    },
  );

  test(
    'connection probe preserves the key path and does not save it',
    () async {
      final client = MockClient((request) async {
        expect(
          request.url.toString(),
          'https://example.com/connect/private-key/',
        );
        return http.Response(
          '{"message":"Libra Companion backend is running"}',
          200,
        );
      });
      addTearDown(client.close);
      expect(
        await verifyBackendConnection(
          'https://example.com/connect/private-key/',
          client,
        ),
        'https://example.com/connect/private-key',
      );
      expect(ApiConfig.baseUrl, 'http://192.168.1.10:8000');
    },
  );

  test(
    'unauthorized and HTTPS test pages cannot replace a working connection',
    () async {
      await ApiConfig.saveBaseUrl('http://192.168.1.10:8000');
      for (final response in [
        http.Response('Unauthorized', 401),
        http.Response('Libra HTTPS is ready', 200),
        http.Response('{"message":"another service"}', 200),
      ]) {
        final client = MockClient((_) async => response);
        await expectLater(
          verifyBackendConnection('https://example.com', client),
          throwsFormatException,
        );
        client.close();
        expect(ApiConfig.baseUrl, 'http://192.168.1.10:8000');
        expect(ApiConfig.isConfigured, isTrue);
      }
    },
  );

  test(
    'private addresses require HTTPS and cannot hide keys in query strings',
    () {
      for (final address in [
      'http://example.com/connect/key',
      'ftp://example.com',
        'https://example.com?key=secret',
        'https://user:password@example.com',
        'https://example.com/#fragment',
      ]) {
        expect(() => ApiConfig.normalize(address), throwsFormatException);
      }
      expect(
        ApiConfig.normalize('192.168.1.10:8000'),
        'http://192.168.1.10:8000',
      );
    },
  );
}

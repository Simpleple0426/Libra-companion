import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';

class MovieRoomException implements Exception {
  const MovieRoomException(this.message);
  final String message;
  @override
  String toString() => message;
}

class MovieRoomApi {
  final http.Client? _client;
  final Set<http.Client> _active = {};
  bool _closed = false;
  MovieRoomApi({http.Client? client}) : _client = client;
  void close() {
    _closed = true;
    _client?.close();
    for (final client in _active.toList()) {
      client.close();
    }
    _active.clear();
  }

  Future<http.Response> _send(
    Uri uri,
    String path,
    Map<String, dynamic>? body,
  ) async {
    if (_closed) throw const MovieRoomException('电影室已关闭，请重新进入');
    // A polling request must not reuse a connection closed by the server or VPN.
    // Keep each request independent, including concurrent chat and history reads.
    final client = _client ?? http.Client();
    _active.add(client);
    try {
      const headers = {
        'Content-Type': 'application/json',
        'Connection': 'close',
      };
      return await (body == null
              ? client.get(uri, headers: headers)
              : client.post(uri, headers: headers, body: jsonEncode(body)))
          .timeout(Duration(seconds: path == '/chat' ? 600 : 25));
    } finally {
      _active.remove(client);
      if (_client == null) client.close();
    }
  }

  Future<Map<String, dynamic>> request(
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    final uri = Uri.parse('${ApiConfig.baseUrl}/movie-room$path');
    http.Response? response;
    for (var attempt = 0; attempt < (body == null ? 2 : 1); attempt++) {
      try {
        response = await _send(uri, path, body);
        break;
      } on TimeoutException {
        if (body == null && attempt == 0 && !_closed) continue;
        throw const MovieRoomException('连接超时，请检查网络后重试');
      } on http.ClientException {
        if (body == null && attempt == 0 && !_closed) continue;
        throw const MovieRoomException('连接中断，请检查网络后重试');
      }
    }
    if (response == null ||
        response.statusCode < 200 ||
        response.statusCode >= 300) {
      throw MovieRoomException(
        '电影室服务暂时异常（${response?.statusCode ?? "未知"}），请稍后重试',
      );
    }
    try {
      return Map<String, dynamic>.from(
        jsonDecode(utf8.decode(response.bodyBytes)) as Map,
      );
    } catch (_) {
      throw const MovieRoomException('电影室返回的内容无法读取，请稍后重试');
    }
  }
}

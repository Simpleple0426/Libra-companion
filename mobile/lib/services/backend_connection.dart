import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/api_config.dart';

/// Checks connectivity without changing the currently saved connection.
Future<String> verifyBackendConnection(
  String address,
  http.Client client,
) async {
  final normalized = ApiConfig.normalize(address);
  final response = await client
      .get(Uri.parse('$normalized/'))
      .timeout(const Duration(seconds: 15));
  if (response.statusCode == 401 || response.statusCode == 403) {
    throw const FormatException('访问未授权，请粘贴包含随机密钥的完整私人地址');
  }
  if (response.statusCode != 200) {
    throw const FormatException('服务器暂时不可用，请检查后端是否正在运行');
  }
  dynamic body;
  try {
    body = jsonDecode(response.body);
  } catch (_) {
    throw const FormatException('该地址尚未接通 Libra 后端');
  }
  if (body is! Map || body['message'] != 'Libra Companion backend is running') {
    throw const FormatException('该地址尚未接通 Libra 后端');
  }
  return normalized;
}

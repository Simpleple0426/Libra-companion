import 'package:shared_preferences/shared_preferences.dart';

class ApiConfig {
  ApiConfig._();

  static const _storageKey = 'libra_api_base_url';
  static const _connectionVersionKey = 'libra_connection_version';
  static const _buildTimeUrl = String.fromEnvironment(
    'LIBRA_API_BASE_URL',
    defaultValue: '',
  );

  static String _baseUrl = _buildTimeUrl;
  static bool _confirmed = false;

  static String get baseUrl => _baseUrl;
  static bool get isConfigured => _confirmed && _baseUrl.isNotEmpty;

  static Future<void> initialize() async {
    final preferences = await SharedPreferences.getInstance();
    _baseUrl = _buildTimeUrl;
    _confirmed = preferences.getInt(_connectionVersionKey) == 2;
    final saved = preferences.getString(_storageKey)?.trim();
    if (saved != null && saved.isNotEmpty) {
      try {
        _baseUrl = normalize(saved);
      } on FormatException {
        _confirmed = false;
      }
    }
  }

  static Future<void> saveBaseUrl(String value) async {
    final normalized = normalize(value);
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString(_storageKey, normalized);
    await preferences.setInt(_connectionVersionKey, 2);
    _baseUrl = normalized;
    _confirmed = true;
  }

  static String normalize(String value) {
    var url = value.trim();
    if (!url.contains('://')) {
      url = 'http://$url';
    }
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !{'http', 'https'}.contains(uri.scheme) ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw const FormatException('请输入完整的 HTTP 或 HTTPS 地址');
    }
    if (uri.path.startsWith('/connect/') && uri.scheme != 'https') {
      throw const FormatException('私人连接地址必须使用 HTTPS');
    }
    return url.replaceFirst(RegExp(r'/+$'), '');
  }
}

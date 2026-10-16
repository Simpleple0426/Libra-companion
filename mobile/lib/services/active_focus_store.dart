import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// A checkpoint survives Android reclaiming the app while the screen is locked.
class ActiveFocusStore {
  static const _key = 'active_focus_session_v1';
  static Future<void> _pending = Future<void>.value();

  Future<Map<String, dynamic>?> load() async {
    await _pending;
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return null;
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  Future<void> save(Map<String, dynamic>? value) {
    final encoded = value == null ? null : jsonEncode(value);
    final write = _pending.then((_) async {
      final prefs = await SharedPreferences.getInstance();
      if (encoded == null) {
        await prefs.remove(_key);
      } else {
        await prefs.setString(_key, encoded);
      }
    });
    _pending = write.catchError((Object _) {});
    return write;
  }
}

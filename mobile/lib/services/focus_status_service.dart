import 'package:shared_preferences/shared_preferences.dart';

/// Serializes status changes and preserves ownership across process recreation.
class FocusStatusService {
  FocusStatusService(this.writeStatus);

  final Future<void> Function(String) writeStatus;
  Future<void> _pending = Future<void>.value();
  static const _active = 'focus_status_active';
  static const _previous = 'focus_status_previous';

  Future<void> _enqueue(Future<void> Function(SharedPreferences) action) {
    final result = _pending.then((_) async {
      await action(await SharedPreferences.getInstance());
    });
    _pending = result.catchError((Object _) {});
    return result;
  }

  Future<void> start() => _enqueue((prefs) async {
    if (prefs.getBool(_active) == true) return;
    await prefs.setString(
      _previous,
      prefs.getString('home_user_status') ?? '设置状态',
    );
    await prefs.setBool(_active, true);
    await writeStatus('专注中');
  });

  Future<void> end() => _enqueue((prefs) async {
    final previous = prefs.getString(_previous);
    if (previous != null && prefs.getString('home_user_status') == '专注中') {
      await writeStatus(previous);
    }
    await prefs.remove(_previous);
    await prefs.remove(_active);
  });

  Future<void> selectManually(String status) => _enqueue((prefs) async {
    await prefs.remove(_previous);
    await writeStatus(status);
  });
}

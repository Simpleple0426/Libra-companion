import 'libra_api.dart';

class AppDurationStore {
  AppDurationStore(this._api);

  final LibraApi _api;
  DateTime? _sessionStartedAt;

  void startSession([DateTime? now]) {
    _sessionStartedAt ??= now ?? DateTime.now();
  }

  Future<void> endSession([DateTime? now]) async {
    final startedAt = _sessionStartedAt;
    if (startedAt == null) return;
    final endedAt = now ?? DateTime.now();
    _sessionStartedAt = null;
    if (!endedAt.isAfter(startedAt)) return;

    await _saveInterval(startedAt, endedAt);
  }

  Future<void> checkpoint([DateTime? now]) async {
    final startedAt = _sessionStartedAt;
    if (startedAt == null) return;
    final checkpointAt = now ?? DateTime.now();
    if (!checkpointAt.isAfter(startedAt)) return;
    _sessionStartedAt = checkpointAt;
    await _saveInterval(startedAt, checkpointAt);
  }

  Future<void> _saveInterval(DateTime startedAt, DateTime endedAt) async {
    var cursor = startedAt;
    while (cursor.isBefore(endedAt)) {
      final nextDay = DateTime(cursor.year, cursor.month, cursor.day + 1);
      final segmentEnd = endedAt.isBefore(nextDay) ? endedAt : nextDay;
      final key = _key(cursor);
      final previous = await _api.getMobileState(key);
      final milliseconds = previous is num ? previous.toInt() : 0;
      await _api.setMobileState(
        key,
        milliseconds + segmentEnd.difference(cursor).inMilliseconds,
      );
      cursor = segmentEnd;
    }
  }

  Future<Duration> durationForDay(DateTime day) async {
    final stored = await _api.getMobileState(_key(day));
    var milliseconds = stored is num ? stored.toInt() : 0;
    final startedAt = _sessionStartedAt;
    final now = DateTime.now();
    if (startedAt != null && _sameDay(startedAt, day)) {
      final end = _sameDay(now, day)
          ? now
          : DateTime(day.year, day.month, day.day + 1);
      if (end.isAfter(startedAt)) {
        milliseconds += end.difference(startedAt).inMilliseconds;
      }
    }
    return Duration(milliseconds: milliseconds);
  }

  Future<Duration> todayDuration() => durationForDay(DateTime.now());

  String _key(DateTime value) =>
      'libra_app_usage_ms_${value.year.toString().padLeft(4, '0')}-'
      '${value.month.toString().padLeft(2, '0')}-'
      '${value.day.toString().padLeft(2, '0')}';

  bool _sameDay(DateTime first, DateTime second) =>
      first.year == second.year &&
      first.month == second.month &&
      first.day == second.day;
}

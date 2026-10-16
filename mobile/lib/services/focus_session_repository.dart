import 'focus_stats_store.dart';
import 'libra_api.dart';

/// Persistence boundary for focus sessions.
///
/// The UI and session controller do not need to know whether records came
/// from the device or the backend. Local data wins when the same session is
/// present in both places, and failed network syncs never lose local data.
class FocusSessionRepository {
  FocusSessionRepository({FocusStatsStore? store, LibraApi? api})
    : _store = store ?? FocusStatsStore(),
      _api = api ?? LibraApi();

  final FocusStatsStore _store;
  final LibraApi _api;

  Future<List<FocusSession>> loadThisMonth() async {
    final localSessions = await _store.load();
    final now = DateTime.now();
    return localSessions.where((session) {
      final local = session.startedAt.toLocal();
      return local.year == now.year && local.month == now.month;
    }).toList()..sort((a, b) => a.startedAt.compareTo(b.startedAt));
  }

  Future<void>? _sync;
  Future<void> sync() =>
      _sync ??= _syncRemote().whenComplete(() => _sync = null);

  Future<void> _syncRemote() async {
    try {
      final localSessions = await _store.load();
      await _api.uploadFocusSessions(localSessions);
      final remoteSessions = await _api.getFocusSessions(
        days: DateTime.now().day,
      );
      await _store.merge(remoteSessions);
    } catch (_) {
      // Local statistics stay available offline; the next visit retries sync.
    }
  }

  Future<void> save(FocusSession session) async {
    await _store.add(session);
  }

  void close() => _api.close();
}

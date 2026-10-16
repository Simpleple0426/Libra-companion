import 'dart:async';

import 'package:flutter/foundation.dart';

import '../services/app_usage_service.dart';
import '../services/active_focus_store.dart';
import '../services/focus_session_repository.dart';
import '../services/focus_stats_store.dart';
import '../services/display_names.dart';

typedef FocusEventCallback = Future<void> Function(String description);

/// Owns the non-visual state of a study-room focus session.
class StudyRoomController extends ChangeNotifier {
  StudyRoomController({
    required this.focusEventSink,
    FocusSessionRepository? repository,
    AppUsageService? usageService,
    ActiveFocusStore? activeStore,
    DateTime Function()? now,
    this.tickInterval = const Duration(seconds: 1),
    this.onSessionStarted,
    this.onSessionTick,
    this.onSessionEnded,
  }) : _repository = repository ?? FocusSessionRepository(),
       _usageService = usageService ?? AppUsageService(),
       _activeStore = activeStore ?? ActiveFocusStore(),
       _now = now ?? DateTime.now;

  final FocusEventCallback focusEventSink;
  final FocusSessionRepository _repository;
  final AppUsageService _usageService;
  final ActiveFocusStore _activeStore;
  final DateTime Function() _now;
  @visibleForTesting
  final Duration tickInterval;
  final Future<void> Function()? onSessionStarted;
  final void Function()? onSessionTick;
  final Future<void> Function()? onSessionEnded;

  Timer? _timer;
  int _remainingSeconds = 0;
  int _elapsedSeconds = 0;
  int _plannedSeconds = 0;
  DateTime? _startedAt;
  DateTime? _lastAccountingAt;
  bool _countUp = false;
  String _content = '';
  bool _finishing = false;
  bool _paused = false;
  bool _statsLoading = true;
  bool _disposed = false;
  List<FocusSession> _sessions = const [];

  bool get isFocusing => _startedAt != null;
  bool get paused => _paused;
  bool get statsLoading => _statsLoading;
  String get content => _content;
  List<FocusSession> get sessions => _sessions;

  Future<void> checkpoint() async {
    if (!isFocusing || _finishing) return;
    _syncElapsedWithClock();
    try {
      await _activeStore.save({
        'startedAt': _startedAt!.toIso8601String(),
        'accountedAt': _lastAccountingAt!.toIso8601String(),
        'elapsed': _elapsedSeconds,
        'planned': _plannedSeconds,
        'countUp': _countUp,
        'paused': _paused,
        'content': _content,
      });
    } catch (error) {
      debugPrint('Saving active focus session failed: $error');
    }
  }

  Future<void> restore() async {
    final saved = await _activeStore.load();
    if (_disposed || isFocusing || saved == null) return;
    final started = DateTime.tryParse(saved['startedAt'] as String? ?? '');
    final accounted = DateTime.tryParse(saved['accountedAt'] as String? ?? '');
    if (started == null ||
        accounted == null ||
        saved['elapsed'] is! int ||
        saved['planned'] is! int) {
      return;
    }
    _startedAt = started;
    _lastAccountingAt = accounted;
    _elapsedSeconds = saved['elapsed'] as int;
    _plannedSeconds = saved['planned'] as int;
    _countUp = saved['countUp'] == true;
    _paused = saved['paused'] == true;
    _content = saved['content'] as String? ?? '';
    _remainingSeconds = (_plannedSeconds - _elapsedSeconds).clamp(
      0,
      _plannedSeconds,
    );
    _syncElapsedWithClock();
    if (!_countUp && _remainingSeconds == 0) {
      await finish();
      return;
    }
    notifyListeners();
    unawaited(_setKeepScreenOn(true));
    if (onSessionStarted != null) unawaited(onSessionStarted!());
    _timer = Timer.periodic(tickInterval, (_) => _tick());
  }

  String get timerLabel {
    final displayedSeconds = _countUp ? _elapsedSeconds : _remainingSeconds;
    final minutes = (displayedSeconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (displayedSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  Future<void> refreshStats() async {
    final sessions = await _repository.loadThisMonth();
    if (_disposed) return;
    _sessions = sessions;
    _statsLoading = false;
    notifyListeners();
    unawaited(_syncStats());
  }

  Future<void> _syncStats() async {
    await _repository.sync();
    if (_disposed) return;
    final sessions = await _repository.loadThisMonth();
    if (_disposed) return;
    _sessions = sessions;
    notifyListeners();
  }

  void startCountdown(int minutes, String content) {
    _begin(plannedSeconds: minutes * 60, countUp: false, content: content);
  }

  void startCountUp(String content) {
    _begin(plannedSeconds: 0, countUp: true, content: content);
  }

  void _begin({
    required int plannedSeconds,
    required bool countUp,
    required String content,
  }) {
    if (_finishing) return;
    _timer?.cancel();
    _plannedSeconds = plannedSeconds;
    _remainingSeconds = plannedSeconds;
    _elapsedSeconds = 0;
    _countUp = countUp;
    _content = content.trim().isEmpty ? '自由学习' : content.trim();
    _startedAt = _now();
    _lastAccountingAt = _startedAt;
    _paused = false;
    unawaited(checkpoint());
    notifyListeners();

    unawaited(_setKeepScreenOn(true));
    if (onSessionStarted != null) unawaited(onSessionStarted!());
    unawaited(focusEventSink('${DisplayNames.user}开始学习：$_content'));
    _timer = Timer.periodic(tickInterval, (_) => _tick());
  }

  void _tick() {
    if (_paused || _disposed || !isFocusing) return;
    onSessionTick?.call();
    _syncElapsedWithClock();
    if (!_countUp && _remainingSeconds <= 0) unawaited(finish());
  }

  void _syncElapsedWithClock() {
    if (_disposed || !isFocusing || _paused) return;
    final current = _now();
    final previous = _lastAccountingAt ?? current;
    final addedSeconds = current.difference(previous).inSeconds;
    if (addedSeconds <= 0) return;
    _lastAccountingAt = previous.add(Duration(seconds: addedSeconds));
    _elapsedSeconds += addedSeconds;
    if (!_countUp) _elapsedSeconds = _elapsedSeconds.clamp(0, _plannedSeconds);
    if (!_countUp) {
      _remainingSeconds = (_plannedSeconds - _elapsedSeconds).clamp(
        0,
        _plannedSeconds,
      );
    }
    notifyListeners();
  }

  void onAppResumed() {
    if (!isFocusing) return;
    unawaited(_setKeepScreenOn(true));
    _syncElapsedWithClock();
  }

  void togglePaused() {
    if (!isFocusing) return;
    if (!_paused) _syncElapsedWithClock();
    _paused = !_paused;
    _lastAccountingAt = _now();
    unawaited(checkpoint());
    notifyListeners();
  }

  void updateContent(String value) {
    if (!isFocusing) return;
    _content = value.trim().isEmpty ? '自由学习' : value.trim();
    unawaited(checkpoint());
    notifyListeners();
  }

  Future<void> finish() async {
    if (_finishing || _startedAt == null) return;
    _finishing = true;
    _syncElapsedWithClock();
    _timer?.cancel();
    try {
      await _activeStore.save(null);
    } catch (error) {
      _finishing = false;
      if (!_disposed) _timer = Timer.periodic(tickInterval, (_) => _tick());
      debugPrint('Clearing active focus session failed: $error');
      return;
    }

    final startedAt = _startedAt!;
    final elapsed = _elapsedSeconds;
    final content = _content;
    final timerMode = _countUp ? 'countup' : 'countdown';
    _startedAt = null;
    _lastAccountingAt = null;
    _plannedSeconds = 0;
    _remainingSeconds = 0;
    _elapsedSeconds = 0;
    _countUp = false;
    _content = '';
    _paused = false;
    if (!_disposed) notifyListeners();

    unawaited(_setKeepScreenOn(false));
    if (onSessionEnded != null) unawaited(onSessionEnded!());
    if (elapsed >= 10) {
      final minutes = (elapsed / 60).ceil();
      unawaited(
        focusEventSink('${DisplayNames.user}结束学习：$content，本次专注 $minutes 分钟'),
      );
      try {
        await _repository.save(
          FocusSession(
            startedAt: startedAt,
            seconds: elapsed,
            content: content,
            timerMode: timerMode,
          ),
        );
        await refreshStats();
      } catch (error, stackTrace) {
        debugPrint('Saving focus statistics failed: $error');
        debugPrintStack(stackTrace: stackTrace);
      }
    }
    _finishing = false;
  }

  Future<void> _setKeepScreenOn(bool enabled) async {
    try {
      await _usageService.setKeepScreenOn(enabled);
    } catch (error) {
      debugPrint('Keeping the focus screen awake failed: $error');
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    unawaited(_setKeepScreenOn(false));
    _repository.close();
    super.dispose();
  }
}

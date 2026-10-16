import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

class FocusSession {
  const FocusSession({
    required this.startedAt,
    required this.seconds,
    this.content = '',
    this.timerMode = 'countdown',
  });

  final DateTime startedAt;
  final int seconds;
  final String content;
  final String timerMode;

  String get sessionKey => '${startedAt.toUtc().toIso8601String()}-$seconds';

  Map<String, Object> toJson() => {
    'startedAt': startedAt.toIso8601String(),
    'seconds': seconds,
    'content': content,
    'timerMode': timerMode,
  };

  static FocusSession? fromJson(Object? value) {
    if (value is! Map<String, dynamic>) return null;
    final startedAt = DateTime.tryParse(value['startedAt'] as String? ?? '');
    final seconds = value['seconds'];
    if (startedAt == null || seconds is! int || seconds <= 0) return null;
    return FocusSession(
      startedAt: startedAt,
      seconds: seconds,
      content: value['content'] as String? ?? '',
      timerMode: value['timerMode'] == 'countup' ? 'countup' : 'countdown',
    );
  }

  Map<String, Object> toApiJson() => {
    'session_key': sessionKey,
    'started_at': startedAt.toIso8601String(),
    'duration_seconds': seconds,
    'content': content,
    'timer_mode': timerMode,
  };

  static FocusSession? fromApiJson(Object? value) {
    if (value is! Map<String, dynamic>) return null;
    final startedAt = DateTime.tryParse(value['started_at'] as String? ?? '');
    final seconds = value['duration_seconds'];
    if (startedAt == null || seconds is! int || seconds <= 0) return null;
    return FocusSession(
      startedAt: startedAt,
      seconds: seconds,
      content: value['content'] as String? ?? '',
      timerMode: value['timer_mode'] == 'countup' ? 'countup' : 'countdown',
    );
  }
}

class FocusStatsStore {
  FocusStatsStore({File? file}) : _storageFile = file;

  final File? _storageFile;

  Future<File> _file() async {
    if (_storageFile != null) return _storageFile;
    final directory = await getApplicationDocumentsDirectory();
    return File(
      '${directory.path}${Platform.pathSeparator}focus_sessions.json',
    );
  }

  Future<List<FocusSession>> load() async {
    try {
      final file = await _file();
      if (!await file.exists()) return const [];
      final values = jsonDecode(await file.readAsString());
      if (values is! List) return const [];
      return values
          .map(FocusSession.fromJson)
          .whereType<FocusSession>()
          .toList();
    } catch (_) {
      return const [];
    }
  }

  // Serialize read/merge/write across instances so a background download
  // cannot overwrite a session that has just finished on the phone.
  static Future<void> _writes = Future<void>.value();

  Future<void> add(FocusSession session) => merge([session]);

  Future<void> merge(List<FocusSession> incoming) {
    final write = _writes.then((_) => _merge(incoming));
    _writes = write.catchError((Object _) {});
    return write;
  }

  Future<void> _merge(List<FocusSession> incoming) async {
    final sessions = <String, FocusSession>{
      for (final session in incoming) session.sessionKey: session,
      for (final session in await load()) session.sessionKey: session,
    };
    final cutoff = DateTime.now().subtract(const Duration(days: 90));
    final retained = sessions.values
        .where((item) => item.startedAt.isAfter(cutoff))
        .map((item) => item.toJson())
        .toList();
    await (await _file()).writeAsString(jsonEncode(retained), flush: true);
  }
}

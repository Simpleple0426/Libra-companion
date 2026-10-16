import 'dart:convert';
import 'dart:io';

import 'package:exif/exif.dart';
import 'package:geocoding/geocoding.dart';
import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import '../models/chat_message.dart';
import '../models/library_book.dart';
import '../models/app_usage_event.dart';
import '../models/calendar_entry.dart';
import '../models/memory_item.dart';
import '../models/dream_reading.dart';
import '../models/letter.dart';
import '../models/timeline_event.dart';
import 'focus_stats_store.dart';
import 'libra_schedule_day.dart';

class LibraSleepStatus {
  const LibraSleepStatus({required this.sleeping, this.sleepUntil});

  final bool sleeping;
  final DateTime? sleepUntil;

  factory LibraSleepStatus.fromJson(Map<String, dynamic> json) {
    final rawUntil = json['sleep_until'] as String?;
    return LibraSleepStatus(
      sleeping: json['sleeping'] == true,
      sleepUntil: rawUntil == null ? null : DateTime.tryParse(rawUntil),
    );
  }
}

class LifeActivityStatus {
  const LifeActivityStatus({
    required this.id,
    required this.kind,
    required this.status,
    required this.progress,
    this.total,
    required this.target,
    required this.targetName,
  });

  final String id;
  final String kind;
  final String status;
  final num progress;
  final num? total;
  final String target;
  final String targetName;

  factory LifeActivityStatus.fromJson(Map<String, dynamic> json) =>
      LifeActivityStatus(
        id: '${json['id'] ?? ''}',
        kind: '${json['kind'] ?? ''}',
        status: '${json['status'] ?? ''}',
        progress: json['progress'] as num? ?? 0,
        total: json['total'] as num?,
        target: '${json['target'] ?? ''}',
        targetName: '${json['target_name'] ?? json['target'] ?? ''}',
      );
}

class LifeSystemStatus {
  const LifeSystemStatus({
    required this.mode,
    required this.status,
    required this.revision,
    required this.place,
    required this.placeName,
    required this.sleepStatus,
    this.activity,
    this.coarseActivity,
    this.companionSessionId,
    this.schedule = const [],
  });

  final String mode;
  final String status;
  final int revision;
  final String place;
  final String placeName;
  final String sleepStatus;
  final LifeActivityStatus? activity;
  final LifeCoarseActivity? coarseActivity;
  final String? companionSessionId;
  final List<LifeScheduleEntry> schedule;

  bool get ready => mode == 'enabled' && status == 'ready';

  factory LifeSystemStatus.fromJson(Map<String, dynamic> json) {
    final rawActivity = json['activity'];
    final rawCoarseActivity = json['coarse_activity'];
    final rawSleep = json['sleep'];
    return LifeSystemStatus(
      mode: '${json['mode'] ?? ''}',
      status: '${json['status'] ?? ''}',
      revision: (json['revision'] as num?)?.toInt() ?? 0,
      place: '${json['place'] ?? ''}',
      placeName: '${json['place_name'] ?? json['place'] ?? ''}',
      sleepStatus: rawSleep is Map ? '${rawSleep['status'] ?? ''}' : '',
      companionSessionId: json['companion'] is Map
          ? json['companion']['id'] as String?
          : null,
      activity: rawActivity is Map
          ? LifeActivityStatus.fromJson(Map<String, dynamic>.from(rawActivity))
          : null,
      coarseActivity: rawCoarseActivity is Map
          ? LifeCoarseActivity.fromJson(
              Map<String, dynamic>.from(rawCoarseActivity),
            )
          : null,
      schedule: LifeScheduleEntry.parse(json),
    );
  }
}

class LifeCoarseActivity {
  const LifeCoarseActivity({
    required this.id,
    required this.kind,
    required this.title,
    this.startAt,
    this.endAt,
  });

  final String id;
  final String kind;
  final String title;
  final DateTime? startAt;
  final DateTime? endAt;

  factory LifeCoarseActivity.fromJson(Map<String, dynamic> json) =>
      LifeCoarseActivity(
        id: '${json['id'] ?? ''}',
        kind: '${json['kind'] ?? ''}',
        title: '${json['title'] ?? ''}',
        startAt: DateTime.tryParse('${json['start_at'] ?? ''}')?.toLocal(),
        endAt: DateTime.tryParse('${json['end_at'] ?? ''}')?.toLocal(),
      );
}

class LifeScheduleEntry {
  const LifeScheduleEntry({
    required this.id,
    required this.title,
    required this.kind,
    required this.place,
    required this.placeId,
    required this.start,
    required this.end,
    required this.status,
    required this.detailed,
    this.note = '',
    this.openEnded = false,
    this.progress,
  });
  final String id, title, kind, place, placeId, status, note;
  final DateTime start, end;
  final bool detailed;
  final bool openEnded;
  final num? progress;

  static List<LifeScheduleEntry> parse(Map<String, dynamic> json) {
    final coarse = json['daily_agenda'];
    final fine = json['fine_agenda'];
    final plans = fine is Map && fine['plans'] is List
        ? fine['plans'] as List
        : const [];
    final items = coarse is Map && coarse['items'] is List
        ? coarse['items'] as List
        : const [];
    final result = <LifeScheduleEntry>[];
    void add(Map row, bool detailed, String note) {
      final start = DateTime.tryParse('${row['start_at'] ?? ''}');
      final end = DateTime.tryParse('${row['end_at'] ?? ''}');
      if (start == null || end == null) return;
      result.add(
        LifeScheduleEntry(
          id: '${row['id'] ?? ''}',
          kind:
              row['activity'] == 'user_time' ||
                  (row['constraints'] is Map &&
                      row['constraints']['required_routine'] == 'user_time')
              ? 'user_time'
              : '${row['state_type'] ?? row['kind'] ?? ''}',
          title:
              !detailed &&
                  '${row['coarse_intent'] ?? row['intent'] ?? ''}'
                      .trim()
                      .isNotEmpty
              ? '${row['coarse_intent'] ?? row['intent']}'
              : '${row['title'] ?? ''}',
          place: '${row['coarse_place_name'] ?? row['place_name'] ?? ''}',
          placeId:
              '${row['coarse_place'] ?? row['place'] ?? row['location_id'] ?? ''}',
          start: start.toLocal(),
          end: end.toLocal(),
          status: '${row['status'] ?? 'planned'}',
          detailed: detailed,
          openEnded: row['open_ended'] == true,
          note: note,
          progress: row['progress'] is num ? row['progress'] as num : null,
        ),
      );
    }

    for (final item in items.whereType<Map>()) {
      final matching = plans
          .whereType<Map>()
          .where((p) => p['parent_id'] == item['id'])
          .toList();
      final plan = matching.isEmpty ? null : matching.last;
      add(
        item,
        false,
        plan != null && plan['status'] != 'ready'
            ? '${plan['reason'] ?? '等待细化'}'
            : '',
      );
      for (final saved in matching) {
        final blocks = saved['blocks'];
        if (blocks is! List) continue;
        for (final block in blocks.whereType<Map>()) {
          final progress = block['progress'];
          final note = block['kind'] == 'watching'
              ? '模拟观看进度${progress is num ? ' · ${(progress / 60).floor()} 分钟' : ''}'
              : block['reading_mode'] == 'knowledge_review'
              ? '作品回顾 · 非原文'
              : block['kind'] == 'reading'
              ? '独立阅读进度${progress is num ? ' · $progress 字符' : ''}'
              : block['kind'] == 'work'
              ? '模拟工作${progress is num ? ' · $progress/2 阶段' : ''}'
              : '';
          add(block, true, note);
        }
      }
    }
    final currentParents = items.whereType<Map>().map((i) => i['id']).toSet();
    for (final plan in plans.whereType<Map>()) {
      if (currentParents.contains(plan['parent_id'])) continue;
      final blocks = plan['blocks'];
      if (blocks is! List) continue;
      for (final block in blocks.whereType<Map>()) {
        add(
          {...block, 'title': '调整前 · ${block['title'] ?? ''}'},
          true,
          '保留调整记录',
        );
      }
    }
    return result;
  }
}

class StickerCatalogItem {
  const StickerCatalogItem({
    required this.id,
    required this.meaning,
    required this.mediaUrl,
  });

  final String id;
  final String meaning;
  final String mediaUrl;

  factory StickerCatalogItem.fromJson(Map<String, dynamic> json) {
    return StickerCatalogItem(
      id: json['id'] as String? ?? '',
      meaning: json['meaning'] as String? ?? '表情',
      mediaUrl: json['media_url'] as String? ?? '',
    );
  }
}

class CompanionStats {
  const CompanionStats({
    required this.todayMessageCount,
    required this.lastChatAt,
  });

  final int todayMessageCount;
  final DateTime? lastChatAt;

  factory CompanionStats.fromJson(Map<String, dynamic> json) {
    final rawLastChatAt = json['last_chat_at'] as String?;
    return CompanionStats(
      todayMessageCount: json['today_message_count'] as int? ?? 0,
      lastChatAt: rawLastChatAt == null
          ? null
          : DateTime.tryParse(rawLastChatAt),
    );
  }
}

class WorkCalendarDay {
  const WorkCalendarDay({
    required this.date,
    required this.dayType,
    required this.restType,
    required this.isAdjusted,
    required this.holidayPeriod,
  });

  final DateTime date;
  final String dayType;
  final String? restType;
  final bool isAdjusted;
  final String? holidayPeriod;

  bool get isMakeupWorkday => dayType == 'workday' && isAdjusted;
  bool get isHolidayLeave =>
      dayType == 'rest_day' && restType == 'holiday_leave';

  factory WorkCalendarDay.fromJson(Map<String, dynamic> json) {
    return WorkCalendarDay(
      date: DateTime.parse(json['date'] as String),
      dayType: json['day_type'] as String,
      restType: json['rest_type'] as String?,
      isAdjusted: json['is_adjusted'] == true,
      holidayPeriod: json['holiday_period'] as String?,
    );
  }
}

class ReadingBook {
  const ReadingBook({
    required this.bookId,
    required this.title,
    required this.author,
    required this.chunkCount,
    required this.currentChunkId,
  });

  final String bookId;
  final String title;
  final String author;
  final int chunkCount;
  final String currentChunkId;

  factory ReadingBook.fromJson(Map<String, dynamic> json) => ReadingBook(
    bookId: json['book_id'] as String? ?? '',
    title: json['title'] as String? ?? '',
    author: json['author'] as String? ?? '',
    chunkCount: json['chunk_count'] as int? ?? 0,
    currentChunkId: json['current_chunk_id'] as String? ?? '',
  );
}

class ReadingChunk {
  const ReadingChunk({
    required this.chunkId,
    required this.index,
    required this.total,
    required this.title,
    required this.preview,
    this.sectionIndex,
  });

  final String chunkId;
  final int index;
  final int total;
  final String title;
  final String preview;
  final int? sectionIndex;

  factory ReadingChunk.fromJson(Map<String, dynamic> json) => ReadingChunk(
    chunkId: json['chunk_id'] as String? ?? '',
    index: json['index'] as int? ?? 0,
    total: json['total'] as int? ?? 0,
    title: json['title'] as String? ?? '',
    preview: json['preview'] as String? ?? '',
    sectionIndex: json['section_index'] as int?,
  );
}

class ReadingSection {
  const ReadingSection({required this.title, required this.chunks});
  final String title;
  final List<ReadingSectionChunk> chunks;

  factory ReadingSection.fromJson(Map<String, dynamic> json) => ReadingSection(
    title: json['title'] as String? ?? '',
    chunks: (json['chunks'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(ReadingSectionChunk.fromJson)
        .toList(),
  );
}

class ReadingSectionChunk {
  const ReadingSectionChunk({
    required this.chunkId,
    required this.index,
    required this.title,
    required this.preview,
  });
  final String chunkId;
  final int index;
  final String title;
  final String preview;

  factory ReadingSectionChunk.fromJson(Map<String, dynamic> json) =>
      ReadingSectionChunk(
        chunkId: json['chunk_id'] as String? ?? '',
        index: json['index'] as int? ?? 0,
        title: json['title'] as String? ?? '',
        preview: json['preview'] as String? ?? '',
      );
}

class ChatReplyException implements Exception {
  const ChatReplyException();

  @override
  String toString() => '暂时未能生成回复';
}

class LibraApi {
  LibraApi({http.Client? client, http.Client Function()? pollingClientFactory})
    : _client = client ?? http.Client(),
      _pollingClientFactory =
          pollingClientFactory ??
          (client == null ? http.Client.new : () => client),
      _ownsPollingClients = client == null || pollingClientFactory != null;

  final http.Client _client;
  final http.Client Function() _pollingClientFactory;
  final bool _ownsPollingClients;

  Future<http.Response> _pollGet(Uri uri, Duration timeout) async {
    // Closing each read also cancels timed-out sockets, leaving the next poll
    // independent of the long-running chat POST and broken keep-alive sockets.
    final client = _pollingClientFactory();
    try {
      return await client
          .get(
            uri,
            headers: const {'Connection': 'close', 'Cache-Control': 'no-cache'},
          )
          .timeout(timeout);
    } finally {
      if (_ownsPollingClients) client.close();
    }
  }

  Uri _uri(String path) => Uri.parse('${ApiConfig.baseUrl}$path');

  Future<DreamReadingBatch> getMemoryReading({
    String? level,
    String kind = 'reviews',
    int offset = 0,
    DateTime? date,
  }) async {
    final uri = _uri('/memory/reading').replace(
      queryParameters: {
        'kind': kind,
        'level': ?level,
        'offset': '$offset',
        'limit': '30',
        if (date != null)
          'date':
              '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}',
      },
    );
    final response = await _client
        .get(uri)
        .timeout(const Duration(seconds: 20));
    return DreamReadingBatch.fromJson(_decode(response));
  }

  Future<List<ReadingBook>> getReadingBooks() async {
    final response = await _client
        .get(_uri('/reading/books'))
        .timeout(const Duration(seconds: 20));
    final values = _decode(response)['books'];
    if (values is! List) return const [];
    return values
        .whereType<Map<String, dynamic>>()
        .map(ReadingBook.fromJson)
        .toList();
  }

  Future<List<LibraryBook>> getBookLibrary() async {
    final response = await _client
        .get(_uri('/reading/library'))
        .timeout(const Duration(seconds: 20));
    final values = _decode(response)['books'] as List? ?? const [];
    return values
        .whereType<Map<String, dynamic>>()
        .map(LibraryBook.fromJson)
        .toList();
  }

  Future<void> addBookToLibrary({
    required String title,
    required String author,
  }) async {
    final response = await _client
        .post(
          _uri('/reading/library'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'title': title.trim(), 'author': author.trim()}),
        )
        .timeout(const Duration(seconds: 20));
    _decode(response);
  }

  Future<ReadingBook> importReadingBook({
    required List<int> bytes,
    required String filename,
    String? title,
  }) async {
    final request = http.MultipartRequest('POST', _uri('/reading/import'));
    request.fields['title'] = title ?? '';
    request.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );
    final streamed = await request.send().timeout(const Duration(minutes: 2));
    final response = await http.Response.fromStream(streamed);
    final data = _decode(response);
    return ReadingBook.fromJson(data['book'] as Map<String, dynamic>);
  }

  Future<ReadingChunk> getReadingChunk(String bookId) async {
    final response = await _client
        .get(_uri('/reading/books/$bookId/current'))
        .timeout(const Duration(seconds: 20));
    return ReadingChunk.fromJson(_decode(response));
  }

  Future<List<ReadingSection>> getReadingSections(String bookId) async {
    final response = await _client
        .get(_uri('/reading/books/$bookId/sections'))
        .timeout(const Duration(seconds: 20));
    final values = _decode(response)['sections'];
    if (values is! List) return const [];
    return values
        .whereType<Map<String, dynamic>>()
        .map(ReadingSection.fromJson)
        .toList();
  }

  Future<ReadingChunk> getReadingChunkById(
    String bookId,
    String chunkId,
  ) async {
    final response = await _client
        .get(_uri('/reading/books/$bookId/chunks/$chunkId'))
        .timeout(const Duration(seconds: 20));
    return ReadingChunk.fromJson(_decode(response));
  }

  Future<ReadingChunk> getReadingSection(
    String bookId,
    int sectionIndex,
  ) async {
    final response = await _client
        .get(_uri('/reading/books/$bookId/sections/$sectionIndex'))
        .timeout(const Duration(seconds: 20));
    return ReadingChunk.fromJson(_decode(response));
  }

  Future<List<ChatMessage>> discussReading(
    String bookId, {
    String message = '',
    bool advance = false,
    String chunkId = '',
    int? sectionIndex,
  }) async {
    final response = await _client
        .post(
          _uri('/reading/books/$bookId/discuss'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'message': message,
            'advance': advance,
            'chunk_id': chunkId,
            'section_index': ?sectionIndex,
          }),
        )
        .timeout(const Duration(minutes: 2));
    final data = _decode(response);
    final messages = data['messages'];
    if (messages is! List) return const [];
    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<LibraSleepStatus> getSleepStatus() async {
    final response = await _client
        .get(_uri('/sleep/status'))
        .timeout(const Duration(seconds: 15));
    return LibraSleepStatus.fromJson(_decode(response));
  }

  Future<LifeSystemStatus> getLifeSystemStatus() async {
    final response = await _client
        .get(_uri('/life-system/status'))
        .timeout(const Duration(seconds: 15));
    return LifeSystemStatus.fromJson(_decode(response));
  }

  Future<void> endCompanion(String sessionId) async {
    final response = await _client
        .post(
          _uri('/life-system/companion/${Uri.encodeComponent(sessionId)}/end'),
        )
        .timeout(const Duration(seconds: 15));
    _decode(response);
  }

  Future<List<TimelineEvent>> getLibraTimelineEvents([DateTime? day]) async {
    final selected = day ?? libraScheduleDay();
    final date =
        '${selected.year.toString().padLeft(4, '0')}-'
        '${selected.month.toString().padLeft(2, '0')}-'
        '${selected.day.toString().padLeft(2, '0')}';
    final response = await _client
        .get(
          _uri(
            '/timeline-events/libra/today',
          ).replace(queryParameters: {'date': date}),
        )
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['events'];
    if (values is! List) {
      throw const FormatException('左然动态数据格式不正确');
    }
    return values
        .whereType<Map<String, dynamic>>()
        .map(TimelineEvent.fromJson)
        .toList();
  }

  Future<int> syncUserTimelineEvents(List<AppUsageEvent> events) async {
    final response = await _client
        .post(
          _uri('/timeline-events/user/sync'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'events': events
                .where((event) => !event.description.contains('手机开始充电') && !event.description.contains('手机结束充电'))
                .map(
                  (event) => {
                    'occurred_at': event.timestamp.toIso8601String(),
                    'description': event.description,
                    'event_type': event.action,
                  },
                )
                .toList(),
          }),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['detail'] ?? data['error'] ?? '用户动态同步失败');
    }
    return (data['inserted'] as num?)?.toInt() ?? 0;
  }

  Future<List<AppUsageEvent>> getTodayUserTimelineEvents() async {
    final response = await _client
        .get(_uri('/timeline-events/user/today'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['events'];
    if (values is! List) return const [];
    return values.whereType<Map<String, dynamic>>().map((event) {
      return AppUsageEvent(
        timestamp: DateTime.parse('${event['occurred_at']}'),
        action: '${event['event_type'] ?? 'legacy'}',
        appName: '',
        customDescription: '${event['description'] ?? ''}',
      );
    }).toList();
  }

  Future<List<TimelineEvent>> getTodayLibraTimelineEvents() =>
      getLibraTimelineEvents();

  Future<CompanionStats> getCompanionStats() async {
    final response = await _client
        .get(_uri('/companion/stats'))
        .timeout(const Duration(seconds: 15));
    return CompanionStats.fromJson(_decode(response));
  }

  Future<LibraSleepStatus> wakeLibra() async {
    final response = await _client
        .post(_uri('/wake'))
        .timeout(const Duration(seconds: 15));
    return LibraSleepStatus.fromJson(_decode(response));
  }

  Future<LibraSleepStatus> sleepLibra() async {
    final response = await _client
        .post(_uri('/sleep'))
        .timeout(const Duration(seconds: 15));
    return LibraSleepStatus.fromJson(_decode(response));
  }

  Future<List<WorkCalendarDay>> getWorkCalendarMonth(DateTime month) async {
    final response = await _client
        .get(_uri('/work-calendar?year=${month.year}&month=${month.month}'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['days'];
    if (values is! List) {
      throw const FormatException('工作日历数据格式不正确');
    }
    return values
        .whereType<Map<String, dynamic>>()
        .map(WorkCalendarDay.fromJson)
        .toList();
  }

  Future<List<SharedMemoryItem>> getSharedMemories({String? type}) async {
    final suffix = type == null ? '' : '?memory_type=$type';
    final response = await _client
        .get(_uri('/shared-memories$suffix'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['shared_memories'];
    if (values is! List) throw const FormatException('没有返回时光记录');
    return values
        .whereType<Map<String, dynamic>>()
        .map(SharedMemoryItem.fromJson)
        .toList();
  }

  Future<SharedMemoryItem> publishMoment(String content) async {
    final response = await _client
        .post(
          _uri('/shared-memories/moments'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'content': content.trim()}),
        )
        .timeout(const Duration(seconds: 15));
    final value = _decode(response)['shared_memory'];
    if (value is! Map<String, dynamic>) throw Exception('动态发布失败');
    return SharedMemoryItem.fromJson(value);
  }

  Future<MemoryComment> commentOnMoment(int memoryId, String content) async {
    final response = await _client
        .post(
          _uri('/shared-memories/$memoryId/comments'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'content': content.trim()}),
        )
        .timeout(const Duration(seconds: 15));
    final value = _decode(response)['comment'];
    if (value is! Map<String, dynamic>) throw Exception('评论发送失败');
    return MemoryComment.fromJson(value);
  }

  Future<List<MemoryComment>> getMomentComments(int memoryId) async {
    final response = await _client
        .get(_uri('/shared-memories/$memoryId/comments'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['comments'];
    if (values is! List) throw const FormatException('没有返回动态评论');
    return values
        .whereType<Map<String, dynamic>>()
        .map(MemoryComment.fromJson)
        .toList();
  }

  Future<SharedMemoryItem> uploadSharedMemoryPhoto(String filePath) async {
    final metadata = await _readPhotoMetadata(filePath);
    final request = http.MultipartRequest(
      'POST',
      _uri('/shared-memories/photos'),
    );
    if (metadata.location.isNotEmpty) {
      request.fields['location_text'] = metadata.location;
    }
    if (metadata.takenAt.isNotEmpty) {
      request.fields['taken_at'] = metadata.takenAt;
    }
    request.files.add(await http.MultipartFile.fromPath('file', filePath));
    final response = await http.Response.fromStream(
      await request.send().timeout(const Duration(minutes: 2)),
    );
    final value = _decode(response)['shared_memory'];
    if (value is! Map<String, dynamic>) throw Exception('照片保存失败');
    return SharedMemoryItem.fromJson(value);
  }

  Future<void> saveChatImageToSharedMemories(int messageId) async {
    final response = await _client
        .post(
          _uri('/shared-memories/from-message'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'message_id': messageId}),
        )
        .timeout(const Duration(seconds: 15));
    _decode(response);
  }

  Future<void> deleteSharedMemory(int memoryId) async {
    final response = await _client
        .delete(_uri('/shared-memories/$memoryId'))
        .timeout(const Duration(seconds: 15));
    _decode(response);
  }

  Future<List<Letter>> getLetters() async {
    final response = await _client
        .get(_uri('/letters'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['letters'];
    if (values is! List) throw const FormatException('没有返回信件');
    return values
        .whereType<Map<String, dynamic>>()
        .map(Letter.fromJson)
        .toList();
  }

  Future<Letter> sendLetter({required String content, int? replyToId}) async {
    final response = await _client
        .post(
          _uri('/letters'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'content': content, 'reply_to_id': ?replyToId}),
        )
        .timeout(const Duration(seconds: 15));
    final value = _decode(response)['letter'];
    if (value is! Map<String, dynamic>) throw Exception('信件寄送失败');
    return Letter.fromJson(value);
  }

  Future<Letter> markLetterRead(int letterId) async {
    final response = await _client
        .post(_uri('/letters/$letterId/read'))
        .timeout(const Duration(seconds: 15));
    final value = _decode(response)['letter'];
    if (value is! Map<String, dynamic>) throw Exception('信件状态更新失败');
    return Letter.fromJson(value);
  }

  Future<Letter> setLetterFavorite(int letterId, bool favorite) async {
    final response = await _client
        .patch(
          _uri('/letters/$letterId/favorite'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'favorite': favorite}),
        )
        .timeout(const Duration(seconds: 15));
    final value = _decode(response)['letter'];
    if (value is! Map<String, dynamic>) throw Exception('收藏状态更新失败');
    return Letter.fromJson(value);
  }

  Future<SharedMemoryItem> updateSharedMemoryLocation(
    int memoryId,
    String location,
  ) async {
    final response = await _client
        .patch(
          _uri('/shared-memories/$memoryId/location'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'location_text': location.trim()}),
        )
        .timeout(const Duration(seconds: 15));
    final value = _decode(response)['shared_memory'];
    if (value is! Map<String, dynamic>) throw Exception('地点保存失败');
    return SharedMemoryItem.fromJson(value);
  }

  Future<({String location, String takenAt})> _readPhotoMetadata(
    String filePath,
  ) async {
    try {
      final tags = await readExifFromBytes(await File(filePath).readAsBytes());
      final latitude = _gpsCoordinate(tags['GPS GPSLatitude']);
      final longitude = _gpsCoordinate(tags['GPS GPSLongitude']);
      final latRef = tags['GPS GPSLatitudeRef']?.printable.toUpperCase() ?? '';
      final lngRef = tags['GPS GPSLongitudeRef']?.printable.toUpperCase() ?? '';
      var location = '';
      if (latitude != null && longitude != null) {
        final lat = latRef == 'S' ? -latitude : latitude;
        final lng = lngRef == 'W' ? -longitude : longitude;
        final places = await Geocoding().placemarkFromCoordinates(lat, lng);
        if (places.isNotEmpty) {
          final place = places.first;
          final parts = <String>[
            if ((place.administrativeArea ?? '').isNotEmpty)
              place.administrativeArea!,
            if ((place.locality ?? '').isNotEmpty &&
                place.locality != place.administrativeArea)
              place.locality!,
          ];
          location = parts.join(' · ');
        }
      }
      final rawDate =
          tags['EXIF DateTimeOriginal']?.printable ??
          tags['Image DateTime']?.printable ??
          '';
      final normalized = rawDate.replaceFirstMapped(
        RegExp(r'^(\d{4}):(\d{2}):(\d{2})'),
        (match) => '${match[1]}-${match[2]}-${match[3]}',
      );
      return (
        location: location,
        takenAt: DateTime.tryParse(normalized)?.toIso8601String() ?? '',
      );
    } catch (_) {
      return (location: '', takenAt: '');
    }
  }

  double? _gpsCoordinate(IfdTag? tag) {
    if (tag == null) return null;
    try {
      final values = (tag.values as dynamic).toList() as List<dynamic>;
      if (values.length < 3) return null;
      double number(dynamic value) => (value as dynamic).toDouble() as double;
      return number(values[0]) +
          number(values[1]) / 60 +
          number(values[2]) / 3600;
    } catch (_) {
      return null;
    }
  }

  Future<List<ChatMessage>> getMessages() async {
    final response = await _client
        .get(_uri('/messages'))
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    final messages = data['messages'];

    if (messages is! List) {
      throw const FormatException('服务器没有返回消息列表');
    }

    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<List<ChatMessage>> getMessagesForDate(DateTime date) async {
    final value =
        '${date.year.toString().padLeft(4, '0')}-'
        '${date.month.toString().padLeft(2, '0')}-'
        '${date.day.toString().padLeft(2, '0')}';
    final response = await _client
        .get(_uri('/messages?date=$value'))
        .timeout(const Duration(seconds: 15));
    final messages = _decode(response)['messages'];
    if (messages is! List) return const [];
    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<List<ChatMessage>> searchMessages(String query) async {
    final keyword = query.trim();
    if (keyword.isEmpty) return const [];
    final uri = _uri(
      '/messages/search',
    ).replace(queryParameters: {'q': keyword, 'limit': '200'});
    final response = await _client
        .get(uri)
        .timeout(const Duration(seconds: 15));
    final messages = _decode(response)['messages'];
    if (messages is! List) return const [];
    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<List<ChatMessage>> getFavoriteMessages() async {
    final response = await _client
        .get(_uri('/messages/favorites'))
        .timeout(const Duration(seconds: 15));
    final messages = _decode(response)['messages'];
    if (messages is! List) return const [];
    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<void> setMessageFavorite(int messageId, bool favorite) async {
    final uri = _uri('/messages/$messageId/favorite');
    final response = favorite
        ? await _client.put(uri).timeout(const Duration(seconds: 15))
        : await _client.delete(uri).timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['detail'] ?? '收藏操作失败');
    }
  }

  Future<List<ChatMessage>> sendMessage(
    String message, {
    String? requestId,
    bool deviceContextEnabled = false,
    String replyMode = 'auto',
    String musicContext = '',
    bool fromMusicRoom = false,
    XhsCardData? xhsAttachment,
  }) async {
    final response = await _client
        .post(
          _uri(fromMusicRoom ? '/music/chat' : '/chat'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'message': message,
            if (requestId != null && requestId.isNotEmpty)
              'request_id': requestId,
            'device_context_enabled': deviceContextEnabled,
            'reply_mode': replyMode,
            if (musicContext.isNotEmpty) 'music_context': musicContext,
            if (xhsAttachment != null)
              'xhs_attachment': {'url': xhsAttachment.url, 'comment': message},
          }),
        )
        .timeout(const Duration(minutes: 5));
    final data = _decode(response);

    if (data['success'] != true) {
      throw const ChatReplyException();
    }

    final replyMessages = data['reply_messages'];
    if (replyMessages is List) {
      final values = replyMessages
          .whereType<Map<String, dynamic>>()
          .map(ChatMessage.fromJson)
          .toList();
      if (values.isNotEmpty) return values;
    }
    if (data['queued_while_sleeping'] == true) return const [];
    final reply = data['reply'];
    if (reply is! String || reply.trim().isEmpty) {
      throw const FormatException('服务器返回了空回复');
    }
    return [
      ChatMessage(
        role: 'assistant',
        content: reply.trim(),
        createdAt: DateTime.now(),
      ),
    ];
  }

  Future<List<ChatMessage>> getTodayMusicMessages() async {
    final now = DateTime.now();
    final date =
        '${now.year.toString().padLeft(4, '0')}-'
        '${now.month.toString().padLeft(2, '0')}-'
        '${now.day.toString().padLeft(2, '0')}';
    final response = await _client
        .get(_uri('/music/messages?date=$date'))
        .timeout(const Duration(seconds: 15));
    final messages = _decode(response)['messages'];
    if (messages is! List) return const [];
    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<Map<String, dynamic>> getChatStatus({String? requestId}) async {
    final uri = _uri('/chat/status').replace(
      queryParameters: requestId == null ? null : {'request_id': requestId},
    );
    final response = await _pollGet(uri, const Duration(seconds: 8));
    final data = _decode(response);
    if (data['success'] != true) throw const FormatException('回复状态读取失败');
    return data;
  }

  Future<XhsCardData> getXhsPreview(String url) async {
    final response = await _client
        .post(
          _uri('/xhs/preview'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'text': url, 'use_cache': true}),
        )
        .timeout(const Duration(minutes: 3));
    final data = _decode(response);
    if (data['success'] != true || data['preview'] is! Map<String, dynamic>) {
      throw Exception(data['detail'] ?? '小红书预览加载失败');
    }
    return XhsCardData.fromJson(data['preview'] as Map<String, dynamic>);
  }

  Future<List<ChatMessage>> getMessageUpdates(int afterId) async {
    final response = await _pollGet(
      _uri('/messages/updates?after_id=$afterId'),
      const Duration(seconds: 15),
    );
    final data = _decode(response);
    final messages = data['messages'];
    if (messages is! List) throw const FormatException('服务器没有返回消息列表');
    return messages
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<({ChatMessage message, List<ChatMessage> replies, bool replySuccess})>
  sendImageWithCaption(
    String filePath,
    String caption, {
    String? requestId,
    bool deviceContextEnabled = false,
    String replyMode = 'auto',
  }) async {
    final metadata = await _readPhotoMetadata(filePath);
    final request = http.MultipartRequest(
      'POST',
      _uri('/messages/image-with-caption'),
    );
    request.fields['caption'] = caption;
    if (requestId != null) request.fields['request_id'] = requestId;
    request.fields['device_context_enabled'] = '$deviceContextEnabled';
    request.fields['reply_mode'] = replyMode;
    if (metadata.location.isNotEmpty) {
      request.fields['location_text'] = metadata.location;
    }
    if (metadata.takenAt.isNotEmpty) {
      request.fields['taken_at'] = metadata.takenAt;
    }
    request.files.add(await http.MultipartFile.fromPath('file', filePath));
    final response = await _sendChatUpload(request, const Duration(minutes: 2));
    final data = _decode(response);
    final message = data['message'];
    if (data['success'] != true || message is! Map<String, dynamic>) {
      throw Exception(data['detail'] ?? data['error'] ?? '图片发送失败');
    }
    final replies = data['reply_messages'];
    return (
      message: ChatMessage.fromJson(message),
      replySuccess: data['reply_success'] == true,
      replies: replies is List
          ? replies
                .whereType<Map<String, dynamic>>()
                .map(ChatMessage.fromJson)
                .toList()
          : <ChatMessage>[],
    );
  }

  Future<
    ({
      ChatMessage message,
      List<ChatMessage> replies,
      String transcript,
      bool replySuccess,
    })
  >
  uploadVoice(
    String filePath,
    int durationSeconds, {
    bool deviceContextEnabled = false,
    String replyMode = 'auto',
  }) async {
    final request = http.MultipartRequest('POST', _uri('/messages/voice'))
      ..fields['duration_seconds'] = '$durationSeconds'
      ..fields['device_context_enabled'] = '$deviceContextEnabled'
      ..fields['reply_mode'] = replyMode
      ..files.add(await http.MultipartFile.fromPath('file', filePath));
    final response = await _sendChatUpload(request, const Duration(minutes: 3));
    final data = _decode(response);
    final message = data['message'];
    if (message is! Map<String, dynamic> || message['id'] is! int) {
      throw Exception(data['detail'] ?? data['error'] ?? '语音发送失败');
    }
    final replies = data['reply_messages'];
    return (
      message: ChatMessage.fromJson(message),
      replies: replies is List
          ? replies
                .whereType<Map<String, dynamic>>()
                .map(ChatMessage.fromJson)
                .toList()
          : <ChatMessage>[],
      transcript: data['transcript'] as String? ?? '',
      replySuccess:
          data['reply_success'] == true ||
          (data['reply_success'] == null && data['success'] == true),
    );
  }

  Future<String> startCall() async {
    final response = await _client
        .post(_uri('/calls/start'))
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    final callId = data['call_id'];
    if (data['success'] != true || callId is! String) {
      throw Exception(data['detail'] ?? data['error'] ?? '无法建立通话');
    }
    return callId;
  }

  Future<void> finishCall(String callId) async {
    await _client
        .post(
          _uri('/calls/finish'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'call_id': callId}),
        )
        .timeout(const Duration(seconds: 15));
  }

  Future<void> interruptCall(String callId, String generationId) async {
    await _client
        .post(
          _uri('/calls/interrupt'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'call_id': callId, 'generation_id': generationId}),
        )
        .timeout(const Duration(seconds: 5));
  }

  Future<({String reply, String mediaUrl, String generationId})> sendCallTurn(
    String callId,
    String filePath,
    int durationSeconds, {
    bool deviceContextEnabled = false,
    required String turnId,
    required String generationId,
  }) async {
    final request = http.MultipartRequest('POST', _uri('/calls/turn'))
      ..fields['call_id'] = callId
      ..fields['duration_seconds'] = '$durationSeconds'
      ..fields['device_context_enabled'] = '$deviceContextEnabled'
      ..fields['turn_id'] = turnId
      ..fields['generation_id'] = generationId
      ..files.add(await http.MultipartFile.fromPath('file', filePath));
    final streamed = await request.send().timeout(const Duration(minutes: 4));
    final response = await http.Response.fromStream(streamed);
    final data = _decode(response);
    final mediaUrl = data['media_url'];
    if (data['success'] != true || mediaUrl is! String) {
      throw Exception(data['detail'] ?? data['error'] ?? '通话回复失败');
    }
    return (
      reply: data['reply'] as String? ?? '',
      mediaUrl: mediaUrl,
      generationId: data['generation_id'] as String? ?? generationId,
    );
  }

  Future<List<StickerCatalogItem>> getStickerCatalog() async {
    final response = await _client
        .get(_uri('/sticker-catalog'))
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    final stickers = data['stickers'];
    if (stickers is! List) return const <StickerCatalogItem>[];
    return stickers
        .whereType<Map<String, dynamic>>()
        .map(StickerCatalogItem.fromJson)
        .where((item) => item.id.isNotEmpty && item.mediaUrl.isNotEmpty)
        .toList();
  }

  Future<({ChatMessage message, List<ChatMessage> replies, bool replySuccess})>
  uploadSticker(
    List<int> bytes,
    String filename, {
    String replyMode = 'auto',
  }) async {
    final request = http.MultipartRequest('POST', _uri('/messages/sticker'));
    request.fields['reply_mode'] = replyMode;
    request.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );
    final response = await _sendChatUpload(request, const Duration(minutes: 2));
    final data = _decode(response);
    final message = data['message'];
    if (data['success'] != true || message is! Map<String, dynamic>) {
      throw Exception(data['detail'] ?? data['error'] ?? '表情发送失败');
    }
    final replies = data['reply_messages'];
    final replyMessages = replies is List
        ? replies
              .whereType<Map<String, dynamic>>()
              .map(ChatMessage.fromJson)
              .toList()
        : <ChatMessage>[];
    return (
      message: ChatMessage.fromJson(message),
      replies: replyMessages,
      replySuccess: data['reply_success'] == true,
    );
  }

  Future<http.Response> _sendChatUpload(
    http.MultipartRequest request,
    Duration timeout,
  ) => _client.send(request).then(http.Response.fromStream).timeout(timeout);

  Future<void> setProactiveEnabled(bool enabled) async {
    final response = await _client
        .post(
          _uri('/proactive/settings'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'enabled': enabled}),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['error'] ?? '主动消息设置失败');
    }
  }

  Future<bool> getProactiveEnabled() async {
    final response = await _client
        .get(_uri('/proactive/settings'))
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true || data['enabled'] is! bool) {
      throw Exception(data['error'] ?? '主动消息设置读取失败');
    }
    return data['enabled'] as bool;
  }

  Future<void> setPersonalizationSettings({
    required String libraName,
    required String userName,
    required String libraNickname,
    required String userNickname,
    required String userAddress,
    required DateTime metAt,
    required int checkinMinMinutes,
    required int checkinMaxMinutes,
    required bool weatherReminderEnabled,
    required bool stateUpdateEnabled,
    Map<String, String>? userDietPreferences,
  }) async {
    final response = await _client
        .post(
          _uri('/personalization/settings'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'libra_name': libraName,
            'user_name': userName,
            'libra_nickname': libraNickname,
            'user_nickname': userNickname,
            'user_address': userAddress,
            'met_at':
                '${metAt.year.toString().padLeft(4, '0')}-${metAt.month.toString().padLeft(2, '0')}-${metAt.day.toString().padLeft(2, '0')}',
            'checkin_min_minutes': checkinMinMinutes,
            'checkin_max_minutes': checkinMaxMinutes,
            'weather_reminder_enabled': weatherReminderEnabled,
            'state_update_enabled': stateUpdateEnabled,
            'user_diet_preferences': ?userDietPreferences,
          }),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['detail'] ?? data['error'] ?? '个性化设置同步失败');
    }
  }

  Future<Map<String, dynamic>> getPersonalizationSettings() async {
    final response = await _client
        .get(_uri('/personalization/settings'))
        .timeout(const Duration(seconds: 15));
    return _decode(response);
  }

  Future<void> setAppPresence(bool active) async {
    final response = await _client
        .post(
          _uri('/app-presence'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'active': active}),
        )
        .timeout(const Duration(seconds: 8));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['detail'] ?? data['error'] ?? '前台状态同步失败');
    }
  }

  Future<void> updateUserStatus(String status) async {
    final response = await _client
        .post(
          _uri('/user/status'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'status': status}),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['detail'] ?? data['error'] ?? '状态同步失败');
    }
  }

  Future<void> registerPushToken(String token) async {
    final response = await _client
        .post(
          _uri('/push/register'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'token': token, 'platform': 'android'}),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) {
      throw Exception(data['error'] ?? '推送设备注册失败');
    }
  }

  Future<void> uploadCalendarEvents(
    List<CalendarEntry> events, {
    DateTime? syncStart,
    DateTime? syncEnd,
    bool reconcileSystem = false,
  }) async {
    if (events.isEmpty) return;
    final response = await _client
        .post(
          _uri('/calendar-events'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'events': events
                .take(5000)
                .map((event) => event.toApiJson())
                .toList(),
            if (syncStart != null)
              'sync_start': syncStart.toUtc().toIso8601String(),
            if (syncEnd != null) 'sync_end': syncEnd.toUtc().toIso8601String(),
            'reconcile_system': reconcileSystem,
          }),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) throw Exception('日历同步失败');
  }

  Future<void> syncTodos(List<TodoItem> todos) async {
    final response = await _client
        .post(
          _uri('/todos/sync'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'todos': todos.map((todo) => todo.toApiJson()).toList(),
          }),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) throw Exception('待办同步失败');
  }

  Future<List<TodoItem>> getTodos() async {
    final response = await _client
        .get(_uri('/todos'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['todos'];
    if (values is! List) return const [];
    return values.whereType<Map<String, dynamic>>().map((item) {
      return TodoItem(
        id: '${item['local_id']}',
        title: '${item['title']}',
        date: DateTime.parse('${item['due_date']}'),
        done: item['done'] == true || item['done'] == 1,
        remindAt: item['remind_at'] == null ? null : DateTime.parse('${item['remind_at']}'),
        repeatRule: item['repeat_rule'] as String?,
      );
    }).toList();
  }

  Future<void> saveTodo(TodoItem todo) async {
    final response = await _client
        .put(
          _uri('/todos/${Uri.encodeComponent(todo.id)}'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode(todo.toApiJson()),
        )
        .timeout(const Duration(seconds: 15));
    if (_decode(response)['success'] != true) throw Exception('待办保存失败');
  }

  Future<void> deleteTodo(String id) async {
    final response = await _client
        .delete(_uri('/todos/${Uri.encodeComponent(id)}'))
        .timeout(const Duration(seconds: 15));
    if (_decode(response)['success'] != true) throw Exception('待办删除失败');
  }

  Future<void> syncHabits(List<HabitItem> habits) async {
    final response = await _client
        .post(
          _uri('/habits/sync'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'habits': habits.map((habit) => habit.toApiJson()).toList(),
          }),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) throw Exception('打卡同步失败');
  }

  Future<List<HabitItem>> getHabits() async {
    final response = await _client
        .get(_uri('/habits'))
        .timeout(const Duration(seconds: 15));
    final values = _decode(response)['habits'];
    if (values is! List) return const [];
    return values.whereType<Map<String, dynamic>>().map((item) {
      return HabitItem(
        id: '${item['local_id']}',
        title: '${item['title']}',
        activeFrom: DateTime.parse('${item['active_from']}'),
        activeUntil: DateTime.tryParse('${item['active_until'] ?? ''}'),
        completedDates: (item['completed_dates'] as List? ?? const [])
            .map((date) => '$date')
            .toList(),
      );
    }).toList();
  }

  Future<void> saveHabit(HabitItem habit) async {
    final response = await _client
        .put(
          _uri('/habits/${Uri.encodeComponent(habit.id)}'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode(habit.toApiJson()),
        )
        .timeout(const Duration(seconds: 15));
    if (_decode(response)['success'] != true) throw Exception('打卡项目保存失败');
  }

  Future<void> setHabitCheckin(String id, DateTime date, bool done) async {
    final day = HabitItem.dayKey(date);
    final response = await _client
        .put(
          _uri('/habits/${Uri.encodeComponent(id)}/checkin'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'checked_date': day, 'done': done}),
        )
        .timeout(const Duration(seconds: 15));
    if (_decode(response)['success'] != true) throw Exception('打卡保存失败');
  }

  Future<void> deleteHabit(String id) async {
    final response = await _client
        .delete(_uri('/habits/${Uri.encodeComponent(id)}'))
        .timeout(const Duration(seconds: 15));
    if (_decode(response)['success'] != true) throw Exception('打卡项目删除失败');
  }

  Future<Object?> getMobileState(String key) async {
    final response = await _client
        .get(_uri('/mobile-state/$key'))
        .timeout(const Duration(seconds: 15));
    return _decode(response)['value'];
  }

  Future<void> setMobileState(String key, Object? value) async {
    final response = await _client
        .put(
          _uri('/mobile-state/$key'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({'value': value}),
        )
        .timeout(const Duration(seconds: 15));
    if (_decode(response)['success'] != true) {
      throw Exception('状态同步失败');
    }
  }

  Future<void> uploadFocusSessions(List<FocusSession> sessions) async {
    if (sessions.isEmpty) return;
    final response = await _client
        .post(
          _uri('/focus/sessions'),
          headers: const {'Content-Type': 'application/json; charset=UTF-8'},
          body: jsonEncode({
            'sessions': sessions.map((session) => session.toApiJson()).toList(),
          }),
        )
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    if (data['success'] != true) throw Exception('专注记录同步失败');
  }

  Future<List<FocusSession>> getFocusSessions({int days = 90}) async {
    final safeDays = days.clamp(1, 90);
    final response = await _client
        .get(_uri('/focus/stats?days=$safeDays'))
        .timeout(const Duration(seconds: 15));
    final data = _decode(response);
    final sessions = data['sessions'];
    if (sessions is! List) throw const FormatException('服务器没有返回专注记录');
    return sessions
        .map(FocusSession.fromApiJson)
        .whereType<FocusSession>()
        .toList();
  }

  Map<String, dynamic> _decode(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      try {
        final error = jsonDecode(utf8.decode(response.bodyBytes));
        if (error is Map<String, dynamic>) {
          throw Exception(
            error['detail'] ?? error['error'] ?? '服务器错误：${response.statusCode}',
          );
        }
      } on FormatException {
        // Fall through to the status-code error below.
      }
      throw Exception('服务器错误：${response.statusCode}');
    }

    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('无法识别服务器响应');
    }
    return decoded;
  }

  void close() => _client.close();
}

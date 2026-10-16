class DreamReading {
  DreamReading.fromJson(Map<String, dynamic> json)
    : id = json['id'] as String,
      level = json['period_type'] as String,
      start = DateTime.parse(json['period_start'] as String),
      end = DateTime.parse(json['period_end'] as String),
      generated = DateTime.parse(
        json['generated_at'] as String,
      ).toUtc().add(const Duration(hours: 8)),
      content = json['content'] as String? ?? '',
      reflection = json['reflection'] as String? ?? '',
      available = json['available'] == true,
      complete = json['complete_period'] == true,
      scenes = (json['scenes'] as List? ?? []).cast<Map<String, dynamic>>(),
      foresight = (json['foresight'] as List? ?? [])
          .cast<Map<String, dynamic>>();

  final String id, level, content, reflection;
  final DateTime start, end, generated;
  final bool available, complete;
  final List<Map<String, dynamic>> scenes, foresight;
  static const labels = {
    'day': '一日回顾',
    'week': '一周回顾',
    'month': '一月回顾',
    'quarter': '一季回顾',
    'year': '一年回顾',
  };
  String get title => labels[level] ?? '回顾';
  String get range => level == 'day'
      ? dateLabel(start)
      : '${dateLabel(start)} — ${dateLabel(end.subtract(const Duration(days: 1)))}';
  bool covers(DateTime date) {
    final day = DateTime(date.year, date.month, date.day);
    return !day.isBefore(start) && day.isBefore(end);
  }

  static String dateLabel(DateTime date) =>
      '${date.year}.${date.month.toString().padLeft(2, '0')}.${date.day.toString().padLeft(2, '0')}';
}

class DreamReadingBatch {
  DreamReadingBatch.fromJson(Map<String, dynamic> json)
    : items = (json['items'] as List)
          .map((e) => DreamReading.fromJson(e as Map<String, dynamic>))
          .toList(),
      hasMore = json['has_more'] == true;
  final List<DreamReading> items;
  final bool hasMore;
}

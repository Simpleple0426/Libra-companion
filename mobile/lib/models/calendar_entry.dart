class CalendarEntry {
  const CalendarEntry({
    required this.id,
    required this.title,
    required this.start,
    required this.end,
    this.allDay = false,
    this.location,
    this.source = 'system',
  });

  final String id;
  final String title;
  final DateTime start;
  final DateTime end;
  final bool allDay;
  final String? location;
  final String source;

  Map<String, dynamic> toApiJson() => {
    'event_id': id,
    'title': title,
    'start': start.toUtc().toIso8601String(),
    'end': end.toUtc().toIso8601String(),
    'all_day': allDay,
    'location': location ?? '',
    'source': source,
  };
}

class TodoItem {
  const TodoItem({required this.id, required this.title, required this.date,
    this.done = false, this.remindAt, this.repeatRule});
  final String id;
  final String title;
  final DateTime date;
  final bool done;
  final DateTime? remindAt;
  final String? repeatRule;
  TodoItem copyWith({String? title, bool? done}) => TodoItem(id: id,
    title: title ?? this.title, date: date, done: done ?? this.done,
    remindAt: remindAt, repeatRule: repeatRule);
  Map<String, dynamic> toJson() => {'id': id, 'title': title,
    'date': date.toIso8601String(), 'done': done,
    'remind_at': remindAt?.toIso8601String(), 'repeat_rule': repeatRule};
  Map<String, dynamic> toApiJson() => {'local_id': id, 'title': title,
    'due_date': date.toIso8601String(), 'done': done,
    'remind_at': remindAt?.toIso8601String(), 'repeat_rule': repeatRule};
  factory TodoItem.fromJson(Map<String, dynamic> json) => TodoItem(
    id: json['id'] as String, title: json['title'] as String,
    date: DateTime.parse(json['date'] as String), done: json['done'] as bool? ?? false,
    remindAt: json['remind_at'] == null ? null : DateTime.parse(json['remind_at'] as String),
    repeatRule: json['repeat_rule'] as String?);
}

class HabitItem {
  const HabitItem({
    required this.id,
    required this.title,
    required this.activeFrom,
    this.activeUntil,
    this.completedDates = const [],
  });

  final String id;
  final String title;
  final DateTime activeFrom;
  final DateTime? activeUntil;
  final List<String> completedDates;

  static String dayKey(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

  bool isDoneOn(DateTime date) => completedDates.contains(dayKey(date));

  bool isActiveOn(DateTime date) {
    final day = DateTime(date.year, date.month, date.day);
    final from = DateTime(activeFrom.year, activeFrom.month, activeFrom.day);
    final until = activeUntil == null
        ? null
        : DateTime(activeUntil!.year, activeUntil!.month, activeUntil!.day);
    return !day.isBefore(from) && (until == null || !day.isAfter(until));
  }

  HabitItem toggledOn(DateTime date) {
    final key = dayKey(date);
    final dates = [...completedDates];
    dates.contains(key) ? dates.remove(key) : dates.add(key);
    return HabitItem(
      id: id,
      title: title,
      activeFrom: activeFrom,
      activeUntil: activeUntil,
      completedDates: dates,
    );
  }

  HabitItem retiredBefore(DateTime date) => HabitItem(
    id: id,
    title: title,
    activeFrom: activeFrom,
    activeUntil: DateTime(
      date.year,
      date.month,
      date.day,
    ).subtract(const Duration(days: 1)),
    completedDates: completedDates,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'activeFrom': dayKey(activeFrom),
    'activeUntil': activeUntil == null ? null : dayKey(activeUntil!),
    'completedDates': completedDates,
  };

  Map<String, dynamic> toApiJson() => {
    'local_id': id,
    'title': title,
    'active_from': dayKey(activeFrom),
    'active_until': activeUntil == null ? null : dayKey(activeUntil!),
    'completed_dates': completedDates,
  };

  factory HabitItem.fromJson(Map<String, dynamic> json) => HabitItem(
    id: json['id'] as String,
    title: json['title'] as String,
    activeFrom:
        DateTime.tryParse(json['activeFrom'] as String? ?? '') ??
        DateTime(1900, 1, 1),
    activeUntil: DateTime.tryParse(json['activeUntil'] as String? ?? ''),
    completedDates: (json['completedDates'] as List? ?? const [])
        .whereType<String>()
        .toList(),
  );
}

enum ImportantDateType { anniversary, birthday, yearly, oneTime }

class ImportantDate {
  const ImportantDate({
    this.id,
    required this.title,
    required this.date,
    ImportantDateType? type,
    bool? repeatsAnnually,
  }) : type =
           type ??
           (repeatsAnnually == false
               ? ImportantDateType.oneTime
               : ImportantDateType.yearly);

  final int? id;
  final String title;
  final DateTime date;
  final ImportantDateType type;
  bool get repeatsAnnually => type != ImportantDateType.oneTime;

  String occurrenceTitle(int year) {
    if (type == ImportantDateType.anniversary) {
      final years = year - date.year;
      return years > 0 ? '$title · $years周年' : title;
    }
    if (type == ImportantDateType.birthday) {
      return title.endsWith('生日') ? title : '$title · 生日';
    }
    return title;
  }

  String get typeLabel => switch (type) {
    ImportantDateType.anniversary => '纪念日',
    ImportantDateType.birthday => '生日',
    ImportantDateType.yearly => '每年重复',
    ImportantDateType.oneTime => '一次性日期',
  };

  ImportantDate copyWith({
    String? title,
    DateTime? date,
    ImportantDateType? type,
    bool? repeatsAnnually,
  }) => ImportantDate(
    id: id,
    title: title ?? this.title,
    date: date ?? this.date,
    type:
        type ??
        (repeatsAnnually == null
            ? this.type
            : repeatsAnnually
            ? ImportantDateType.yearly
            : ImportantDateType.oneTime),
  );
}

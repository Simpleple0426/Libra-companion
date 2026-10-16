class TimelineEvent {
  const TimelineEvent({
    required this.id,
    required this.occurredAt,
    required this.event,
    this.kind,
    this.summarySource,
    this.detail = const {},
  });

  final String id;
  final DateTime occurredAt;
  final String event;
  final String? kind;
  final String? summarySource;
  final Map<String, dynamic> detail;

  bool get hasDetail => detail.isNotEmpty;

  factory TimelineEvent.fromJson(Map<String, dynamic> json) => TimelineEvent(
    id: '${json['id']}',
    // Life events are stored as timezone-aware instants (normally UTC).  Dart
    // keeps an offset timestamp as UTC after parsing, so convert once at the
    // API boundary before any home/detail widget formats its hour.
    occurredAt: DateTime.parse(json['occurred_at'] as String).toLocal(),
    event: json['event'] as String,
    kind: json['kind'] as String?,
    summarySource: json['summary_source'] as String?,
    detail: json['detail'] is Map
        ? Map<String, dynamic>.from(json['detail'] as Map)
        : const {},
  );
}

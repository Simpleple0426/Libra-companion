class SharedMemoryItem {
  const SharedMemoryItem({
    required this.id,
    required this.type,
    required this.author,
    required this.content,
    required this.eventDate,
    required this.createdAt,
    this.sourceKind,
    this.sourceTitle,
    this.sourceUrl,
    this.mediaUrl,
    this.location,
    this.takenAt,
    this.comments = const [],
  });
  final int id;
  final String type;
  final String author;
  final String content;
  final DateTime eventDate;
  final DateTime createdAt;
  final String? sourceKind;
  final String? sourceTitle;
  final String? sourceUrl;
  String get sourceLabel => switch (sourceKind) {
    'movie_review' => '影片影评',
    'movie_quote' => '电影台词摘抄',
    'book_quote' => '书籍名句摘抄',
    'book_introduction' => '购书想法',
    'walk_thought' => '散步随想',
    'leisure_thought' => '休闲随想',
    _ => '动态',
  };
  // Older clients display the provenance heading as part of the body.
  String get displayContent => sourceKind != null && content.contains('\n\n')
      ? content.substring(content.indexOf('\n\n') + 2)
      : content;
  final String? mediaUrl;
  final String? location;
  final DateTime? takenAt;
  final List<MemoryComment> comments;
  bool get isPhoto => type == 'photo' && mediaUrl != null;
  String? get thumbnailUrl {
    final value = mediaUrl;
    if (value == null || !value.startsWith('/uploads/chat/')) return value;
    final filename = value.split('/').last;
    final dot = filename.lastIndexOf('.');
    final stem = dot > 0 ? filename.substring(0, dot) : filename;
    return '/uploads/thumbnails/$stem.jpg';
  }

  factory SharedMemoryItem.fromJson(Map<String, dynamic> json) {
    final now = DateTime.now();
    return SharedMemoryItem(
      id: json['id'] as int? ?? 0,
      type: json['memory_type'] as String? ?? 'moment',
      author: json['author'] as String? ?? 'libra',
      content: json['content'] as String? ?? '',
      sourceKind: json['source_kind'] as String?,
      sourceTitle: json['source_title'] as String?,
      sourceUrl: json['source_url'] as String?,
      mediaUrl: json['media_url'] as String?,
      location: json['location_text'] as String?,
      takenAt: DateTime.tryParse(json['taken_at'] as String? ?? ''),
      eventDate: DateTime.tryParse(json['event_date'] as String? ?? '') ?? now,
      createdAt:
          DateTime.tryParse(json['created_at'] as String? ?? '')?.toLocal() ??
          now,
      comments: (json['comments'] as List? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(MemoryComment.fromJson)
          .toList(),
    );
  }
}

class MemoryComment {
  const MemoryComment({
    required this.id,
    required this.memoryId,
    required this.author,
    required this.content,
    required this.createdAt,
  });

  final int id;
  final int memoryId;
  final String author;
  final String content;
  final DateTime createdAt;

  factory MemoryComment.fromJson(Map<String, dynamic> json) => MemoryComment(
    id: json['id'] as int? ?? 0,
    memoryId: json['memory_id'] as int? ?? 0,
    author: json['author'] as String? ?? 'user',
    content: json['content'] as String? ?? '',
    createdAt:
        DateTime.tryParse(json['created_at'] as String? ?? '') ??
        DateTime.now(),
  );
}

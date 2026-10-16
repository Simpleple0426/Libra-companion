class LibraryQuote {
  const LibraryQuote({
    required this.text,
    required this.thought,
    required this.translation,
  });
  final String text;
  final String thought;
  final String translation;

  factory LibraryQuote.fromJson(Map<String, dynamic> json) => LibraryQuote(
    text: json['text'] as String? ?? '',
    thought: json['thought'] as String? ?? '',
    translation: json['translation'] as String? ?? '',
  );
}

class LibraryBook {
  const LibraryBook({
    required this.id,
    required this.title,
    required this.author,
    required this.status,
    required this.progress,
    required this.chapter,
    required this.introduction,
    required this.introductionStatus,
    required this.scopeNote,
    required this.quotes,
  });

  final String id;
  final String title;
  final String author;
  final String status;
  final double progress;
  final String chapter;
  final String introduction;
  final String introductionStatus;
  final String scopeNote;
  final List<LibraryQuote> quotes;

  String get progressLabel => switch (status) {
    'read' => '已读完',
    'reading' => '阅读中 · ${progress.toStringAsFixed(1)}%',
    _ => '未开始阅读',
  };

  factory LibraryBook.fromJson(Map<String, dynamic> json) => LibraryBook(
    id: json['id'] as String? ?? '',
    title: json['title'] as String? ?? '',
    author: json['author'] as String? ?? '',
    status: json['reading_status'] as String? ?? 'unread',
    progress: ((json['progress_percent'] as num?)?.toDouble() ?? 0).clamp(
      0,
      100,
    ),
    chapter: json['chapter'] as String? ?? '',
    introduction: json['introduction'] as String? ?? '',
    introductionStatus: json['introduction_status'] as String? ?? 'pending',
    scopeNote: json['scope_note'] as String? ?? '',
    quotes: (json['quotes'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(LibraryQuote.fromJson)
        .toList(),
  );
}

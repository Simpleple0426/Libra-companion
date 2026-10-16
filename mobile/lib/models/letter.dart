class Letter {
  const Letter({
    required this.id,
    required this.sender,
    required this.subject,
    required this.content,
    required this.createdAt,
    required this.favorite,
    this.replyToId,
    this.readAt,
  });

  final int id;
  final String sender;
  final String subject;
  final String content;
  final DateTime createdAt;
  final bool favorite;
  final int? replyToId;
  final DateTime? readAt;

  bool get isMine => sender == 'user';
  bool get isUnread => !isMine && readAt == null;

  static List<Letter> repliesInThread(List<Letter> letters, int rootId) {
    final ids = <int>{rootId};
    var changed = true;
    while (changed) {
      changed = false;
      for (final letter in letters) {
        if (ids.contains(letter.replyToId) && ids.add(letter.id)) {
          changed = true;
        }
      }
    }
    return letters
        .where((letter) => letter.id != rootId && ids.contains(letter.id))
        .toList()
      ..sort((a, b) {
        final time = a.createdAt.compareTo(b.createdAt);
        return time == 0 ? a.id.compareTo(b.id) : time;
      });
  }

  factory Letter.fromJson(Map<String, dynamic> json) => Letter(
    id: json['id'] as int,
    sender: json['sender'] as String? ?? 'libra',
    subject: json['subject'] as String? ?? '',
    content: json['content'] as String? ?? '',
    createdAt: DateTime.parse(json['created_at'] as String),
    favorite: json['favorite'] == 1 || json['favorite'] == true,
    replyToId: json['reply_to_id'] as int?,
    readAt: json['read_at'] == null
        ? null
        : DateTime.tryParse(json['read_at'] as String),
  );
}

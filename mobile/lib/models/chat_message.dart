import 'dart:convert';

class XhsCardData {
  const XhsCardData({
    required this.url,
    required this.title,
    this.noteId = '',
    this.author = '',
    this.summary = '',
    this.coverUrl = '',
    this.imageUrls = const [],
    this.comment = '',
  });

  final String noteId;
  final String url;
  final String title;
  final String author;
  final String summary;
  final String coverUrl;
  final List<String> imageUrls;
  final String comment;

  factory XhsCardData.fromJson(Map<String, dynamic> json) => XhsCardData(
    noteId: json['note_id']?.toString() ?? '',
    url: (json['url'] ?? json['original_url'] ?? '').toString(),
    title: json['title']?.toString() ?? '小红书笔记',
    author: json['author']?.toString() ?? '',
    summary: json['summary']?.toString() ?? '',
    coverUrl: json['cover_url']?.toString() ?? '',
    imageUrls: json['image_urls'] is List
        ? (json['image_urls'] as List)
              .map((value) => value.toString())
              .where((value) => value.isNotEmpty)
              .toList()
        : const [],
    comment: json['comment']?.toString() ?? '',
  );

  Map<String, dynamic> toJson() => {
    'note_id': noteId,
    'url': url,
    'title': title,
    'author': author,
    'summary': summary,
    'cover_url': coverUrl,
    'image_urls': imageUrls,
    'comment': comment,
  };

  XhsCardData withComment(String value) => XhsCardData(
    noteId: noteId,
    url: url,
    title: title,
    author: author,
    summary: summary,
    coverUrl: coverUrl,
    imageUrls: imageUrls,
    comment: value,
  );
}

class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.content,
    this.id,
    this.createdAt,
    this.source = 'chat',
    this.messageType = 'text',
    this.mediaUrl,
    this.localAssetPath,
    this.localFilePath,
    this.durationSeconds,
    this.favorite = false,
    this.xhsCard,
    this.requestId,
  });

  final int? id;
  final String role;
  final String content;
  final DateTime? createdAt;
  final String source;
  final String messageType;
  final String? mediaUrl;
  final String? localAssetPath;
  final String? localFilePath;
  final int? durationSeconds;
  final bool favorite;
  final XhsCardData? xhsCard;
  final String? requestId;

  bool get isUser => role == 'user';
  bool get isImage =>
      (messageType == 'image' || messageType == 'sticker') &&
      (mediaUrl != null || localAssetPath != null || localFilePath != null);
  bool get isSticker =>
      messageType == 'sticker' && (mediaUrl != null || localAssetPath != null);
  bool get isNudge => messageType == 'nudge';
  bool get isVoice => messageType == 'voice';
  bool get isXhsCard => messageType == 'xhs_card' && xhsCard != null;

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    final messageType = json['message_type'] as String? ?? 'text';
    final rawContent = json['content'] as String? ?? '';
    XhsCardData? xhsCard;
    if (messageType == 'xhs_card') {
      try {
        final decoded = jsonDecode(rawContent);
        if (decoded is Map<String, dynamic>) {
          xhsCard = XhsCardData.fromJson(decoded);
        }
      } catch (_) {}
    }
    return ChatMessage(
      id: json['id'] as int?,
      role: json['role'] as String? ?? 'assistant',
      content: xhsCard?.comment ?? rawContent,
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? ''),
      source: json['source'] as String? ?? 'chat',
      messageType: messageType,
      mediaUrl: json['media_url'] as String?,
      durationSeconds: json['duration_seconds'] as int?,
      favorite: json['favorite'] == true || json['favorite'] == 1,
      xhsCard: xhsCard,
      requestId: json['request_id'] as String?,
    );
  }

  ChatMessage copyWith({bool? favorite}) => ChatMessage(
    id: id,
    role: role,
    content: content,
    createdAt: createdAt,
    source: source,
    messageType: messageType,
    mediaUrl: mediaUrl,
    localAssetPath: localAssetPath,
    localFilePath: localFilePath,
    durationSeconds: durationSeconds,
    favorite: favorite ?? this.favorite,
    xhsCard: xhsCard,
    requestId: requestId,
  );

  bool confirmsDeliveryOf(String? pendingRequestId) =>
      pendingRequestId != null &&
      pendingRequestId.isNotEmpty &&
      isUser &&
      id != null &&
      requestId == pendingRequestId;

  bool matchesPendingUserCopy(ChatMessage serverMessage) {
    if (!isUser ||
        id != null ||
        !serverMessage.isUser ||
        serverMessage.id == null) {
      return false;
    }
    final localRequestId = requestId?.trim() ?? '';
    final serverRequestId = serverMessage.requestId?.trim() ?? '';
    if (localRequestId.isNotEmpty && serverRequestId.isNotEmpty) {
      return localRequestId == serverRequestId;
    }
    if (content != serverMessage.content ||
        messageType != serverMessage.messageType ||
        xhsCard?.url != serverMessage.xhsCard?.url) {
      return false;
    }
    return createdAt == null ||
        serverMessage.createdAt == null ||
        createdAt!.difference(serverMessage.createdAt!).abs() <
            const Duration(minutes: 10);
  }
}

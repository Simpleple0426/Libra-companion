import '../models/chat_message.dart';

/// Merge an upload response even if polling already replaced its local bubble.
void mergeUploadedMessage(
  List<ChatMessage> messages,
  ChatMessage optimistic,
  ChatMessage saved,
) {
  final localIndex = messages.indexOf(optimistic);
  final savedIndex = saved.id == null
      ? -1
      : messages.indexWhere((message) => message.id == saved.id);
  if (savedIndex >= 0) {
    messages[savedIndex] = saved;
    if (localIndex >= 0 && localIndex != savedIndex) {
      messages.removeAt(localIndex);
    }
  } else if (localIndex >= 0) {
    messages[localIndex] = saved;
  } else {
    messages.add(saved);
  }
}

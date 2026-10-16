import 'package:flutter_test/flutter_test.dart';
import 'package:libra_app/models/letter.dart';

Letter letter(int id, String sender, int? parent) => Letter(
  id: id,
  sender: sender,
  subject: '',
  content: 'letter $id',
  createdAt: DateTime(2026, 10, 4, 12, id),
  favorite: false,
  replyToId: parent,
);

void main() {
  test('shows every round and preserves sender identity for old and new threads', () {
    final items = [letter(5, 'libra', 4), letter(3, 'libra', 1),
      letter(1, 'libra', null), letter(4, 'user', 3), letter(2, 'user', 1),
      letter(6, 'user', null)];
    final replies = Letter.repliesInThread(items, 1);
    expect(replies.map((item) => item.id), [2, 3, 4, 5]);
    expect(replies.map((item) => item.isMine), [true, false, true, false]);
    expect(replies.where((item) => item.isUnread).map((item) => item.id), [3, 5]);
  });
}

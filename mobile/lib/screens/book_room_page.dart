import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../models/chat_message.dart';
import '../services/libra_api.dart';
import '../widgets/reading_room_background.dart';
import 'book_library_page.dart';

const _accent = Color(0xFFE77E82);
const _ink = Color(0xFF524849);

class BookRoomPage extends StatefulWidget {
  const BookRoomPage({super.key});

  @override
  State<BookRoomPage> createState() => _BookRoomPageState();
}

class _BookRoomPageState extends State<BookRoomPage> {
  final _api = LibraApi();
  List<ReadingBook> _books = const [];
  bool _loading = true;
  bool _importing = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final books = await _api.getReadingBooks();
      if (mounted) setState(() => _books = books);
    } catch (error) {
      if (mounted) _notice('书架暂时无法读取：$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _import() async {
    final selected = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['epub', 'txt', 'md'],
    );
    final file = selected.isEmpty ? null : selected.first;
    if (file == null) return;
    final bytes = await file.readAsBytes();
    setState(() => _importing = true);
    try {
      await _api.importReadingBook(bytes: bytes, filename: file.name);
      await _load();
      _notice('已放进书房');
    } catch (error) {
      _notice('导入失败：$error');
    } finally {
      if (mounted) setState(() => _importing = false);
    }
  }

  void _notice(String value) => ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(value), behavior: SnackBarBehavior.floating),
  );

  @override
  Widget build(BuildContext context) => ReadingRoomBackground(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        scrolledUnderElevation: 0,
        elevation: 0,
        title: const Text(
          '书房',
          style: TextStyle(color: _ink, fontWeight: FontWeight.w700),
        ),
        iconTheme: const IconThemeData(color: _accent),
        actionsIconTheme: const IconThemeData(color: _accent),
        actions: [
          TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: _accent),
            onPressed: _importing ? null : _import,
            icon: _importing
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.add_rounded),
            label: const Text('导入'),
          ),
          TextButton.icon(
            style: TextButton.styleFrom(foregroundColor: _accent),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const BookLibraryPage()),
            ),
            icon: const Icon(Icons.local_library_outlined),
            label: const Text('书库'),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: _loading
            ? const Center(child: CircularProgressIndicator(color: _accent))
            : _books.isEmpty
            ? ListView(
                children: const [
                  SizedBox(height: 180),
                  Icon(Icons.menu_book_outlined, color: _accent, size: 52),
                  SizedBox(height: 14),
                  Center(
                    child: Text('导入一本想和左然一起读的书', style: TextStyle(color: _ink)),
                  ),
                  SizedBox(height: 8),
                  Center(
                    child: Text(
                      '支持 EPUB、TXT 与 Markdown',
                      style: TextStyle(color: Color(0xFF9B8B89)),
                    ),
                  ),
                ],
              )
            : ListView.separated(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
                itemCount: _books.length,
                separatorBuilder: (_, _) => const SizedBox(height: 12),
                itemBuilder: (context, index) => _BookCard(
                  book: _books[index],
                  onTap: () async {
                    await Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => _CoReadingPage(book: _books[index]),
                      ),
                    );
                    _load();
                  },
                ),
              ),
      ),
    ),
  );
}

class _BookCard extends StatelessWidget {
  const _BookCard({required this.book, required this.onTap});
  final ReadingBook book;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white.withValues(alpha: .84),
    borderRadius: BorderRadius.circular(28),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(28),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            const CircleAvatar(
              backgroundColor: Color(0xFFFFE1DE),
              child: Icon(Icons.auto_stories_rounded, color: _accent),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    book.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: _ink,
                      fontSize: 17,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (book.author.isNotEmpty) ...[
                    const SizedBox(height: 3),
                    Text(
                      book.author,
                      style: const TextStyle(color: Color(0xFF9B8B89)),
                    ),
                  ],
                  const SizedBox(height: 10),
                  Text(
                    '共 ${book.chunkCount} 段 · 继续共读',
                    style: const TextStyle(color: _accent, fontSize: 13),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right_rounded, color: _accent),
          ],
        ),
      ),
    ),
  );
}

class _CoReadingPage extends StatefulWidget {
  const _CoReadingPage({required this.book});
  final ReadingBook book;
  @override
  State<_CoReadingPage> createState() => _CoReadingPageState();
}

class _CoReadingPageState extends State<_CoReadingPage> {
  final _api = LibraApi();
  final _input = TextEditingController();
  ReadingChunk? _chunk;
  int? _selectedSectionIndex;
  List<ReadingSection> _sections = const [];
  List<ChatMessage> _messages = const [];
  bool _loading = true;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final values = await Future.wait([
        _api.getReadingChunk(widget.book.bookId),
        _api.getReadingSections(widget.book.bookId),
      ]);
      if (mounted) {
        setState(() {
          _chunk = values[0] as ReadingChunk;
          _sections = values[1] as List<ReadingSection>;
        });
      }
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _discuss({bool advance = false}) async {
    if (_sending) return;
    setState(() => _sending = true);
    try {
      final replies = await _api.discussReading(
        widget.book.bookId,
        message: _input.text,
        advance: advance,
        chunkId: _chunk?.chunkId ?? '',
        sectionIndex: _selectedSectionIndex,
      );
      if (!mounted) return;
      setState(() {
        _messages = [..._messages, ...replies];
        _input.clear();
      });
      if (advance) await _load();
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('共读暂时失败：$error')));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _chooseExcerpt() async {
    final chosen = await showModalBottomSheet<int>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFFFFF8F7),
      builder: (context) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * .72,
          child: Column(
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(22, 20, 22, 10),
                child: Row(
                  children: [
                    Icon(Icons.format_list_bulleted_rounded, color: _accent),
                    SizedBox(width: 10),
                    Text(
                      '选择章节与段落',
                      style: TextStyle(
                        color: _ink,
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: _sections.length,
                  itemBuilder: (context, sectionIndex) {
                    final section = _sections[sectionIndex];
                    return ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 22,
                        vertical: 6,
                      ),
                      leading: Text(
                        '${sectionIndex + 1}',
                        style: const TextStyle(
                          color: _accent,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      title: Text(
                        section.title,
                        style: const TextStyle(
                          color: _ink,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: Text(
                        '共 ${section.chunks.length} 段',
                        style: const TextStyle(color: Color(0xFF9A8580)),
                      ),
                      trailing: const Icon(
                        Icons.chevron_right_rounded,
                        color: _accent,
                      ),
                      onTap: () => Navigator.pop(context, sectionIndex),
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (chosen == null) return;
    setState(() => _loading = true);
    try {
      final chunk = await _api.getReadingSection(widget.book.bookId, chosen);
      if (mounted)
        setState(() {
          _chunk = chunk;
          _selectedSectionIndex = chosen;
          _messages = const [];
        });
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: const Color(0xFFFFF5F4),
    appBar: AppBar(
      backgroundColor: Colors.transparent,
      elevation: 0,
      iconTheme: const IconThemeData(color: _ink),
      title: Text(
        widget.book.title,
        style: const TextStyle(color: _ink, fontWeight: FontWeight.w700),
      ),
      actions: [
        TextButton.icon(
          onPressed: _loading ? null : _chooseExcerpt,
          icon: const Icon(Icons.list_alt_rounded, color: _accent),
          label: const Text('章节', style: TextStyle(color: _accent)),
        ),
      ],
    ),
    body: _loading
        ? const Center(child: CircularProgressIndicator(color: _accent))
        : Column(
            children: [
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 18),
                  children: [if (_chunk != null) _ExcerptCard(chunk: _chunk!)],
                ),
              ),
              DecoratedBox(
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF5F4).withValues(alpha: .97),
                  border: const Border(
                    top: BorderSide(color: Color(0xFFF1D5D2)),
                  ),
                ),
                child: SafeArea(
                  top: false,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      ConstrainedBox(
                        constraints: const BoxConstraints(maxHeight: 190),
                        child: _messages.isEmpty
                            ? const Padding(
                                padding: EdgeInsets.fromLTRB(24, 14, 24, 8),
                                child: Align(
                                  alignment: Alignment.centerLeft,
                                  child: Text(
                                    '左然会在这里回应你对这一章的想法。',
                                    style: TextStyle(color: Color(0xFF9A8580)),
                                  ),
                                ),
                              )
                            : ListView.builder(
                                shrinkWrap: true,
                                padding: const EdgeInsets.fromLTRB(
                                  20,
                                  12,
                                  20,
                                  4,
                                ),
                                itemCount: _messages.length,
                                itemBuilder: (context, index) {
                                  final message = _messages[index];
                                  return Padding(
                                    padding: const EdgeInsets.only(bottom: 8),
                                    child: Align(
                                      alignment: Alignment.centerLeft,
                                      child: DecoratedBox(
                                        decoration: BoxDecoration(
                                          color: Colors.white.withValues(
                                            alpha: .9,
                                          ),
                                          borderRadius: BorderRadius.circular(
                                            18,
                                          ),
                                        ),
                                        child: Padding(
                                          padding: const EdgeInsets.all(13),
                                          child: Text(
                                            message.content,
                                            style: const TextStyle(
                                              color: _ink,
                                              height: 1.45,
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                  );
                                },
                              ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(16, 6, 16, 12),
                        child: Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _input,
                                decoration: const InputDecoration(
                                  hintText: '想和左然聊聊这一章？',
                                  filled: true,
                                  fillColor: Colors.white,
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.all(
                                      Radius.circular(22),
                                    ),
                                    borderSide: BorderSide.none,
                                  ),
                                ),
                                onSubmitted: (_) => _discuss(),
                              ),
                            ),
                            IconButton(
                              onPressed: _sending ? null : _discuss,
                              icon: const Icon(
                                Icons.send_rounded,
                                color: _accent,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
  );
}

class _ExcerptCard extends StatelessWidget {
  const _ExcerptCard({required this.chunk});
  final ReadingChunk chunk;
  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .75),
      borderRadius: BorderRadius.circular(22),
    ),
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '第 ${chunk.index + 1} / ${chunk.total} 章',
            style: const TextStyle(color: _accent, fontWeight: FontWeight.w600),
          ),
          if (chunk.title.isNotEmpty) ...[
            const SizedBox(height: 5),
            Text(
              chunk.title,
              style: const TextStyle(
                color: _ink,
                fontSize: 18,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
          const SizedBox(height: 12),
          Text(
            chunk.preview,
            style: const TextStyle(color: _ink, height: 1.55),
          ),
        ],
      ),
    ),
  );
}

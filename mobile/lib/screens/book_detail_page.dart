import 'dart:async';
import 'package:flutter/material.dart';
import '../models/library_book.dart';
import '../services/libra_api.dart';
import '../widgets/reading_room_background.dart';

const _accent = Color(0xFFE77E82),
    _ink = Color(0xFF524849),
    _muted = Color(0xFF9B8B89);

class BookLibraryTile extends StatelessWidget {
  const BookLibraryTile({super.key, required this.book, required this.onTap});
  final LibraryBook book;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white.withValues(alpha: .85),
    borderRadius: BorderRadius.circular(22),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(22),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            Container(
              width: 54,
              height: 72,
              decoration: BoxDecoration(
                color: const Color(0xFFF8E1DE),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Icon(
                Icons.auto_stories_outlined,
                color: _accent,
                size: 28,
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    book.title,
                    style: const TextStyle(
                      fontSize: 16,
                      color: _ink,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  if (book.author.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Text(
                      book.author,
                      style: const TextStyle(color: _muted, fontSize: 12),
                    ),
                  ],
                  const SizedBox(height: 8),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(5),
                    child: LinearProgressIndicator(
                      value: book.status == 'read' ? 1 : book.progress / 100,
                      color: _accent,
                      backgroundColor: const Color(0xFFF4E8E5),
                      minHeight: 4,
                    ),
                  ),
                  const SizedBox(height: 5),
                  Text(
                    book.progressLabel,
                    style: const TextStyle(color: _muted, fontSize: 11),
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

class BookDetailPage extends StatefulWidget {
  const BookDetailPage({super.key, required this.book, required this.api});
  final LibraryBook book;
  final LibraApi api;
  @override
  State<BookDetailPage> createState() => _BookDetailPageState();
}

class _BookDetailPageState extends State<BookDetailPage> {
  late LibraryBook _book = widget.book;
  Timer? _timer;
  bool _fetching = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _reload());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _reload() async {
    if (_fetching) return;
    _fetching = true;
    try {
      final books = await widget.api.getBookLibrary();
      if (!mounted) return;
      final matches = books.where((book) => book.id == _book.id);
      setState(() {
        if (matches.isNotEmpty) _book = matches.first;
        _error = matches.isEmpty ? '这本书暂时无法刷新，已保留当前内容' : null;
      });
    } catch (_) {
      if (mounted) setState(() => _error = '暂时无法刷新，下拉重试');
    } finally {
      _fetching = false;
    }
  }

  @override
  Widget build(BuildContext context) => ReadingRoomBackground(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        foregroundColor: _ink,
        elevation: 0,
        title: const Text('阅读手记'),
      ),
      body: RefreshIndicator(
        onRefresh: _reload,
        color: _accent,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(22),
          children: [
            const Icon(Icons.auto_stories_outlined, size: 48, color: _accent),
            const SizedBox(height: 16),
            Text(
              _book.title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: _ink,
                fontSize: 24,
                fontWeight: FontWeight.w700,
              ),
            ),
            if (_book.author.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                _book.author,
                textAlign: TextAlign.center,
                style: const TextStyle(color: _muted),
              ),
            ],
            const SizedBox(height: 8),
            Text(
              _book.progressLabel,
              textAlign: TextAlign.center,
              style: const TextStyle(color: _muted, fontSize: 12),
            ),
            if (_book.chapter.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                _book.chapter,
                textAlign: TextAlign.center,
                style: const TextStyle(color: _muted, fontSize: 12),
              ),
            ],
            if (_book.scopeNote.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                _book.scopeNote,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: _muted,
                  fontSize: 12,
                  height: 1.6,
                ),
              ),
            ],
            if (_error != null)
              TextButton(onPressed: _reload, child: Text(_error!)),
            const SizedBox(height: 24),
            _heading('左然写的简介'),
            _card([
              Text(
                _book.introduction.isNotEmpty
                    ? _book.introduction
                    : _book.introductionStatus == 'retry'
                    ? '简介暂时未能写好，稍后会补上。'
                    : '正在整理这本书的简介…',
              ),
            ]),
            const SizedBox(height: 18),
            _heading('留下的句子'),
            if (_book.quotes.isEmpty)
              _card([const Text('还没有摘录\n遇到值得留下的句子，再慢慢记下来。')]),
            for (final quote in _book.quotes)
              _card([
                SelectableText('“${quote.text}”'),
                if (quote.translation.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  SelectableText(
                    quote.translation,
                    style: const TextStyle(color: _muted),
                  ),
                ],
                if (quote.thought.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  SelectableText(quote.thought),
                ],
              ]),
          ],
        ),
      ),
    ),
  );

  Widget _heading(String text) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: Text(
      text,
      style: const TextStyle(
        color: _ink,
        fontSize: 18,
        fontWeight: FontWeight.w600,
      ),
    ),
  );

  Widget _card(List<Widget> children) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .87),
      borderRadius: BorderRadius.circular(20),
    ),
    child: DefaultTextStyle(
      style: const TextStyle(color: _ink, height: 1.8, fontSize: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    ),
  );
}

import 'dart:async';

import 'package:flutter/material.dart';

import '../models/library_book.dart';
import 'book_detail_page.dart';
import '../services/libra_api.dart';
import '../widgets/reading_room_background.dart';

const _accent = Color(0xFFE77E82);
const _ink = Color(0xFF524849);
const _muted = Color(0xFF9B8B89);

class BookLibraryPage extends StatefulWidget {
  const BookLibraryPage({super.key, this.api});
  final LibraApi? api;

  @override
  State<BookLibraryPage> createState() => _BookLibraryPageState();
}

class _BookLibraryPageState extends State<BookLibraryPage> {
  late final LibraApi _api = widget.api ?? LibraApi();
  final _searchController = TextEditingController();
  List<LibraryBook> _books = const [];
  bool _loading = true;
  bool _fetching = false;
  bool _failed = false;
  Timer? _refresh;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _refresh?.cancel();
    _searchController.dispose();
    if (widget.api == null) _api.close();
    super.dispose();
  }

  List<LibraryBook> get _visibleBooks {
    final query = _searchController.text.trim().toLowerCase();
    if (query.isEmpty) return _books;
    return _books
        .where(
          (book) =>
              book.title.toLowerCase().contains(query) ||
              book.author.toLowerCase().contains(query),
        )
        .toList();
  }

  Future<void> _showImportDialog() async {
    final added = await showDialog<bool>(
      context: context,
      builder: (_) => _ImportBookDialog(api: _api),
    );
    if (added == true && mounted) await _load();
  }

  Future<void> _load() async {
    if (_fetching) return;
    _fetching = true;
    _refresh?.cancel();
    try {
      final books = await _api.getBookLibrary();
      if (!mounted) return;
      setState(() {
        _books = books;
        _failed = false;
      });
      if (books.any((book) => book.introduction.isEmpty)) {
        _refresh = Timer(const Duration(seconds: 15), () => unawaited(_load()));
      }
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    } finally {
      _fetching = false;
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => ReadingRoomBackground(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        iconTheme: const IconThemeData(color: _accent),
        foregroundColor: _ink,
        title: const Text(
          '左然的书库',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
        actions: [
          TextButton.icon(
            onPressed: _showImportDialog,
            icon: const Icon(Icons.add_rounded),
            label: const Text('导入'),
            style: TextButton.styleFrom(foregroundColor: _accent),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator(color: _accent))
          : RefreshIndicator(
              onRefresh: _load,
              color: _accent,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
                children: [
                  TextField(
                    controller: _searchController,
                    onChanged: (_) => setState(() {}),
                    decoration: InputDecoration(
                      hintText: '搜索书名或作者',
                      prefixIcon: const Icon(
                        Icons.search_rounded,
                        color: _accent,
                      ),
                      suffixIcon: _searchController.text.isEmpty
                          ? null
                          : IconButton(
                              icon: const Icon(Icons.close_rounded),
                              onPressed: () {
                                _searchController.clear();
                                setState(() {});
                              },
                            ),
                      filled: true,
                      fillColor: Colors.white.withValues(alpha: .85),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(20),
                        borderSide: BorderSide.none,
                      ),
                    ),
                  ),
                  const SizedBox(height: 18),
                  if (_failed) ...[
                    const Text(
                      '书库暂时无法刷新，请稍后重试',
                      style: TextStyle(color: _muted),
                    ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(
                        onPressed: _load,
                        child: const Text('重新加载'),
                      ),
                    ),
                  ],
                  if (_books.isEmpty && !_failed)
                    const Padding(
                      padding: EdgeInsets.only(top: 140),
                      child: Center(
                        child: Text(
                          '书架上暂时还没有书',
                          style: TextStyle(color: _muted),
                        ),
                      ),
                    ),
                  if (_books.isNotEmpty) ...[
                    Padding(
                      padding: const EdgeInsets.only(bottom: 16),
                      child: Text(
                        _searchController.text.trim().isEmpty
                            ? '共 ${_books.length} 本 · 他的阅读与随想'
                            : '找到 ${_visibleBooks.length} 本书',
                        style: const TextStyle(color: _muted),
                      ),
                    ),
                    if (_visibleBooks.isEmpty)
                      const Padding(
                        padding: EdgeInsets.only(top: 48),
                        child: Center(
                          child: Text(
                            '没有找到这本书',
                            style: TextStyle(color: _muted),
                          ),
                        ),
                      ),
                    for (final book in _visibleBooks)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: BookLibraryTile(
                          key: ValueKey(book.id),
                          book: book,
                          onTap: () async {
                            await Navigator.of(context).push(
                              MaterialPageRoute<void>(
                                builder: (_) =>
                                    BookDetailPage(book: book, api: _api),
                              ),
                            );
                            if (mounted) await _load();
                          },
                        ),
                      ),
                  ],
                ],
              ),
            ),
    ),
  );
}

class _ImportBookDialog extends StatefulWidget {
  const _ImportBookDialog({required this.api});
  final LibraApi api;

  @override
  State<_ImportBookDialog> createState() => _ImportBookDialogState();
}

class _ImportBookDialogState extends State<_ImportBookDialog> {
  final _title = TextEditingController();
  final _author = TextEditingController();
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _title.dispose();
    _author.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final title = _title.text.trim();
    final author = _author.text.trim();
    if (title.isEmpty || author.isEmpty) {
      setState(() => _error = '请填写书名和作者');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await widget.api.addBookToLibrary(title: title, author: author);
      if (mounted) Navigator.pop(context, true);
    } catch (error) {
      if (mounted) {
        setState(() {
          _submitting = false;
          _error = '导入失败：$error';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('导入书籍'),
    content: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: _title,
          autofocus: true,
          maxLength: 200,
          decoration: const InputDecoration(labelText: '书名'),
        ),
        TextField(
          controller: _author,
          maxLength: 100,
          decoration: const InputDecoration(labelText: '作者'),
        ),
        if (_error != null)
          Text(_error!, style: const TextStyle(color: _accent)),
      ],
    ),
    actions: [
      TextButton(
        onPressed: _submitting ? null : () => Navigator.pop(context, false),
        child: const Text('取消'),
      ),
      FilledButton(
        onPressed: _submitting ? null : _submit,
        child: const Text('加入书库'),
      ),
    ],
  );
}

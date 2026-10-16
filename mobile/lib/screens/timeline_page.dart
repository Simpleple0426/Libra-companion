import 'dart:async';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:cached_network_image/cached_network_image.dart';

import '../config/api_config.dart';
import '../models/memory_item.dart';
import '../models/letter.dart';
import '../services/libra_api.dart';
import '../services/display_names.dart';
import 'diary_reading.dart';

const _ink = Color(0xFF514746);
const _rose = Color(0xFFDE776C);
const _paper = Color(0xFFFFF9F6);

class TimelinePage extends StatefulWidget {
  const TimelinePage({super.key, this.api, this.active = true});
  final LibraApi? api;
  final bool active;
  @override
  State<TimelinePage> createState() => _TimelinePageState();
}

class _MomentCommentsSheet extends StatefulWidget {
  const _MomentCommentsSheet({required this.api, required this.item});

  final LibraApi api;
  final SharedMemoryItem item;

  @override
  State<_MomentCommentsSheet> createState() => _MomentCommentsSheetState();
}

class _MomentCommentsSheetState extends State<_MomentCommentsSheet> {
  final _controller = TextEditingController();
  late List<MemoryComment> _comments;
  bool _sending = false;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _comments = [...widget.item.comments];
    _refreshTimer = Timer.periodic(
      const Duration(seconds: 3),
      (_) => _refreshComments(),
    );
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  Future<void> _refreshComments() async {
    try {
      final comments = await widget.api.getMomentComments(widget.item.id);
      if (!mounted) return;
      final oldIds = _comments.map((item) => item.id).toList();
      final newIds = comments.map((item) => item.id).toList();
      if (oldIds.length != newIds.length ||
          !oldIds.asMap().entries.every(
            (item) => item.value == newIds[item.key],
          )) {
        setState(() => _comments = comments);
      }
    } catch (_) {
      // Keep the visible comments and retry while the sheet remains open.
    }
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _sending) return;
    FocusScope.of(context).unfocus();
    setState(() => _sending = true);
    try {
      final comment = await widget.api.commentOnMoment(widget.item.id, text);
      if (!mounted) return;
      _controller.clear();
      setState(() => _comments = [..._comments, comment]);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 18,
        right: 18,
        top: 12,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 16,
      ),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * .68,
        child: Column(
          children: [
            Row(
              children: [
                const Text(
                  '评论',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: _ink,
                  ),
                ),
                const Spacer(),
                IconButton(
                  onPressed: _sending ? null : () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(16),
              ),
              child: Text(
                widget.item.content,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: _ink, height: 1.5),
              ),
            ),
            const SizedBox(height: 12),
            Expanded(
              child: _comments.isEmpty
                  ? const Center(
                      child: Text(
                        '还没有评论，来留下第一句吧',
                        style: TextStyle(color: Color(0xFF9A7D79)),
                      ),
                    )
                  : ListView.separated(
                      itemCount: _comments.length,
                      separatorBuilder: (_, _) => const Divider(height: 18),
                      itemBuilder: (_, index) {
                        final comment = _comments[index];
                        return Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            CircleAvatar(
                              radius: 16,
                              backgroundColor: comment.author == 'libra'
                                  ? const Color(0xFFFFD6D1)
                                  : const Color(0xFFE8E3E1),
                              child: Text(
                                comment.author == 'libra'
                                    ? DisplayNames.libra.characters.first
                                    : DisplayNames.user.characters.first,
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: _ink,
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    comment.author == 'libra'
                                        ? DisplayNames.libra
                                        : DisplayNames.user,
                                    style: const TextStyle(
                                      fontSize: 12,
                                      fontWeight: FontWeight.w700,
                                      color: _rose,
                                    ),
                                  ),
                                  const SizedBox(height: 3),
                                  Text(
                                    comment.content,
                                    style: const TextStyle(
                                      fontSize: 14,
                                      height: 1.45,
                                      color: _ink,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        );
                      },
                    ),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    enabled: !_sending,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _send(),
                    decoration: const InputDecoration(
                      hintText: '写下评论……',
                      filled: true,
                      fillColor: Colors.white,
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.all(Radius.circular(18)),
                        borderSide: BorderSide.none,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  onPressed: _sending ? null : _send,
                  style: IconButton.styleFrom(backgroundColor: _rose),
                  icon: _sending
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.send_rounded),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ComposeLetterDialog extends StatefulWidget {
  const _ComposeLetterDialog({
    this.title,
    this.hintText = '有些话，可以慢慢写……',
    this.actionLabel = '寄出',
  });

  final String? title;
  final String hintText;
  final String actionLabel;

  @override
  State<_ComposeLetterDialog> createState() => _ComposeLetterDialogState();
}

class _ComposeLetterDialogState extends State<_ComposeLetterDialog> {
  final _content = TextEditingController();

  @override
  void dispose() {
    _content.dispose();
    super.dispose();
  }

  void _send() {
    final body = _content.text.trim();
    if (body.isEmpty) return;
    FocusScope.of(context).unfocus();
    Navigator.of(context).pop(body);
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    backgroundColor: _paper,
    title: Text(widget.title ?? '写给${DisplayNames.libra}'),
    content: SizedBox(
      width: 430,
      child: TextField(
        controller: _content,
        autofocus: true,
        minLines: 8,
        maxLines: 14,
        textInputAction: TextInputAction.newline,
        decoration: InputDecoration(
          hintText: widget.hintText,
          border: const OutlineInputBorder(),
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.of(context).pop(),
        child: const Text('取消'),
      ),
      FilledButton(onPressed: _send, child: Text(widget.actionLabel)),
    ],
  );
}

class _TimelinePageState extends State<TimelinePage> with WidgetsBindingObserver {
  late final _api = widget.api ?? LibraApi();
  final _picker = ImagePicker();
  final _searchController = TextEditingController();
  List<SharedMemoryItem> _items = const [];
  List<Letter> _letters = const [];
  bool _loading = true,
      _uploading = false,
      _album = false,
      _lettersTab = false,
      _favoritesOnly = false,
      _albumGrid = false;
  String _noteSection = 'moment';
  DateTime? _momentDate;
  DateTime? _diaryDate;
  String? _error;
  final Set<int> _expandedCommentItems = <int>{};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void didUpdateWidget(covariant TimelinePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) _load();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && widget.active) _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _searchController.dispose();
    if (widget.api == null) _api.close();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      if (_lettersTab) {
        final letters = await _api.getLetters();
        if (mounted) setState(() => _letters = letters);
        return;
      }
      final values = await _api.getSharedMemories(
        type: _album ? 'photo' : null,
      );
      if (mounted) {
        setState(() {
          _items = _album
              ? values
              : values.where((item) => !item.isPhoto).toList();
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _addPhoto() async {
    if (_uploading) return;
    setState(() => _uploading = true);
    try {
      final image = await _picker.pickImage(source: ImageSource.gallery);
      if (image == null || !mounted) return;
      await _api.uploadSharedMemoryPhoto(image.path);
      await _load();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    } finally {
      if (mounted) {
        setState(() => _uploading = false);
      }
    }
  }

  Future<void> _remove(SharedMemoryItem item) async {
    try {
      await _api.deleteSharedMemory(item.id);
      if (mounted) {
        setState(
          () => _items = _items.where((value) => value.id != item.id).toList(),
        );
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  Future<void> _editLocation(SharedMemoryItem item) async {
    final controller = TextEditingController(text: item.location ?? '');
    final location = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: _paper,
        title: const Text('照片地点'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            hintText: '例如：上海、杭州西湖',
            prefixIcon: Icon(Icons.location_on_outlined),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, ''),
            child: const Text('清除地点'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, controller.text),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (location == null) return;
    try {
      final updated = await _api.updateSharedMemoryLocation(item.id, location);
      if (mounted) {
        setState(() {
          _items = _items
              .map((value) => value.id == item.id ? updated : value)
              .toList();
        });
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: Colors.transparent,
    child: Column(
      children: [
        _header(),
        Expanded(child: _body()),
      ],
    ),
  );

  Widget _header() => Padding(
    padding: const EdgeInsets.fromLTRB(18, 8, 14, 8),
    child: SizedBox(
      height: 52,
      child: LayoutBuilder(
        builder: (context, constraints) => Row(
          children: [
            SizedBox(
              width: constraints.maxWidth * .36,
              child: const FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'MOMENTS',
                      style: TextStyle(
                        color: _rose,
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 4,
                      ),
                    ),
                    SizedBox(width: 7),
                    Icon(Icons.photo_library_outlined, color: _rose, size: 17),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Row(
                children: [
                  Expanded(child: _tab('手记', !_album && !_lettersTab, 'notes')),
                  Expanded(child: _tab('相册', _album, 'album')),
                  Expanded(child: _tab('信件', _lettersTab, 'letters')),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _tab(String text, bool active, String section) => InkWell(
    onTap: () {
      if (active) return;
      setState(() {
        _album = section == 'album';
        _lettersTab = section == 'letters';
        if (!_lettersTab) _favoritesOnly = false;
      });
      _load();
    },
    borderRadius: BorderRadius.circular(10),
    child: Padding(
      padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 12),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: TextStyle(
          fontSize: 14,
          fontWeight: active ? FontWeight.w700 : FontWeight.w500,
          color: active ? _rose : const Color(0xFF9A7D79),
        ),
      ),
    ),
  );

  Widget _body() {
    if (!_album && !_lettersTab && _noteSection == 'review') {
      return Column(
        children: [
          _noteSectionBar(),
          Expanded(child: ReviewReading(api: _api)),
        ],
      );
    }
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: _rose));
    }
    if (_error != null) {
      return Center(
        child: TextButton(onPressed: _load, child: const Text('加载失败，点此重试')),
      );
    }
    if (_lettersTab) return _lettersBody();
    if (_album && _items.isEmpty) return _empty();
    if (_album) {
      final photos = _filteredPhotos;
      return Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 2),
            child: Row(
              children: [
                if (_albumGrid)
                  Expanded(
                    child: TextField(
                      controller: _searchController,
                      onChanged: (_) => setState(() {}),
                      decoration: InputDecoration(
                        hintText: '搜索城市或地点',
                        prefixIcon: const Icon(Icons.search, size: 21),
                        suffixIcon: _searchController.text.isEmpty
                            ? null
                            : IconButton(
                                onPressed: () {
                                  _searchController.clear();
                                  setState(() {});
                                },
                                icon: const Icon(Icons.close, size: 19),
                              ),
                        filled: true,
                        fillColor: Colors.white.withValues(alpha: .76),
                        isDense: true,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(18),
                          borderSide: BorderSide.none,
                        ),
                      ),
                    ),
                  )
                else
                  const Expanded(
                    child: Text(
                      '按加入相册的顺序',
                      style: TextStyle(fontSize: 13, color: Color(0xFF9A7D79)),
                    ),
                  ),
                const SizedBox(width: 8),
                _viewToggle(),
                const SizedBox(width: 6),
                IconButton(
                  tooltip: '添加到共享相册',
                  onPressed: _uploading ? null : _addPhoto,
                  style: IconButton.styleFrom(
                    backgroundColor: Colors.white.withValues(alpha: .76),
                  ),
                  icon: _uploading
                      ? const SizedBox.square(
                          dimension: 19,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(
                          Icons.add_photo_alternate_outlined,
                          color: _rose,
                        ),
                ),
              ],
            ),
          ),
          Expanded(
            child: photos.isEmpty
                ? const Center(
                    child: Text(
                      '没有找到这个地点的照片',
                      style: TextStyle(color: Color(0xFF9A7D79)),
                    ),
                  )
                : _albumGrid
                ? RefreshIndicator(
                    onRefresh: _load,
                    child: GridView.builder(
                      padding: const EdgeInsets.all(12),
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                            crossAxisCount: 2,
                            mainAxisSpacing: 10,
                            crossAxisSpacing: 10,
                            childAspectRatio: .74,
                          ),
                      itemCount: photos.length,
                      itemBuilder: (_, i) =>
                          _photoCard(photos[i], compact: true),
                    ),
                  )
                : RefreshIndicator(
                    onRefresh: _load,
                    child: ListView.builder(
                      padding: const EdgeInsets.fromLTRB(14, 12, 14, 28),
                      itemCount: photos.length,
                      itemBuilder: (_, i) => Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: _photoCard(photos[i]),
                      ),
                    ),
                  ),
          ),
        ],
      );
    }
    final selectedDate = _noteSection == 'moment' ? _momentDate : _diaryDate;
    final notes = _items.where((item) {
      if (item.type != _noteSection) return false;
      return selectedDate == null ||
          DateUtils.isSameDay(item.eventDate, selectedDate);
    }).toList();
    return Column(
      children: [
        _noteSectionBar(),
        _noteDateFilter(selectedDate),
        Expanded(
          child: notes.isEmpty
              ? _noteEmpty()
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.builder(
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
                    itemCount: notes.length,
                    itemBuilder: (_, i) => _timelineCard(notes[i]),
                  ),
                ),
        ),
      ],
    );
  }

  Widget _lettersBody() => Column(
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(14, 4, 10, 0),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            TextButton.icon(
              onPressed: _composeLetter,
              icon: const Icon(Icons.edit_outlined, size: 18),
              label: const Text('写信'),
              style: TextButton.styleFrom(
                foregroundColor: const Color(0xFF9A7D79),
              ),
            ),
            TextButton.icon(
              onPressed: () => setState(() => _favoritesOnly = !_favoritesOnly),
              icon: Icon(
                _favoritesOnly ? Icons.star_rounded : Icons.star_border_rounded,
                size: 19,
              ),
              label: Text(_favoritesOnly ? '全部' : '收藏'),
              style: TextButton.styleFrom(
                foregroundColor: _favoritesOnly
                    ? _rose
                    : const Color(0xFF9A7D79),
              ),
            ),
          ],
        ),
      ),
      Expanded(
        child: _rootLetters.isEmpty
            ? Center(
                child: Text(
                  _favoritesOnly ? '还没有收藏的信件' : '信箱还是空的\n写一封想认真说的话吧',
                  textAlign: TextAlign.center,
                  style: const TextStyle(height: 1.7, color: Color(0xFF9A7D79)),
                ),
              )
            : RefreshIndicator(
                onRefresh: _load,
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(14, 4, 14, 28),
                  itemCount: _rootLetters.length,
                  itemBuilder: (_, index) => _letterCard(_rootLetters[index]),
                ),
              ),
      ),
    ],
  );

  List<Letter> get _rootLetters => _letters.where((letter) {
    if (letter.replyToId != null &&
        _letters.any((item) => item.id == letter.replyToId)) {
      return false;
    }
    if (!_favoritesOnly) return true;
    return letter.favorite;
  }).toList();

  List<Letter> _repliesTo(int letterId) =>
      Letter.repliesInThread(_letters, letterId);

  String _letterSenderLabel(Letter letter) =>
      letter.isMine ? '我的信' : '${DisplayNames.libra}的信';

  Widget _letterCard(Letter letter) {
    final mine = letter.isMine;
    final replies = _repliesTo(letter.id);
    final hasUnread = letter.isUnread || replies.any((reply) => reply.isUnread);
    final date = letter.createdAt.toLocal();
    final dateText =
        '${date.month}月${date.day}日  ${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: GestureDetector(
        onTap: () => _openLetter(letter),
        child: Container(
          width: MediaQuery.sizeOf(context).width * .78,
          margin: const EdgeInsets.only(bottom: 14),
          padding: const EdgeInsets.fromLTRB(17, 15, 17, 14),
          decoration: BoxDecoration(
            color: mine
                ? const Color(0xFFFFE6E1).withValues(alpha: .82)
                : Colors.white.withValues(alpha: .78),
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(20),
              topRight: const Radius.circular(20),
              bottomLeft: Radius.circular(mine ? 20 : 5),
              bottomRight: Radius.circular(mine ? 5 : 20),
            ),
            border: Border.all(
              color: hasUnread ? _rose : const Color(0xFFF0E4E1),
              width: hasUnread ? 1.4 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                _letterSenderLabel(letter),
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: _rose,
                ),
              ),
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      letter.content,
                      maxLines: 4,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14,
                        height: 1.55,
                        color: Color(0xFF6F6260),
                      ),
                    ),
                  ),
                  if (hasUnread)
                    Padding(
                      padding: const EdgeInsets.only(left: 10, top: 4),
                      child: Container(
                        width: 8,
                        height: 8,
                        decoration: const BoxDecoration(
                          color: _rose,
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  IconButton(
                    tooltip: letter.favorite ? '取消收藏' : '收藏',
                    visualDensity: VisualDensity.compact,
                    padding: const EdgeInsets.only(right: 6),
                    constraints: const BoxConstraints(
                      minWidth: 34,
                      minHeight: 34,
                    ),
                    onPressed: () => _toggleLetterFavorite(letter),
                    icon: Icon(
                      letter.favorite
                          ? Icons.star_rounded
                          : Icons.star_border_rounded,
                      size: 19,
                      color: letter.favorite ? _rose : const Color(0xFFB3A5A2),
                    ),
                  ),
                  Text(
                    dateText,
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFFB3A5A2),
                    ),
                  ),
                  const Spacer(),
                  if (replies.isNotEmpty)
                    Text(
                      '已有回信',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: hasUnread ? _rose : const Color(0xFF9A7D79),
                      ),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _composeLetter() async {
    final body = await showDialog<String>(
      context: context,
      builder: (_) => const _ComposeLetterDialog(),
    );
    if (body == null || body.isEmpty) return;
    try {
      final letter = await _api.sendLetter(content: body);
      if (!mounted) return;
      setState(() => _letters = [letter, ..._letters]);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('信已经寄出，${DisplayNames.libra}会认真回信')),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  Future<Letter?> _replyToLetter(int letterId, String content) async {
    try {
      final reply = await _api.sendLetter(
        content: content,
        replyToId: letterId,
      );
      if (mounted) {
        setState(() => _letters = [..._letters, reply]);
      }
      return reply;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
      return null;
    }
  }

  Future<void> _openLetter(Letter letter) async {
    var current = letter;
    var replies = _repliesTo(letter.id);
    final unread = [letter, ...replies].where((item) => item.isUnread).toList();
    if (unread.isNotEmpty) {
      try {
        for (final item in unread) {
          final updated = await _api.markLetterRead(item.id);
          if (updated.id == current.id) current = updated;
          replies = replies
              .map((reply) => reply.id == updated.id ? updated : reply)
              .toList();
          _letters = _letters
              .map((value) => value.id == updated.id ? updated : value)
              .toList();
        }
        if (mounted) {
          setState(() {});
        }
      } catch (_) {}
    }
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          backgroundColor: _paper,
          title: Row(
            children: [
              Text(_letterSenderLabel(current)),
              const Spacer(),
              IconButton(
                tooltip: current.favorite ? '取消收藏' : '收藏',
                onPressed: () async {
                  final updated = await _toggleLetterFavorite(current);
                  if (updated != null && dialogContext.mounted) {
                    setDialogState(() => current = updated);
                  }
                },
                icon: Icon(
                  current.favorite
                      ? Icons.star_rounded
                      : Icons.star_border_rounded,
                  color: current.favorite ? _rose : const Color(0xFF9A7D79),
                ),
              ),
            ],
          ),
          content: SingleChildScrollView(
            child: SizedBox(
              width: 440,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    current.content,
                    style: const TextStyle(
                      fontSize: 15,
                      height: 1.8,
                      color: _ink,
                    ),
                  ),
                  for (final reply in replies) ...[
                    Padding(
                      padding: EdgeInsets.symmetric(vertical: 22),
                      child: Row(
                        children: [
                          Expanded(child: Divider(color: Color(0xFFE9C8C3))),
                          Padding(
                            padding: EdgeInsets.symmetric(horizontal: 12),
                            child: Text(
                              _letterSenderLabel(reply),
                              style: TextStyle(fontSize: 12, color: _rose),
                            ),
                          ),
                          Expanded(child: Divider(color: Color(0xFFE9C8C3))),
                        ],
                      ),
                    ),
                    Text(
                      reply.content,
                      style: const TextStyle(
                        fontSize: 15,
                        height: 1.8,
                        color: _ink,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () async {
                final body = await showDialog<String>(
                  context: dialogContext,
                  builder: (_) => _ComposeLetterDialog(
                    title: '回复${DisplayNames.libra}',
                    hintText: '把想说的话写在这里……',
                    actionLabel: '回复',
                  ),
                );
                if (body == null || body.isEmpty) return;
                final reply = await _replyToLetter(
                  replies.isEmpty ? current.id : replies.last.id,
                  body,
                );
                if (reply != null && dialogContext.mounted) {
                  setDialogState(() => replies = [...replies, reply]);
                }
              },
              child: const Text('回复'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('收好'),
            ),
          ],
        ),
      ),
    );
  }

  Future<Letter?> _toggleLetterFavorite(Letter letter) async {
    try {
      final updated = await _api.setLetterFavorite(letter.id, !letter.favorite);
      if (mounted) {
        setState(() {
          _letters = _letters
              .map((item) => item.id == updated.id ? updated : item)
              .toList();
        });
      }
      return updated;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
      return null;
    }
  }

  Widget _noteSectionBar() => Padding(
    padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
    child: Container(
      padding: const EdgeInsets.all(5),
      decoration: BoxDecoration(
        color: const Color(0xFFF9EFEF).withValues(alpha: .84),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.white.withValues(alpha: .7)),
      ),
      child: Row(
        children: [
          Expanded(
            child: _noteSectionButton(
              type: 'moment',
              label: '动态',
              icon: Icons.format_quote_rounded,
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _noteSectionButton(
              type: 'diary',
              label: '日记',
              icon: Icons.menu_book_rounded,
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: _noteSectionButton(
              type: 'review',
              label: '回顾',
              icon: Icons.history_edu_outlined,
            ),
          ),
        ],
      ),
    ),
  );

  Widget _noteSectionButton({
    required String type,
    required String label,
    required IconData icon,
  }) {
    final active = _noteSection == type;
    return InkWell(
      onTap: () => setState(() => _noteSection = type),
      borderRadius: BorderRadius.circular(16),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
        decoration: BoxDecoration(
          color: active
              ? Colors.white.withValues(alpha: .95)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 19,
              color: active ? _rose : const Color(0xFF9BA8A3),
            ),
            const SizedBox(width: 8),
            Text(
              label,
              style: TextStyle(
                fontSize: 14,
                fontWeight: active ? FontWeight.w700 : FontWeight.w500,
                color: active ? _rose : const Color(0xFF9BA8A3),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _noteEmpty() => Center(
    child: Text(
      (_noteSection == 'moment' ? _momentDate : _diaryDate) != null
          ? '这一天没有${_noteSection == 'diary' ? '日记' : '动态'}'
          : _noteSection == 'diary'
          ? '还没有写下日记'
          : '还没有发布动态',
      style: const TextStyle(color: Color(0xFF9A7D79)),
    ),
  );

  Widget _noteDateFilter(DateTime? selectedDate) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
    child: Wrap(
      spacing: 8,
      runSpacing: 6,
      alignment: WrapAlignment.spaceBetween,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        InkWell(
          onTap: _pickNoteDate,
          borderRadius: BorderRadius.circular(14),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .78),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.calendar_month_outlined,
                  size: 17,
                  color: _rose,
                ),
                const SizedBox(width: 7),
                Text(
                  selectedDate == null
                      ? '按日期查找'
                      : '${selectedDate.year}年${selectedDate.month}月${selectedDate.day}日',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: selectedDate == null
                        ? FontWeight.w500
                        : FontWeight.w600,
                    color: selectedDate == null
                        ? const Color(0xFF9A7D79)
                        : _rose,
                  ),
                ),
              ],
            ),
          ),
        ),
        if (selectedDate != null) ...[
          const SizedBox(width: 6),
          TextButton(onPressed: _clearNoteDate, child: const Text('全部时间')),
        ],
        if (_noteSection == 'moment')
          FilledButton.icon(
            onPressed: _publishMoment,
            icon: const Icon(Icons.edit_outlined, size: 17),
            label: const Text('发动态'),
            style: FilledButton.styleFrom(
              backgroundColor: _rose,
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 12),
            ),
          ),
      ],
    ),
  );

  Future<void> _pickNoteDate() async {
    final current = _noteSection == 'moment' ? _momentDate : _diaryDate;
    final picked = await showDatePicker(
      context: context,
      initialDate: current ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now().add(const Duration(days: 365)),
      helpText: _noteSection == 'moment' ? '查找动态' : '查找日记',
    );
    if (picked == null || !mounted) return;
    setState(() {
      if (_noteSection == 'moment') {
        _momentDate = picked;
      } else {
        _diaryDate = picked;
      }
    });
  }

  void _clearNoteDate() {
    setState(() {
      if (_noteSection == 'moment') {
        _momentDate = null;
      } else {
        _diaryDate = null;
      }
    });
  }

  Future<void> _publishMoment() async {
    final content = await showDialog<String>(
      context: context,
      builder: (_) => const _ComposeLetterDialog(
        title: '发布动态',
        hintText: '这一刻，想和 Libra 说些什么……',
        actionLabel: '发布',
      ),
    );
    if (content == null || content.isEmpty) return;
    try {
      final moment = await _api.publishMoment(content);
      if (!mounted) return;
      setState(() {
        _momentDate = null;
        _items = [moment, ..._items];
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('动态已发布，Libra 稍后会来看看')));
      _refreshAfterLibraReply();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
      }
    }
  }

  void _refreshAfterLibraReply() {
    Future<void>.delayed(const Duration(seconds: 8), () {
      if (mounted && !_album && !_lettersTab) _load();
    });
    Future<void>.delayed(const Duration(seconds: 20), () {
      if (mounted && !_album && !_lettersTab) _load();
    });
  }

  Future<void> _showComments(SharedMemoryItem item) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: _paper,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (_) => _MomentCommentsSheet(api: _api, item: item),
    );
    if (mounted) await _load();
  }

  Widget _empty() => Center(
    child: Padding(
      padding: const EdgeInsets.all(36),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            _album ? Icons.photo_library_outlined : Icons.auto_stories_outlined,
            size: 48,
            color: const Color(0xFFD9AAA4),
          ),
          const SizedBox(height: 14),
          Text(
            _album ? '共享相册还是空的\n发给 Libra 的照片，会由他决定是否珍藏' : '手记会在相处中慢慢写下来',
            textAlign: TextAlign.center,
            style: const TextStyle(height: 1.6, color: Color(0xFF9A7D79)),
          ),
          if (_album)
            TextButton.icon(
              onPressed: _addPhoto,
              icon: const Icon(Icons.add),
              label: const Text('我来添加第一张'),
            ),
        ],
      ),
    ),
  );

  Widget _viewToggle() => Container(
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .78),
      borderRadius: BorderRadius.circular(14),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _viewButton(Icons.view_agenda_outlined, false, '按添加顺序'),
        _viewButton(Icons.grid_view_rounded, true, '文件视图'),
      ],
    ),
  );

  Widget _viewButton(IconData icon, bool grid, String tooltip) => IconButton(
    tooltip: tooltip,
    onPressed: () => setState(() => _albumGrid = grid),
    constraints: const BoxConstraints.tightFor(width: 38, height: 44),
    padding: EdgeInsets.zero,
    icon: Icon(
      icon,
      size: 20,
      color: _albumGrid == grid ? _rose : const Color(0xFFB7AAA8),
    ),
  );

  Widget _timelineCard(SharedMemoryItem item) {
    if (item.isPhoto) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 14),
        child: _photoCard(item),
      );
    }
    final diary = item.type == 'diary';
    final commentsExpanded = _expandedCommentItems.contains(item.id);
    final visibleComments = commentsExpanded
        ? item.comments
        : item.comments.take(2);
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(17),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: .78),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: Colors.white.withValues(alpha: .72)),
        boxShadow: const [
          BoxShadow(
            color: Color(0x10DE776C),
            blurRadius: 16,
            offset: Offset(0, 5),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          diary
                              ? Icons.menu_book_rounded
                              : Icons.format_quote_rounded,
                          size: 18,
                          color: _rose,
                        ),
                        const SizedBox(width: 7),
                        Expanded(
                          child: Text(
                            diary
                                ? '${DisplayNames.libra}的日记'
                                : item.author == 'libra'
                                ? '${DisplayNames.libra} · ${item.sourceLabel}'
                                : '${DisplayNames.user} · 动态',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              color: _rose,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      _date(item.eventDate),
                      style: const TextStyle(
                        fontSize: 11,
                        color: Color(0xFFB29E9B),
                      ),
                    ),
                  ],
                ),
              ),
              _menu(item),
            ],
          ),
          const SizedBox(height: 11),
          if ((item.sourceTitle ?? '').isNotEmpty) ...[
            Text(
              (item.sourceKind == 'walk_thought' ||
                      item.sourceKind == 'leisure_thought')
                  ? item.sourceTitle!
                  : '《${item.sourceTitle}》',
              style: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: _rose,
              ),
            ),
            const SizedBox(height: 8),
          ],
          Text(
            item.displayContent,
            style: TextStyle(
              fontSize: diary ? 15 : 16,
              height: 1.65,
              color: _ink,
            ),
          ),
          if ((item.sourceUrl ?? '').isNotEmpty) ...[
            const SizedBox(height: 10),
            SelectableText(
              '摘录来源：${item.sourceUrl}',
              style: const TextStyle(
                fontSize: 11,
                height: 1.4,
                color: Color(0xFF9B8580),
              ),
            ),
          ],
          if (!diary) ...[
            const SizedBox(height: 14),
            const Divider(height: 1, color: Color(0xFFF0E7E4)),
            if (item.comments.isNotEmpty) ...[
              const SizedBox(height: 10),
              for (final comment in visibleComments)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Text.rich(
                    TextSpan(
                      children: [
                        TextSpan(
                          text:
                              '${comment.author == 'libra' ? DisplayNames.libra : DisplayNames.user}：',
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            color: _rose,
                          ),
                        ),
                        TextSpan(
                          text: comment.content,
                          style: const TextStyle(color: _ink),
                        ),
                      ],
                    ),
                    maxLines: commentsExpanded ? null : 2,
                    overflow: commentsExpanded
                        ? TextOverflow.visible
                        : TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 12, height: 1.45),
                  ),
                ),
            ],
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                if (item.comments.length > 2)
                  TextButton(
                    onPressed: () => setState(() {
                      if (commentsExpanded) {
                        _expandedCommentItems.remove(item.id);
                      } else {
                        _expandedCommentItems.add(item.id);
                      }
                    }),
                    child: Text(
                      commentsExpanded
                          ? '收起'
                          : '查看全部 ${item.comments.length} 条评论',
                    ),
                  ),
                TextButton.icon(
                  onPressed: () => _showComments(item),
                  icon: const Icon(Icons.chat_bubble_outline_rounded, size: 16),
                  label: const Text('评论'),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _photoCard(
    SharedMemoryItem item, {
    bool compact = false,
  }) => GestureDetector(
    onTap: () => _showPhotoDetail(item),
    child: ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: Container(
        color: Colors.white.withValues(alpha: .8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (compact)
              Expanded(child: _memoryImage(item))
            else
              SizedBox(height: 230, child: _memoryImage(item)),
            Padding(
              padding: const EdgeInsets.fromLTRB(13, 10, 5, 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.content,
                          maxLines: compact ? 2 : 4,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 13,
                            height: 1.45,
                            color: _ink,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '${_date(item.eventDate)} · ${item.author == 'libra' ? '${DisplayNames.libra}收藏' : '${DisplayNames.user}添加的'}',
                          style: const TextStyle(
                            fontSize: 10,
                            color: Color(0xFFB29E9B),
                          ),
                        ),
                        if ((item.location ?? '').isNotEmpty) ...[
                          const SizedBox(height: 4),
                          Row(
                            children: [
                              const Icon(
                                Icons.location_on_outlined,
                                size: 12,
                                color: _rose,
                              ),
                              const SizedBox(width: 2),
                              Expanded(
                                child: Text(
                                  item.location!,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 10,
                                    color: _rose,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  _menu(item),
                ],
              ),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _memoryImage(SharedMemoryItem item) => CachedNetworkImage(
    imageUrl: '${ApiConfig.baseUrl}${item.thumbnailUrl}',
    width: double.infinity,
    height: double.infinity,
    fit: BoxFit.cover,
    fadeInDuration: const Duration(milliseconds: 120),
    placeholder: (_, _) => const ColoredBox(
      color: Color(0xFFF3ECE9),
      child: Center(
        child: CircularProgressIndicator(strokeWidth: 2, color: _rose),
      ),
    ),
    errorWidget: (_, _, _) =>
        const Center(child: Icon(Icons.broken_image_outlined)),
  );

  Future<void> _showPhotoDetail(SharedMemoryItem item) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: _paper,
      useSafeArea: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (sheetContext) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .92,
        minChildSize: .55,
        maxChildSize: .96,
        builder: (_, scrollController) => CustomScrollView(
          controller: scrollController,
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(18, 8, 10, 12),
                child: Row(
                  children: [
                    const Text(
                      '照片详情',
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: _ink,
                      ),
                    ),
                    const Spacer(),
                    IconButton(
                      onPressed: () => Navigator.pop(sheetContext),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
              ),
            ),
            SliverToBoxAdapter(
              child: ColoredBox(
                color: const Color(0xFFF1EBE8),
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    minHeight: 260,
                    maxHeight: MediaQuery.sizeOf(context).height * .55,
                  ),
                  child: CachedNetworkImage(
                    imageUrl: '${ApiConfig.baseUrl}${item.mediaUrl}',
                    fit: BoxFit.contain,
                    placeholder: (_, _) => const Center(
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: _rose,
                      ),
                    ),
                    errorWidget: (_, _, _) => const SizedBox(
                      height: 280,
                      child: Center(child: Icon(Icons.broken_image_outlined)),
                    ),
                  ),
                ),
              ),
            ),
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(20, 20, 20, 36),
              sliver: SliverList.list(
                children: [
                  Text(
                    item.content,
                    style: const TextStyle(
                      fontSize: 16,
                      height: 1.7,
                      color: _ink,
                    ),
                  ),
                  const SizedBox(height: 18),
                  _detailLine(
                    Icons.schedule_outlined,
                    '加入相册：${_date(item.createdAt)}',
                  ),
                  const SizedBox(height: 9),
                  _detailLine(
                    Icons.favorite_border_rounded,
                    item.author == 'libra'
                        ? '${DisplayNames.libra}收藏'
                        : '${DisplayNames.user}添加的',
                  ),
                  if ((item.location ?? '').isNotEmpty) ...[
                    const SizedBox(height: 9),
                    _detailLine(Icons.location_on_outlined, item.location!),
                  ],
                  if (item.takenAt != null) ...[
                    const SizedBox(height: 9),
                    _detailLine(
                      Icons.photo_camera_outlined,
                      '拍摄于 ${_date(item.takenAt!)}',
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _detailLine(IconData icon, String text) => Row(
    children: [
      Icon(icon, size: 17, color: _rose),
      const SizedBox(width: 8),
      Expanded(
        child: Text(
          text,
          style: const TextStyle(fontSize: 13, color: Color(0xFF9A7D79)),
        ),
      ),
    ],
  );

  Widget _menu(SharedMemoryItem item) => PopupMenuButton<String>(
    padding: EdgeInsets.zero,
    iconSize: 18,
    icon: const Icon(Icons.more_horiz, color: Color(0xFFB29E9B)),
    onSelected: (value) =>
        value == 'location' ? _editLocation(item) : _remove(item),
    itemBuilder: (_) => [
      if (item.isPhoto)
        const PopupMenuItem(value: 'location', child: Text('修改照片地点')),
      const PopupMenuItem(value: 'delete', child: Text('移除这条记录')),
    ],
  );
  List<SharedMemoryItem> get _filteredPhotos {
    final query = _albumGrid ? _searchController.text.trim().toLowerCase() : '';
    final photos = query.isEmpty
        ? [..._items]
        : _items
              .where(
                (item) => (item.location ?? '').toLowerCase().contains(query),
              )
              .toList();
    photos.sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return photos;
  }

  String _date(DateTime value) =>
      '${value.year}.${value.month.toString().padLeft(2, '0')}.${value.day.toString().padLeft(2, '0')}';
}

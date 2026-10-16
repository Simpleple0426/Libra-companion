import 'dart:async';
import 'package:flutter/material.dart';
import '../services/movie_room_api.dart';
import '../widgets/reading_room_background.dart';
import 'local_movie_player_page.dart';

const _accent = Color(0xFFE77E82),
    _ink = Color(0xFF524849),
    _muted = Color(0xFF9B8B89);
String _minutes(dynamic value) => '${((value as num?) ?? 0) ~/ 60} 分钟';
String _date(dynamic value) => '${value ?? ''}'.split('T').first;

class MovieLibraryPage extends StatefulWidget {
  const MovieLibraryPage({super.key, this.api});
  final MovieRoomApi? api;
  @override
  State<MovieLibraryPage> createState() => _MovieLibraryPageState();
}

class _MovieLibraryPageState extends State<MovieLibraryPage> {
  late final _api = widget.api ?? MovieRoomApi();
  List<Map<String, dynamic>> _solo = [], _shared = [];
  bool _loading = true;
  String? _error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    if (widget.api == null) _api.close();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final data = await _api.request('/library');
      if (!mounted) return;
      setState(() {
        _solo = (data['solo'] as List)
            .map((m) => Map<String, dynamic>.from(m as Map))
            .toList();
        _shared = (data['shared'] as List)
            .map((m) => Map<String, dynamic>.from(m as Map))
            .toList();
        _error = data['solo_available'] == false ? '左然的片单暂时无法读取，下拉重试' : null;
      });
    } catch (_) {
      if (mounted) setState(() => _error = '片单暂时无法读取，下拉重试');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => DefaultTabController(
    length: 2,
    child: ReadingRoomBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          surfaceTintColor: Colors.transparent,
          foregroundColor: _ink,
          elevation: 0,
          title: const Text(
            '电影清单',
            style: TextStyle(fontWeight: FontWeight.w700),
          ),
          actions: [
            IconButton(
              tooltip: '本地影片',
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const LocalMoviePlayerPage(),
                ),
              ),
              icon: const Icon(Icons.play_circle_outline, color: _accent),
            ),
          ],
          bottom: const TabBar(
            labelColor: _accent,
            unselectedLabelColor: _muted,
            indicatorColor: _accent,
            tabs: [
              Tab(text: '左然的片单'),
              Tab(text: '我们一起看'),
            ],
          ),
        ),
        body: _loading
            ? const Center(child: CircularProgressIndicator(color: _accent))
            : Column(
                children: [
                  if (_error != null)
                    TextButton(onPressed: _load, child: Text(_error!)),
                  Expanded(
                    child: TabBarView(
                      children: [_list(_solo, false), _list(_shared, true)],
                    ),
                  ),
                ],
              ),
      ),
    ),
  );
  Widget _list(List<Map<String, dynamic>> rows, bool shared) =>
      RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(20),
          children: [
            Text(
              shared ? '把一起度过的光影收藏起来' : '他的选择，和观影后的片刻想法',
              style: const TextStyle(color: _muted),
            ),
            const SizedBox(height: 18),
            if (rows.isEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 100),
                child: Center(
                  child: Text(
                    shared ? '开始一次电脑陪看\n这里会记下你们的电影与日期' : '片单还在慢慢积累',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: _muted, height: 1.8),
                  ),
                ),
              ),
            ...rows.map((row) => _tile(row, shared)),
          ],
        ),
      );
  Widget _tile(Map<String, dynamic> row, bool shared) {
    final duration = (row['duration'] as num?)?.toDouble() ?? 0;
    final position = (row['position'] as num?)?.toDouble() ?? 0;
    final done = shared
        ? row['status'] == 'completed'
        : row['completed'] == true;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Material(
        color: Colors.white.withValues(alpha: .85),
        borderRadius: BorderRadius.circular(22),
        child: InkWell(
          borderRadius: BorderRadius.circular(22),
          onTap: () async {
            await Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => MovieDetailPage(
                  movie: row,
                  shared: shared,
                  api: widget.api,
                ),
              ),
            );
            if (mounted) _load();
          },
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
                    Icons.movie_filter_outlined,
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
                        '${row['title']}',
                        style: const TextStyle(
                          fontSize: 16,
                          color: _ink,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        shared
                            ? '${_date(row['started_at'])} · ${done ? '已一起看完' : '一起看过'}'
                            : done
                            ? '已看完'
                            : position > 0
                            ? '观看中'
                            : '待看',
                        style: const TextStyle(color: _muted, fontSize: 12),
                      ),
                      const SizedBox(height: 8),
                      if (!shared && duration > 0)
                        ClipRRect(
                          borderRadius: BorderRadius.circular(5),
                          child: LinearProgressIndicator(
                            value: (position / duration).clamp(0, 1),
                            color: _accent,
                            backgroundColor: const Color(0xFFF4E8E5),
                            minHeight: 4,
                          ),
                        ),
                      const SizedBox(height: 5),
                      Text(
                        shared
                            ? row['position'] == null
                                  ? '尚未同步播放时间'
                                  : '上次看到 ${_minutes(position)}'
                            : '${_minutes(position)}${duration > 0 ? ' / ${_minutes(duration)}' : ''}',
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
      ),
    );
  }
}

class MovieDetailPage extends StatefulWidget {
  const MovieDetailPage({
    super.key,
    required this.movie,
    required this.shared,
    this.api,
  });
  final Map<String, dynamic> movie;
  final bool shared;
  final MovieRoomApi? api;
  @override
  State<MovieDetailPage> createState() => _MovieDetailPageState();
}

class _MovieDetailPageState extends State<MovieDetailPage> {
  late Map<String, dynamic> _movie = Map.of(widget.movie);
  late final _api = widget.api ?? MovieRoomApi();
  Timer? _timer;
  bool _busy = false;
  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (_movie['review_status'] == 'writing') _reload();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    if (widget.api == null) _api.close();
    super.dispose();
  }

  Future<void> _reload() async {
    try {
      final data = await _api.request('/library');
      final rows = data[widget.shared ? 'shared' : 'solo'] as List;
      final matches = rows.where((row) => row['id'] == _movie['id']);
      if (mounted && matches.isNotEmpty) {
        setState(
          () => _movie = Map<String, dynamic>.from(matches.first as Map),
        );
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('暂时无法刷新，请稍后再试')));
      }
    }
  }

  Future<void> _finish() async {
    if (_busy) return;
    if (_movie['status'] != 'completed') {
      final yes = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('这部电影看完了吗？'),
          content: const Text('会结束本次陪看，并请左然根据你们实际看到的内容写影评。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('还没看完'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('已看完'),
            ),
          ],
        ),
      );
      if (yes != true || !mounted) return;
    }
    setState(() => _busy = true);
    try {
      await _api.request(
        '/viewings/${Uri.encodeComponent('${_movie['id']}')}/finish',
        {},
      );
      await _reload();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('暂时未能完成，请稍后重试')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final quotes = (_movie['quotes'] as List?) ?? [];
    final reviews = widget.shared
        ? [
            if ('${_movie['review'] ?? ''}'.isNotEmpty)
              {'text': _movie['review'], 'date': _movie['updated_at']},
          ]
        : (_movie['reviews'] as List? ?? []);
    return ReadingRoomBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          surfaceTintColor: Colors.transparent,
          foregroundColor: _ink,
          elevation: 0,
          title: const Text('光影手记'),
        ),
        body: RefreshIndicator(
          onRefresh: _reload,
          child: ListView(
            padding: const EdgeInsets.all(22),
            children: [
              const Icon(Icons.local_movies_outlined, size: 48, color: _accent),
              const SizedBox(height: 16),
              Text(
                '${_movie['title']}',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: _ink,
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                widget.shared
                    ? '${_date(_movie['started_at'])} · 我们一起看'
                    : '左然的观影记录',
                textAlign: TextAlign.center,
                style: const TextStyle(color: _muted),
              ),
              if (!widget.shared)
                const Padding(
                  padding: EdgeInsets.only(top: 8),
                  child: Text(
                    '进度来自左然的生活记录',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: _muted, fontSize: 12),
                  ),
                ),
              const SizedBox(height: 24),
              const Text(
                '留下的句子',
                style: TextStyle(
                  color: _ink,
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 12),
              if (quotes.isEmpty) _card('还没有摘录\n遇到值得留下的句子，再慢慢记下来。'),
              ...quotes.map(
                (q) => _card('“${q['text']}”\n\n${q['thought'] ?? ''}'),
              ),
              const SizedBox(height: 18),
              const Text(
                '看完之后',
                style: TextStyle(
                  color: _ink,
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 12),
              if (reviews.isEmpty)
                _card(
                  _movie['review_status'] == 'writing'
                      ? '左然正在整理这次观影的感想…'
                      : _movie['review_status'] == 'error'
                      ? '影评暂未写成，可能还缺少足够的观影内容。'
                      : '影评会在看完后，留在这里。',
                ),
              ...reviews.map(
                (r) => _card('${r['text']}\n\n${_date(r['date'])}'),
              ),
              if (widget.shared && _movie['review_status'] != 'ready')
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: _accent),
                    onPressed: _busy || _movie['review_status'] == 'writing'
                        ? null
                        : _finish,
                    icon: const Icon(Icons.check_circle_outline),
                    label: Text(
                      _movie['status'] == 'completed' ? '请他再写一次影评' : '我们已经看完了',
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _card(String text) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .87),
      borderRadius: BorderRadius.circular(20),
    ),
    child: SelectableText(
      text,
      style: const TextStyle(color: _ink, height: 1.8),
    ),
  );
}

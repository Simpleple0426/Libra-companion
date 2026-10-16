import 'dart:async';
import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../config/api_config.dart';
import 'package:flutter/material.dart';
import '../services/movie_room_api.dart';
import '../widgets/reading_room_background.dart';
import 'movie_library_page.dart';

const movieAccent = Color(0xFFE77E82);
const movieInk = Color(0xFF524849);

class MovieRoomPage extends StatefulWidget {
  const MovieRoomPage({super.key, this.api});
  final MovieRoomApi? api;
  @override
  State<MovieRoomPage> createState() => _MovieRoomPageState();
}

class _MovieRoomPageState extends State<MovieRoomPage> {
  late final _api = widget.api ?? MovieRoomApi();
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<Map<String, dynamic>> _messages = [];
  final Map<String, Map<String, dynamic>> _pending = {};
  List<Map<String, dynamic>> get _visibleMessages => [
    ..._messages,
    if (_date == null) ..._pending.values,
  ];
  Map<String, dynamic>? _current;
  Timer? _timer;
  DateTime? _date;
  int? _before;
  bool _historyLoaded = false;
  bool _loading = true, _fetching = false, _sending = false;
  int _revision = 0;
  bool _restoring = true;
  late final String _outboxKey = 'movie_room_outbox:${ApiConfig.baseUrl}';
  String? _error, _requestId, _requestText, _requestViewing;

  @override
  void initState() {
    super.initState();
    _restore();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _load());
  }

  Future<void> _restore() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(_outboxKey);
      if (!mounted) return;
      if (saved != null) {
        final value = Map<String, dynamic>.from(jsonDecode(saved) as Map);
        _requestId = value['request_id'] as String;
        _requestText = value['content'] as String;
        _requestViewing = value['viewing_id'] as String?;
        _pending[_requestId!] = value;
        _loading = false;
      }
    } catch (error) {
      debugPrint('Movie outbox restore failed: $error');
    } finally {
      if (mounted) {
        setState(() => _restoring = false);
        _load();
      }
    }
  }

  Future<void> _finishRequest(String id) async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_outboxKey);
    if (saved != null && (jsonDecode(saved) as Map)['request_id'] == id) {
      if (!await prefs.remove(_outboxKey)) throw StateError('无法更新发送状态');
    }
    if (!mounted || _requestId != id) return;
    setState(() {
      _requestId = null;
      _requestText = null;
      _requestViewing = null;
      _sending = false;
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    _input.dispose();
    _scroll.dispose();
    if (widget.api == null) _api.close();
    super.dispose();
  }

  String _day(DateTime value) =>
      '${value.year}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';
  Future<void> _load({bool older = false}) async {
    if (_fetching || _restoring) return;
    _fetching = true;
    final revision = _revision;
    try {
      final query = <String, String>{
        if (_requestId != null) 'request_id': _requestId!,
        if (_date != null) 'date': _day(_date!),
        if (older && _before != null) 'before': '$_before',
      };
      final result = await _api.request(
        '/messages?${Uri(queryParameters: query).query}',
      );
      if (!mounted || revision != _revision) return;
      final state = result['request_state'] as Map?;
      final incoming = (result['messages'] as List).map(
        (m) => Map<String, dynamic>.from(m as Map),
      );
      setState(() {
        final merged = <int, Map<String, dynamic>>{
          for (final m in _messages) m['id'] as int: m,
        };
        for (final m in incoming) {
          _pending.remove(m['request_id']);
          merged[m['id'] as int] = m;
        }
        if (_date == null && state != null) {
          for (final item in state['messages'] as List) {
            final m = Map<String, dynamic>.from(item as Map);
            _pending.remove(m['request_id']);
            merged.putIfAbsent(m['id'] as int, () => m);
          }
        }
        _messages
          ..clear()
          ..addAll(merged.values);
        _messages.sort((a, b) => (a['id'] as int).compareTo(b['id'] as int));
        if (older || !_historyLoaded) {
          _before = result['next_before'] as int?;
        }
        _historyLoaded = true;
        _current = result['current'] == null
            ? null
            : Map<String, dynamic>.from(result['current'] as Map);
        _error = null;
      });
      if (state != null &&
          state['completed'] == true &&
          state['request_id'] == _requestId) {
        await _finishRequest(state['request_id'] as String);
      }
    } catch (error, stack) {
      debugPrint('Movie room refresh error: $error\n$stack');
      if (mounted && revision == _revision) {
        setState(
          () => _error = error is MovieRoomException
              ? '${error.message}，点此重试'
              : '电影室内容暂时无法显示，点此重试',
        );
      }
    } finally {
      _fetching = false;
      if (mounted) setState(() => _loading = false);
      if (mounted && revision != _revision) _load();
    }
  }

  Future<void> _chooseDate() async {
    final value = await showDatePicker(
      context: context,
      initialDate: _date ?? DateTime.now(),
      firstDate: DateTime(2022, 8, 22),
      lastDate: DateTime.now(),
      helpText: '查找观影聊天',
      cancelText: '取消',
      confirmText: '查看',
    );
    if (value == null || !mounted) return;
    setState(() {
      _date = value;
      _revision++;
      _before = null;
      _historyLoaded = false;
      _messages.clear();
      _loading = true;
    });
    _load();
  }

  Future<void> _send({bool retry = false}) async {
    final text = retry ? (_requestText ?? '') : _input.text.trim();
    if (text.isEmpty || _sending || _restoring) return;
    if (_requestId == null || _requestText != text) {
      _requestId = 'movie-${DateTime.now().microsecondsSinceEpoch}';
      _requestText = text;
      _requestViewing = _current?['id'] as String?;
    }
    setState(() {
      _sending = true;
      _pending.putIfAbsent(
        _requestId!,
        () => {
          'role': 'user',
          'content': text,
          'created_at': DateTime.now().toIso8601String(),
          'request_id': _requestId,
          'viewing_id': _requestViewing,
        },
      );
      _input.clear();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _scroll.hasClients) _scroll.jumpTo(0);
    });
    final sendingId = _requestId!;
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = await prefs.setString(
        _outboxKey,
        jsonEncode(
          _pending[sendingId] ??
              {
                'request_id': sendingId,
                'content': text,
                'role': 'user',
                'viewing_id': _requestViewing,
                'created_at': DateTime.now().toIso8601String(),
              },
        ),
      );
      if (!saved) throw StateError('消息暂时无法保存到手机');
      if (!mounted || _requestId != sendingId) return;
      await _api.request('/chat', {
        'message': text,
        'request_id': sendingId,
        'viewing_id': _requestViewing,
      });
      if (!mounted) return;
      await _finishRequest(sendingId);
      await _load();
      if (_scroll.hasClients) {
        _scroll.animateTo(
          0,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    } catch (_) {
      if (mounted && _requestId == sendingId) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('回复暂未完成，消息已保留；可点击重试')));
      }
    } finally {
      if (mounted && _requestId == sendingId) setState(() => _sending = false);
    }
  }

  @override
  Widget build(BuildContext context) => ReadingRoomBackground(
    child: Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        foregroundColor: movieInk,
        elevation: 0,
        title: const Text('电影室', style: TextStyle(fontWeight: FontWeight.w700)),
        actions: [
          IconButton(
            tooltip: '按天查找聊天',
            onPressed: _chooseDate,
            icon: const Icon(Icons.calendar_month_outlined, color: movieAccent),
          ),
          IconButton(
            tooltip: '电影清单',
            icon: const Icon(Icons.video_library_outlined, color: movieAccent),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => MovieLibraryPage(api: widget.api),
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        top: false,
        child: Column(
          children: [
            Container(
              margin: const EdgeInsets.fromLTRB(18, 8, 18, 12),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: .75),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                children: [
                  const Icon(Icons.movie_outlined, color: movieAccent),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _current == null
                              ? '留一盏灯，陪你看一部电影'
                              : '正在观看 · ${(_current!['title'] as String?)?.isNotEmpty == true ? _current!['title'] : '未命名电影'}',
                          style: const TextStyle(
                            color: movieInk,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(
                          _current?['paused'] == true
                              ? '陪看已暂停'
                              : '把关于电影的话，留在这里',
                          style: const TextStyle(
                            color: Color(0xFF9B8B89),
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            if (_date != null)
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(_day(_date!), style: const TextStyle(color: movieInk)),
                  TextButton(
                    onPressed: () {
                      setState(() {
                        _date = null;
                        _revision++;
                        _messages.clear();
                        _before = null;
                        _historyLoaded = false;
                      });
                      _load();
                    },
                    child: const Text('回到最近'),
                  ),
                ],
              ),
            if (_error != null)
              TextButton(onPressed: _load, child: Text(_error!)),
            Expanded(
              child: _loading
                  ? const Center(
                      child: CircularProgressIndicator(color: movieAccent),
                    )
                  : _visibleMessages.isEmpty
                  ? const Center(
                      child: Text(
                        '这一页还很安静\n开始陪看，或聊聊你想看的电影',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Color(0xFF9B8B89), height: 1.8),
                      ),
                    )
                  : ListView(
                      controller: _scroll,
                      reverse: true,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 18,
                        vertical: 8,
                      ),
                      children: [
                        ..._visibleMessages.reversed.map(_bubble),
                        if (_before != null)
                          TextButton(
                            onPressed: () => _load(older: true),
                            child: const Text('更早的观影聊天'),
                          ),
                      ],
                    ),
            ),
            if (_sending)
              const Padding(
                padding: EdgeInsets.all(6),
                child: Text(
                  '左然正在想怎么和你说…',
                  style: TextStyle(color: Color(0xFF9B8B89), fontSize: 12),
                ),
              ),
            if (!_sending && _requestId != null && _date == null)
              TextButton(
                onPressed: () => _send(retry: true),
                child: const Text('回复暂未完成，点击重试'),
              ),
            if (_date == null)
              Padding(
                padding: const EdgeInsets.fromLTRB(14, 8, 14, 12),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _input,
                        enabled: !_restoring && !_sending && _requestId == null,
                        minLines: 1,
                        maxLines: 4,
                        maxLength: 4000,
                        decoration: InputDecoration(
                          hintText: '和左然聊聊这部电影…',
                          counterText: '',
                          filled: true,
                          fillColor: Colors.white,
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(22),
                            borderSide: const BorderSide(
                              color: Color(0xFFF0E4E2),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton.filled(
                      style: IconButton.styleFrom(
                        backgroundColor: const Color(0xFFDE776C),
                      ),
                      tooltip: '发送',
                      onPressed: _restoring || _sending || _requestId != null
                          ? null
                          : () => _send(),
                      icon: const Icon(Icons.arrow_upward_rounded),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    ),
  );
  Widget _bubble(Map<String, dynamic> message) {
    final mine = message['role'] == 'user';
    final timestamp = DateTime.tryParse('${message['created_at']}');
    final label = timestamp == null
        ? ''
        : '${timestamp.month}月${timestamp.day}日 ${timestamp.hour.toString().padLeft(2, '0')}:${timestamp.minute.toString().padLeft(2, '0')}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Column(
        crossAxisAlignment: mine
            ? CrossAxisAlignment.end
            : CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 6, right: 6, bottom: 5),
            child: Text(
              '${mine ? '我' : '左然'} · $label',
              style: const TextStyle(color: Color(0xFF9B8B89), fontSize: 11),
            ),
          ),
          Container(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.sizeOf(context).width * .8,
            ),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: mine
                  ? const Color(0xE8FFD5D0)
                  : Colors.white.withValues(alpha: .88),
              border: Border.all(
                color: mine ? const Color(0xFFFFC7C1) : const Color(0xFFF2E8E6),
              ),
              boxShadow: [
                BoxShadow(
                  color:
                      (mine ? const Color(0xFFCE766C) : const Color(0xFF6F5551))
                          .withValues(alpha: mine ? .15 : .11),
                  blurRadius: 16,
                  spreadRadius: .3,
                  offset: const Offset(0, 5),
                ),
              ],
              borderRadius: BorderRadius.circular(18),
            ),
            child: SelectableText(
              '${message['content']}',
              style: const TextStyle(
                color: Color(0xFF292524),
                height: 1.6,
                fontSize: 15,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

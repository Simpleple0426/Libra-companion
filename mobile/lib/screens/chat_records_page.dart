import 'package:flutter/material.dart';

import '../config/api_config.dart';
import '../models/chat_message.dart';
import '../services/display_names.dart';
import '../services/libra_api.dart';

const _rose = Color(0xFFDE776C);
const _ink = Color(0xFF554B49);

class ChatSearchPage extends StatefulWidget {
  const ChatSearchPage({super.key});

  @override
  State<ChatSearchPage> createState() => _ChatSearchPageState();
}

class _ChatSearchPageState extends State<ChatSearchPage> {
  final _api = LibraApi();
  DateTime _date = DateUtils.dateOnly(DateTime.now());
  late Future<List<ChatMessage>> _messages = _api.getMessagesForDate(_date);

  @override
  void dispose() {
    _api.close();
    super.dispose();
  }

  Future<void> _chooseDate() async {
    final selected = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(2022, 8, 22),
      lastDate: DateUtils.dateOnly(DateTime.now()),
      helpText: '选择聊天日期',
      cancelText: '取消',
      confirmText: '查看',
    );
    if (selected == null || !mounted) return;
    setState(() {
      _date = selected;
      _messages = _api.getMessagesForDate(selected);
    });
  }

  @override
  Widget build(BuildContext context) => _RecordsScaffold(
    title: '查找聊天记录',
    action: TextButton.icon(
      onPressed: _chooseDate,
      icon: const Icon(Icons.calendar_month_rounded, size: 19),
      label: Text('${_date.month}月${_date.day}日'),
    ),
    messages: _messages,
    emptyText: '这一天还没有聊天记录',
  );
}

class ChatKeywordSearchPage extends StatefulWidget {
  const ChatKeywordSearchPage({super.key});

  @override
  State<ChatKeywordSearchPage> createState() => _ChatKeywordSearchPageState();
}

class _ChatKeywordSearchPageState extends State<ChatKeywordSearchPage> {
  final _api = LibraApi();
  final _controller = TextEditingController();
  Future<List<ChatMessage>> _messages = Future.value(const []);
  bool _hasSearched = false;

  @override
  void dispose() {
    _controller.dispose();
    _api.close();
    super.dispose();
  }

  void _search() {
    final query = _controller.text.trim();
    FocusScope.of(context).unfocus();
    setState(() {
      _hasSearched = query.isNotEmpty;
      _messages = query.isEmpty
          ? Future.value(const [])
          : _api.searchMessages(query);
    });
  }

  @override
  Widget build(BuildContext context) => _RecordsScaffold(
    title: '搜索聊天记录',
    messages: _messages,
    emptyText: _hasSearched ? '没有找到相关聊天记录' : '输入关键词，搜索你们的聊天记录',
    header: Padding(
      padding: const EdgeInsets.fromLTRB(24, 14, 24, 4),
      child: TextField(
        controller: _controller,
        autofocus: true,
        textInputAction: TextInputAction.search,
        onSubmitted: (_) => _search(),
        decoration: InputDecoration(
          hintText: '搜索聊天内容',
          prefixIcon: const Icon(Icons.search_rounded, color: _rose),
          suffixIcon: IconButton(
            tooltip: '搜索',
            onPressed: _search,
            icon: const Icon(Icons.arrow_forward_rounded, color: _rose),
          ),
          filled: true,
          fillColor: const Color(0xFFFFFAF9).withValues(alpha: .88),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: BorderSide(color: _rose.withValues(alpha: .28)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: BorderSide(color: _rose.withValues(alpha: .28)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: _rose, width: 1.3),
          ),
        ),
      ),
    ),
  );
}

class FavoriteMessagesPage extends StatefulWidget {
  const FavoriteMessagesPage({super.key});

  @override
  State<FavoriteMessagesPage> createState() => _FavoriteMessagesPageState();
}

class _FavoriteMessagesPageState extends State<FavoriteMessagesPage> {
  final _api = LibraApi();
  late Future<List<ChatMessage>> _messages = _api.getFavoriteMessages();

  @override
  void dispose() {
    _api.close();
    super.dispose();
  }

  Future<void> _removeFavorite(ChatMessage message) async {
    final messageId = message.id;
    if (messageId == null) return;
    try {
      await _api.setMessageFavorite(messageId, false);
      if (!mounted) return;
      setState(() {
        _messages = _messages.then(
          (values) => values.where((item) => item.id != messageId).toList(),
        );
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('已移出收藏')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('移出收藏失败，请稍后重试')));
    }
  }

  @override
  Widget build(BuildContext context) => _RecordsScaffold(
    title: '收藏的消息',
    messages: _messages,
    emptyText: '还没有收藏 Libra 的消息',
    showFavorite: true,
    onRemoveFavorite: _removeFavorite,
  );
}

class _RecordsScaffold extends StatelessWidget {
  const _RecordsScaffold({
    required this.title,
    required this.messages,
    required this.emptyText,
    this.action,
    this.header,
    this.showFavorite = false,
    this.onRemoveFavorite,
  });

  final String title;
  final Future<List<ChatMessage>> messages;
  final String emptyText;
  final Widget? action;
  final Widget? header;
  final bool showFavorite;
  final ValueChanged<ChatMessage>? onRemoveFavorite;

  @override
  Widget build(BuildContext context) => Scaffold(
    extendBodyBehindAppBar: true,
    backgroundColor: Colors.transparent,
    appBar: AppBar(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      foregroundColor: _ink,
      elevation: 0,
      title: Text(title),
      actions: action == null ? null : [action!, const SizedBox(width: 8)],
    ),
    body: DecoratedBox(
      decoration: const BoxDecoration(
        image: DecorationImage(
          image: AssetImage('assets/images/home_background.png'),
          fit: BoxFit.cover,
          alignment: Alignment.topCenter,
        ),
      ),
      child: ColoredBox(
        color: const Color(0xFFFFFAF9).withValues(alpha: .68),
        child: SafeArea(
          child: Padding(
            // AppBar is already drawn above this body.  Keeping another toolbar
            // height here leaves an unnecessary blank band before the search box.
            padding: EdgeInsets.zero,
            child: Column(
              children: [
                ...?(header == null ? null : [header!]),
                Expanded(
                  child: FutureBuilder<List<ChatMessage>>(
                    future: messages,
                    builder: (context, snapshot) {
                      if (snapshot.connectionState != ConnectionState.done) {
                        return const Center(
                          child: CircularProgressIndicator(color: _rose),
                        );
                      }
                      if (snapshot.hasError) {
                        return const Center(child: Text('聊天记录加载失败'));
                      }
                      final values = snapshot.data ?? const [];
                      if (values.isEmpty) return Center(child: Text(emptyText));
                      return ListView.separated(
                        padding: const EdgeInsets.fromLTRB(24, 14, 24, 32),
                        itemCount: values.length,
                        separatorBuilder: (_, _) => Divider(
                          height: 1,
                          thickness: .7,
                          color: _rose.withValues(alpha: .18),
                        ),
                        itemBuilder: (_, index) => _RecordTile(
                          message: values[index],
                          showFavorite: showFavorite,
                          onRemoveFavorite: onRemoveFavorite,
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class _RecordTile extends StatelessWidget {
  const _RecordTile({
    required this.message,
    required this.showFavorite,
    this.onRemoveFavorite,
  });

  final ChatMessage message;
  final bool showFavorite;
  final ValueChanged<ChatMessage>? onRemoveFavorite;

  @override
  Widget build(BuildContext context) {
    final time = message.createdAt;
    final timeText = time == null
        ? ''
        : '${time.month.toString().padLeft(2, '0')}.${time.day.toString().padLeft(2, '0')} '
              '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 15),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      message.isUser ? DisplayNames.user : DisplayNames.libra,
                      style: const TextStyle(
                        color: _ink,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const Spacer(),
                    if (showFavorite)
                      IconButton(
                        tooltip: '移出收藏',
                        visualDensity: VisualDensity.compact,
                        constraints: const BoxConstraints(
                          minWidth: 30,
                          minHeight: 30,
                        ),
                        padding: const EdgeInsets.all(4),
                        onPressed: onRemoveFavorite == null
                            ? null
                            : () => onRemoveFavorite!(message),
                        icon: const Icon(
                          Icons.favorite_rounded,
                          color: _rose,
                          size: 18,
                        ),
                      ),
                    if (showFavorite) const SizedBox(width: 2),
                    Text(
                      timeText,
                      style: const TextStyle(
                        color: Colors.black38,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 7),
                if (message.isImage && message.mediaUrl != null)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: Image.network(
                      '${ApiConfig.baseUrl}${message.mediaUrl}',
                      width: 180,
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => const Text('[图片]'),
                    ),
                  )
                else
                  SelectableText(
                    message.isVoice
                        ? '语音转写：${message.content}'
                        : message.content,
                    style: const TextStyle(
                      color: _ink,
                      height: 1.45,
                      fontSize: 15,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

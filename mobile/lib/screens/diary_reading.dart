import 'package:flutter/material.dart';
import '../models/dream_reading.dart';
import '../services/libra_api.dart';

const _ink = Color(0xFF514746);
const _rose = Color(0xFFDE776C);
const _muted = Color(0xFF9A7D79);
const _paper = Color(0xFFFFF9F6);

class ReviewReading extends StatefulWidget {
  const ReviewReading({super.key, required this.api});
  final LibraApi api;
  @override
  State<ReviewReading> createState() => _ReviewReadingState();
}

class _ReviewReadingState extends State<ReviewReading> {
  List<DreamReading> _items = [];
  String _level = 'day';
  DateTime? _date;
  bool _busy = false, _more = false;
  String? _error;
  int _generation = 0;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load({bool append = false}) async {
    final generation = ++_generation;
    setState(() {
      _busy = true;
      _error = null;
      if (!append) {
        _items = [];
        _more = false;
      }
    });
    try {
      final batch = await widget.api.getMemoryReading(
        level: _level,
        date: _date,
        offset: append ? _items.length : 0,
      );
      if (!mounted || generation != _generation) return;
      setState(() {
        _items = append ? [..._items, ...batch.items] : batch.items;
        _more = batch.hasMore;
      });
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(() => _error = '暂时没能加载，点此重试');
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date ?? DateTime.now(),
      firstDate: DateTime(2020),
      lastDate: DateTime.now(),
      helpText: '查找回顾',
    );
    if (picked == null || !mounted) return;
    setState(() => _date = picked);
    _load();
  }

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 2),
        child: Wrap(
          spacing: 12,
          runSpacing: 6,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            Container(
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: .8),
                border: Border.all(color: const Color(0xFFF0DFDB)),
                borderRadius: BorderRadius.circular(20),
              ),
              padding: const EdgeInsets.all(3),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final entry in const {
                    'day': '日',
                    'week': '周',
                    'month': '月',
                  }.entries)
                    Semantics(
                      selected: _level == entry.key,
                      button: true,
                      child: InkWell(
                        borderRadius: BorderRadius.circular(18),
                        onTap: () {
                          if (_level != entry.key) {
                            setState(() => _level = entry.key);
                            _load();
                          }
                        },
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 150),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 18,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: _level == entry.key
                                ? Colors.white
                                : Colors.transparent,
                            borderRadius: BorderRadius.circular(18),
                          ),
                          child: Text(
                            entry.value,
                            style: TextStyle(
                              color: _level == entry.key
                                  ? _rose
                                  : const Color(0xFF9BA8A3),
                              fontSize: 13,
                              fontWeight: _level == entry.key
                                  ? FontWeight.w600
                                  : FontWeight.w400,
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            TextButton.icon(
              onPressed: _pickDate,
              icon: const Icon(Icons.calendar_month_outlined, size: 17),
              label: Text(
                _date == null ? '按日期查找' : DreamReading.dateLabel(_date!),
              ),
              style: TextButton.styleFrom(foregroundColor: _muted),
            ),
            if (_date != null)
              IconButton(
                tooltip: '全部时间',
                onPressed: () {
                  setState(() => _date = null);
                  _load();
                },
                icon: const Icon(Icons.close, size: 18, color: _muted),
              ),
          ],
        ),
      ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: () => _load(),
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
            children: [
              if (_busy)
                const Padding(
                  padding: EdgeInsets.all(20),
                  child: Center(child: CircularProgressIndicator(color: _rose)),
                ),
              if (_error != null)
                TextButton(
                  onPressed: () => _load(append: _items.isNotEmpty),
                  child: Text(_error!),
                ),
              for (final item in _items) _ReadingCard(item: item),
              if (_items.isEmpty && !_busy && _error == null)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 60),
                  child: Text(
                    '还没有这一段时光的回顾',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: _muted),
                  ),
                ),
              if (_more)
                TextButton(
                  onPressed: _busy ? null : () => _load(append: true),
                  child: const Text('往前翻'),
                ),
            ],
          ),
        ),
      ),
    ],
  );
}

class _ReadingCard extends StatelessWidget {
  const _ReadingCard({required this.item});
  final DreamReading item;
  @override
  Widget build(BuildContext context) => Card(
    elevation: 1,
    shadowColor: _rose.withValues(alpha: .08),
    color: const Color(0xFFFFFCFA),
    margin: const EdgeInsets.only(bottom: 18),
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(22),
      side: const BorderSide(color: Color(0xFFF1E3DF)),
    ),
    child: InkWell(
      borderRadius: BorderRadius.circular(22),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => DreamReadingDetail(item: item)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    item.range,
                    style: const TextStyle(
                      color: _ink,
                      fontSize: 20,
                      fontWeight: FontWeight.w500,
                      letterSpacing: .4,
                    ),
                  ),
                ),
                if (!item.complete)
                  const Text(
                    '仍在续写',
                    style: TextStyle(color: _rose, fontSize: 11),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              item.title,
              style: const TextStyle(color: _muted, fontSize: 12),
            ),
            const SizedBox(height: 20),
            Text(
              item.available ? item.content : '这篇整理的依据已有变化，内容暂不展示。',
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: _ink, height: 1.8, fontSize: 15),
            ),
            const SizedBox(height: 18),
            const Divider(height: 1, color: Color(0xFFF0E4E0)),
            const SizedBox(height: 14),
            const Align(
              alignment: Alignment.centerRight,
              child: Text(
                '展开全文 ›',
                style: TextStyle(color: _rose, fontSize: 12),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class DreamReadingDetail extends StatelessWidget {
  const DreamReadingDetail({super.key, required this.item});
  final DreamReading item;
  Widget _section(String title, String body, {bool thought = false}) =>
      Container(
        margin: const EdgeInsets.only(bottom: 28),
        padding: thought ? const EdgeInsets.all(20) : EdgeInsets.zero,
        decoration: thought
            ? BoxDecoration(
                color: const Color(0xFFFFF0EC),
                borderRadius: BorderRadius.circular(20),
              )
            : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(
                color: _rose,
                fontSize: 15,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 12),
            SelectableText(
              body,
              style: const TextStyle(color: _ink, fontSize: 16, height: 1.9),
            ),
          ],
        ),
      );
  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: _paper,
    appBar: AppBar(
      title: Text(item.title),
      centerTitle: true,
      elevation: 0,
      backgroundColor: _paper,
      foregroundColor: _ink,
    ),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          item.range,
          style: const TextStyle(
            color: _ink,
            fontSize: 24,
            fontWeight: FontWeight.w500,
          ),
        ),
        const SizedBox(height: 28),
        if (!item.available)
          _section('暂时合上这一页', '这篇整理的依据已有变化，内容暂不展示。')
        else ...[
          _section('回看这段时光', item.content),
          for (final scene in item.scenes)
            _section(scene['title'] as String, scene['content'] as String),
          if (item.reflection.isNotEmpty) ...[
            _section('回望时的想法', item.reflection, thought: true),
            const Padding(
              padding: EdgeInsets.only(bottom: 24),
              child: Text(
                '这些理解还在慢慢形成。',
                style: TextStyle(color: _muted, fontSize: 12),
              ),
            ),
          ],
          if (item.foresight.isNotEmpty)
            _section(
              '想到以后',
              item.foresight
                  .map((f) => '${f['content']}\n留意到 ${f['valid_until']}')
                  .join('\n\n'),
            ),
        ],
      ],
    ),
  );
}

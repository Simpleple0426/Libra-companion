import '../services/display_names.dart';
import 'package:flutter/material.dart';
import '../services/libra_api.dart';

class LifeScheduleSheet extends StatelessWidget {
  const LifeScheduleSheet({super.key, required this.entries});
  final List<LifeScheduleEntry> entries;
  String _time(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  String _status(String s) => switch (s) {
    'completed' => '已完成',
    'in_progress' => '进行中',
    'paused' => '已暂停',
    'deferred' => '待后续安排',
    'elapsed_unverified' => '已过计划时间',
    'cancelled' => '已调整',
    'unavailable' => '资源不可用',
    _ => '计划中',
  };
  @override
  Widget build(BuildContext context) => SafeArea(
    child: SizedBox(
      height: MediaQuery.sizeOf(context).height * .8,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(20, 20, 20, 4),
            child: Text(
              '今日安排',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
            ),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(20, 0, 20, 12),
            child: Text(
              '临近时段会展开具体内容；安排可能随互动调整。',
              style: TextStyle(color: Colors.black54),
            ),
          ),
          Expanded(
            child: entries.isEmpty
                ? const Center(child: Text('今日安排正在准备中'))
                : ListView.builder(
                    itemCount: entries.length,
                    itemBuilder: (context, index) {
                      final e = entries[index];
                      return Padding(
                        padding: EdgeInsets.fromLTRB(
                          e.detailed ? 28 : 12,
                          3,
                          12,
                          3,
                        ),
                        child: Card(
                          color: e.detailed
                              ? const Color(0xFFFFF5F4)
                              : Colors.white,
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  '${_time(e.start)}—${e.openEnded ? '结束时间未定' : _time(e.end)}${e.place.isEmpty ? '' : ' · ${e.place}'}',
                                  style: const TextStyle(color: Colors.black54),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  DisplayNames.companionText(e.title),
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: e.detailed
                                        ? FontWeight.w500
                                        : FontWeight.bold,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  '${e.detailed ? '具体安排' : '时段安排'} · ${_status(e.status)}',
                                  style: const TextStyle(fontSize: 12),
                                ),
                                if (e.note.isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 4),
                                    child: Text(
                                      e.note,
                                      style: const TextStyle(
                                        fontSize: 12,
                                        color: Colors.black54,
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    ),
  );
}

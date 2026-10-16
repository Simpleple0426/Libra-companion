import 'package:flutter/material.dart';

import '../models/calendar_entry.dart';
import 'home_page.dart';

class HabitStatsPage extends StatefulWidget {
  const HabitStatsPage({super.key, required this.habits});
  final List<HabitItem> habits;

  @override
  State<HabitStatsPage> createState() => _HabitStatsPageState();
}

class _HabitStatsPageState extends State<HabitStatsPage> {
  bool _monthly = false;
  int _selectedIndex = 0;

  @override
  void initState() {
    super.initState();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final activeIndex = widget.habits.indexWhere(
      (habit) => habit.isActiveOn(today),
    );
    if (activeIndex >= 0) _selectedIndex = activeIndex;
  }

  DateTime get _today {
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day);
  }

  List<DateTime> get _days {
    final count = _monthly ? 30 : 7;
    return List.generate(
      count,
      (index) => _today.subtract(Duration(days: count - index - 1)),
    );
  }

  HabitItem? get _selectedHabit => widget.habits.isEmpty
      ? null
      : widget.habits[_selectedIndex.clamp(0, widget.habits.length - 1)];

  int _streak(HabitItem habit) {
    var date = _today;
    // Keep the streak achieved through yesterday until today's check-in is
    // actually due/completed instead of resetting the display to zero.
    if (!habit.isDoneOn(date)) {
      date = date.subtract(const Duration(days: 1));
    }
    var count = 0;
    while (habit.isActiveOn(date) && habit.isDoneOn(date)) {
      count++;
      date = date.subtract(const Duration(days: 1));
    }
    return count;
  }

  List<DateTime> _activeDays(HabitItem habit) =>
      _days.where(habit.isActiveOn).toList();

  int _completedInRange(HabitItem habit) =>
      _activeDays(habit).where(habit.isDoneOn).length;

  @override
  Widget build(BuildContext context) {
    final habit = _selectedHabit;
    final activeDays = habit == null ? <DateTime>[] : _activeDays(habit);
    final completed = habit == null ? 0 : _completedInRange(habit);
    final rate = activeDays.isEmpty ? 0.0 : completed / activeDays.length;

    return Scaffold(
      backgroundColor: homeBackground,
      appBar: AppBar(
        elevation: 0,
        backgroundColor: homeHeader,
        foregroundColor: Colors.black87,
        title: const Text('打卡记录'),
      ),
      body: widget.habits.isEmpty
          ? const Center(
              child: Text('还没有打卡项目', style: TextStyle(color: homeInactive)),
            )
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                const Text(
                  '选择项目',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  height: 42,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    itemCount: widget.habits.length,
                    separatorBuilder: (_, _) => const SizedBox(width: 8),
                    itemBuilder: (context, index) {
                      final selected = index == _selectedIndex;
                      return ChoiceChip(
                        selected: selected,
                        showCheckmark: false,
                        selectedColor: homeAccent,
                        backgroundColor: Colors.white,
                        label: Text(widget.habits[index].title),
                        labelStyle: TextStyle(
                          color: selected ? Colors.white : Colors.black87,
                          fontWeight: selected
                              ? FontWeight.w700
                              : FontWeight.w500,
                        ),
                        onSelected: (_) =>
                            setState(() => _selectedIndex = index),
                      );
                    },
                  ),
                ),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              habit!.title,
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          _RangeButton(
                            label: '周',
                            selected: !_monthly,
                            onTap: () => setState(() => _monthly = false),
                          ),
                          const SizedBox(width: 6),
                          _RangeButton(
                            label: '月',
                            selected: _monthly,
                            onTap: () => setState(() => _monthly = true),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                      Row(
                        children: [
                          _Metric(
                            value: '${(rate * 100).round()}%',
                            label: _monthly ? '近30天完成率' : '近7天完成率',
                          ),
                          _Metric(value: '${_streak(habit)}', label: '连续天数'),
                          _Metric(
                            value: '${habit.completedDates.length}',
                            label: '累计次数',
                          ),
                        ],
                      ),
                      const SizedBox(height: 20),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final day in _days)
                            _DayCell(
                              date: day,
                              active: habit.isActiveOn(day),
                              done: habit.isDoneOn(day),
                            ),
                        ],
                      ),
                      const SizedBox(height: 14),
                      const Wrap(
                        spacing: 14,
                        runSpacing: 6,
                        children: [
                          _LegendDot(color: Color(0xFFF1EAEA), label: '未完成'),
                          _LegendDot(color: Color(0xFF73A996), label: '已完成'),
                          _LegendDot(color: Color(0xFFF8F5F5), label: '未生效'),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({required this.value, required this.label});
  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Expanded(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          value,
          style: const TextStyle(
            color: homeAccent,
            fontSize: 24,
            fontWeight: FontWeight.w800,
          ),
        ),
        Text(label, style: const TextStyle(color: homeInactive, fontSize: 11)),
      ],
    ),
  );
}

class _RangeButton extends StatelessWidget {
  const _RangeButton({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => InkWell(
    borderRadius: BorderRadius.circular(10),
    onTap: onTap,
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 7),
      decoration: BoxDecoration(
        color: selected ? homeAccent : const Color(0xFFF5EEEE),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: selected ? Colors.white : homeInactive,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
  );
}

class _DayCell extends StatelessWidget {
  const _DayCell({
    required this.date,
    required this.active,
    required this.done,
  });
  final DateTime date;
  final bool active;
  final bool done;

  @override
  Widget build(BuildContext context) {
    final color = !active
        ? const Color(0xFFF8F5F5)
        : done
        ? const Color(0xFF73A996)
        : const Color(0xFFF1EAEA);
    return Tooltip(
      message:
          '${date.month}月${date.day}日 · ${!active
              ? '未生效'
              : done
              ? '已完成'
              : '未完成'}',
      child: Container(
        width: 34,
        height: 34,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(9),
        ),
        child: Text(
          '${date.day}',
          style: TextStyle(
            color: done ? Colors.white : homeInactive,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 9,
        height: 9,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
      ),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(color: homeInactive, fontSize: 11)),
    ],
  );
}

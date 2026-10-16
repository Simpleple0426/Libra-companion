import 'package:flutter/material.dart';

import '../models/calendar_entry.dart';
import '../services/calendar_service.dart';
import '../services/display_names.dart';
import '../services/important_dates_store.dart';
import '../services/libra_api.dart';
import 'habit_stats_page.dart';
import 'home_page.dart';

class CalendarPage extends StatefulWidget {
  const CalendarPage({
    super.key,
    required this.deviceContextEnabled,
    required this.permissionRefreshToken,
    required this.onActivityRecorded,
  });
  final bool deviceContextEnabled;
  final int permissionRefreshToken;
  final Future<void> Function(String action, String appName, String description)
  onActivityRecorded;

  @override
  State<CalendarPage> createState() => _CalendarPageState();
}

class _CalendarPageState extends State<CalendarPage>
    with WidgetsBindingObserver {
  final _service = CalendarService();
  final _api = LibraApi();
  late final ImportantDatesStore _importantDatesStore;
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);
  DateTime _selected = DateTime(
    DateTime.now().year,
    DateTime.now().month,
    DateTime.now().day,
  );
  List<CalendarEntry> _events = [];
  List<TodoItem> _todos = [];
  List<HabitItem> _habits = [];
  List<ImportantDate> _importantDates = [];
  Map<String, WorkCalendarDay> _workCalendar = {};
  bool _showHabits = false;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _importantDatesStore = ImportantDatesStore(_api);
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _api.close();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load(showLoading: false);
  }

  @override
  void didUpdateWidget(CalendarPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.permissionRefreshToken != oldWidget.permissionRefreshToken) {
      _load(showLoading: false);
    }
  }

  Future<void> _load({bool showLoading = true}) async {
    if (showLoading && mounted) setState(() => _loading = true);
    final result = await _service.loadMonth(_month);
    var todos = await _service.loadTodos();
    var habits = await _service.loadHabits();
    try {
      todos = await _api.getTodos();
      habits = await _api.getHabits();
      await _service.saveTodos(todos);
      await _service.saveHabits(habits);
    } catch (_) {
      // Keep the last local copy while the backend is unavailable.
    }
    final importantDates = await _importantDatesStore.load();
    List<WorkCalendarDay> workCalendar = const [];
    try {
      workCalendar = await _api.getWorkCalendarMonth(_month);
    } catch (_) {}
    if (!mounted) return;
    setState(() {
      _events = [...result.events, ..._importantDateEvents(importantDates)];
      _todos = todos;
      _habits = List<HabitItem>.of(habits);
      _importantDates = importantDates;
      _workCalendar = {for (final day in workCalendar) _dateKey(day.date): day};
      _loading = false;
    });
    final eventsToSync = result.hasPermission
        ? result.events
        : result.events.where((event) => event.source == 'festival').toList();
    if (eventsToSync.isNotEmpty) {
      try {
        await _api.uploadCalendarEvents(
          eventsToSync,
          syncStart: DateTime(_month.year, _month.month - 1, 20),
          syncEnd: DateTime(_month.year, _month.month + 2, 10),
          reconcileSystem: result.hasPermission,
        );
      } catch (_) {}
    }
    // Loading is read-only. Never push an offline cache back to the server
    // merely because the page opened; only explicit user edits may write.
  }

  bool _sameDay(DateTime a, DateTime b) =>
      a.year == b.year && a.month == b.month && a.day == b.day;
  String _dateKey(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-'
      '${date.month.toString().padLeft(2, '0')}-'
      '${date.day.toString().padLeft(2, '0')}';
  List<CalendarEntry> get _selectedEvents =>
      _events.where((event) => _sameDay(event.start, _selected)).toList();
  List<TodoItem> get _selectedTodos =>
      _todos.where((todo) => _sameDay(todo.date, _selected)).toList();
  List<HabitItem> _activeHabits(DateTime date) =>
      _habits.where((habit) => habit.isActiveOn(date)).toList();
  int _habitDoneCount(DateTime date) =>
      _activeHabits(date).where((habit) => habit.isDoneOn(date)).length;

  List<({ImportantDate item, DateTime date, int days})>
  get _upcomingImportantDates {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final values = <({ImportantDate item, DateTime date, int days})>[];
    for (final item in _importantDates) {
      late DateTime occurrence;
      if (item.repeatsAnnually) {
        occurrence = _safeAnnualDate(
          today.year,
          item.date.month,
          item.date.day,
        );
        if (occurrence.isBefore(today)) {
          occurrence = _safeAnnualDate(
            today.year + 1,
            item.date.month,
            item.date.day,
          );
        }
      } else {
        occurrence = DateTime(item.date.year, item.date.month, item.date.day);
        if (occurrence.isBefore(today)) continue;
      }
      values.add((
        item: item,
        date: occurrence,
        days: occurrence.difference(today).inDays,
      ));
    }
    values.sort((a, b) {
      final byDate = a.date.compareTo(b.date);
      return byDate != 0 ? byDate : a.item.title.compareTo(b.item.title);
    });
    return values;
  }

  DateTime _safeAnnualDate(int year, int month, int day) {
    final lastDay = DateTime(year, month + 1, 0).day;
    return DateTime(year, month, day.clamp(1, lastDay));
  }

  Future<void> _jumpToImportantDate(DateTime date) async {
    final target = DateTime(date.year, date.month, date.day);
    final changedMonth =
        _month.year != target.year || _month.month != target.month;
    setState(() {
      _month = DateTime(target.year, target.month);
      _selected = target;
    });
    if (changedMonth) await _load();
  }

  Widget _importantDateCountdownStrip() {
    final dates = _upcomingImportantDates;
    if (dates.isEmpty) return const SizedBox.shrink();
    return Container(
      height: 64,
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: .78),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.white.withValues(alpha: .72)),
        boxShadow: [
          BoxShadow(
            color: homeAccent.withValues(alpha: .07),
            blurRadius: 14,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: PageView.builder(
        physics: const BouncingScrollPhysics(),
        itemCount: dates.length,
        itemBuilder: (context, index) {
          final value = dates[index];
          final occurrenceTitle = value.item.occurrenceTitle(value.date.year);
          return InkWell(
            onTap: () => _jumpToImportantDate(value.date),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: homeAccent.withValues(alpha: .12),
                      shape: BoxShape.circle,
                    ),
                    child: const Icon(
                      Icons.favorite_outline,
                      color: homeAccent,
                      size: 19,
                    ),
                  ),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          value.days == 0
                              ? occurrenceTitle
                              : '距 $occurrenceTitle',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          '${value.date.year}年${value.date.month}月${value.date.day}日',
                          style: const TextStyle(
                            color: homeInactive,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    value.days == 0 ? '就是今天 ♡' : '${value.days} 天',
                    style: const TextStyle(
                      color: homeAccent,
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(width: 2),
                  const Icon(
                    Icons.chevron_right,
                    size: 19,
                    color: homeInactive,
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  int _habitStreak(HabitItem habit) {
    final now = DateTime.now();
    var date = DateTime(now.year, now.month, now.day);
    // An unfinished current day must not erase the streak completed through
    // yesterday.  Once today is checked, it naturally becomes part of it.
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

  Future<void> _toggleHabit(HabitItem habit) async {
    final index = _habits.indexWhere((item) => item.id == habit.id);
    if (index < 0) return;
    final updated = List<HabitItem>.of(_habits);
    final wasDone = habit.isDoneOn(_selected);
    updated[index] = habit.toggledOn(_selected);
    setState(() => _habits = updated);
    await _service.saveHabits(_habits);
    try {
      await _api.setHabitCheckin(habit.id, _selected, !wasDone);
    } catch (_) {}
    if (!wasDone) {
      await widget.onActivityRecorded(
        'habit_completed',
        '打卡',
        '${DisplayNames.user}完成了打卡：${habit.title}',
      );
    }
  }

  Future<void> _openHabitEditor() async {
    final title = await showDialog<String>(
      context: context,
      builder: (_) => const _HabitEditorDialog(),
    );
    if (title == null || title.trim().isEmpty || !mounted) return;
    late final HabitItem created;
    setState(() {
      created = HabitItem(
        id: DateTime.now().microsecondsSinceEpoch.toString(),
        title: title.trim(),
        activeFrom: DateTime(
          DateTime.now().year,
          DateTime.now().month,
          DateTime.now().day,
        ),
      );
      _habits.add(created);
    });
    await _service.saveHabits(_habits);
    try {
      await _api.saveHabit(created);
    } catch (_) {}
  }

  Future<void> _showHabitDelete(HabitItem item) async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: homeBackground,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        top: false,
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(
                Icons.delete_outline,
                color: Colors.redAccent,
              ),
              title: const Text('删除打卡项目'),
              onTap: () async {
                Navigator.of(sheetContext).pop();
                final index = _habits.indexWhere(
                  (habit) => habit.id == item.id,
                );
                if (index >= 0) {
                  final updated = List<HabitItem>.of(_habits);
                  updated[index] = item.retiredBefore(DateTime.now());
                  setState(() => _habits = updated);
                  try {
                    await _api.saveHabit(updated[index]);
                  } catch (_) {}
                }
                await _service.saveHabits(_habits);
              },
            ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
  }

  List<CalendarEntry> _importantDateEvents(List<ImportantDate> items) {
    final monthStart = DateTime(_month.year, _month.month, 1);
    final monthEnd = DateTime(_month.year, _month.month + 1, 1);
    return items.expand((item) {
      final date = item.repeatsAnnually
          ? DateTime(_month.year, item.date.month, item.date.day)
          : item.date;
      if (date.isBefore(monthStart) || !date.isBefore(monthEnd)) {
        return const <CalendarEntry>[];
      }
      return [
        CalendarEntry(
          id: 'important:${item.id}:$date',
          title: item.occurrenceTitle(_month.year),
          start: date,
          end: date,
          allDay: true,
          source: 'custom',
        ),
      ];
    }).toList();
  }

  Future<void> _changeMonth(int offset) async {
    setState(() {
      _month = DateTime(_month.year, _month.month + offset);
      _selected = DateTime(_month.year, _month.month, 1);
    });
    await _load();
  }

  Future<void> _toggle(TodoItem todo) async {
    final index = _todos.indexWhere((item) => item.id == todo.id);
    if (index < 0) return;
    final updated = todo.copyWith(done: !todo.done);
    setState(() => _todos[index] = updated);
    await _service.saveTodos(_todos);
    try {
      await _api.saveTodo(updated);
    } catch (_) {
      if (mounted) setState(() => _todos[index] = todo);
      await _service.saveTodos(_todos);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('未能同步完成状态，请重试；提醒暂未取消')));
      return;
    }
    if (!todo.done) {
      await widget.onActivityRecorded(
        'todo_completed',
        '待办',
        '${DisplayNames.user}完成了待办：${todo.title}',
      );
    }
  }

  Future<void> _openTodoEditor([TodoItem? item]) async {
    final draft = await showDialog<TodoItem>(
      context: context,
      builder: (_) =>
          _TodoEditorDialog(selectedDate: _selected, initial: item),
    );
    if (draft == null || !mounted) return;
    late final TodoItem saved;
    setState(() {
      if (item == null) {
        saved = TodoItem(
          id: DateTime.now().microsecondsSinceEpoch.toString(),
          title: draft.title,
          date: draft.date,
          remindAt: draft.remindAt,
          repeatRule: draft.repeatRule,
        );
        _todos.add(saved);
      } else {
        final index = _todos.indexWhere((todo) => todo.id == item.id);
        saved = draft;
        if (index >= 0) _todos[index] = saved;
      }
    });
    await _service.saveTodos(_todos);
    try {
      await _api.saveTodo(saved);
    } catch (_) {
      if (mounted) setState(() {
        _todos.removeWhere((todo) => todo.id == saved.id);
        if (item != null) _todos.add(item);
      });
      await _service.saveTodos(_todos);
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('未能保存到服务器，请重试；提醒设置未生效')));
      return;
    }
    if (item == null) {
      await widget.onActivityRecorded(
        'todo_added',
        '待办',
        '${DisplayNames.user}添加了待办：${draft.title}',
      );
    }
  }

  Future<void> _showTodoActions(TodoItem item) async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: homeBackground,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        top: false,
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.edit_outlined, color: homeAccent),
              title: const Text('编辑待办'),
              onTap: () async {
                Navigator.of(sheetContext).pop();
                await _openTodoEditor(item);
              },
            ),
            ListTile(
              leading: const Icon(
                Icons.delete_outline,
                color: Colors.redAccent,
              ),
              title: const Text('删除待办'),
              onTap: () async {
                Navigator.of(sheetContext).pop();
                setState(
                  () => _todos.removeWhere((todo) => todo.id == item.id),
                );
                await _service.saveTodos(_todos);
                try {
                  await _api.deleteTodo(item.id);
                } catch (_) {
                  if (mounted) setState(() => _todos.add(item));
                  await _service.saveTodos(_todos);
                  if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('删除未同步，请重试；提醒暂未取消')));
                }
              },
            ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    );
  }

  Future<void> _showImportantDatesSheet() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: homeBackground,
      showDragHandle: true,
      builder: (sheetContext) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '我的重要日子',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
                  ),
                ),
                IconButton(
                  onPressed: () async {
                    Navigator.of(sheetContext).pop();
                    await _openImportantDateEditor();
                  },
                  icon: const Icon(Icons.add_circle, color: homeAccent),
                ),
              ],
            ),
            if (_importantDates.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Text(
                  '添加一个值得记住的日期吧',
                  style: TextStyle(color: homeInactive),
                ),
              ),
            ..._importantDates.map(
              (item) => ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(
                  Icons.favorite_border_rounded,
                  color: homeAccent,
                ),
                title: Text(item.title),
                subtitle: Text(
                  '${item.date.year}年${item.date.month}月${item.date.day}日 · ${item.typeLabel}',
                ),
                onTap: () async {
                  Navigator.of(sheetContext).pop();
                  await _openImportantDateEditor(item);
                },
                trailing: IconButton(
                  onPressed: item.id == null
                      ? null
                      : () async {
                          Navigator.of(sheetContext).pop();
                          await _importantDatesStore.delete(item.id!);
                          await _load();
                        },
                  icon: const Icon(Icons.delete_outline, color: homeInactive),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _openImportantDateEditor([ImportantDate? item]) async {
    final saved = await showDialog<ImportantDate>(
      context: context,
      builder: (_) =>
          _ImportantDateEditorDialog(initial: item, defaultDate: _selected),
    );
    if (saved == null) return;
    await _importantDatesStore.save(saved);
    if (!mounted) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final first = DateTime(_month.year, _month.month, 1);
    final days = DateTime(_month.year, _month.month + 1, 0).day;
    final leading = first.weekday - 1;
    final weekRows = (leading + days + 6) ~/ 7;
    final mediaQuery = MediaQuery.of(context);
    return MediaQuery(
      data: mediaQuery.copyWith(viewInsets: EdgeInsets.zero),
      child: ColoredBox(
        color: Colors.transparent,
        child: Column(
          children: [
            Container(
              height: 68,
              color: Colors.transparent,
              padding: const EdgeInsets.fromLTRB(14, 0, 10, 0),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      InkWell(
                        onTap: _showImportantDatesSheet,
                        borderRadius: BorderRadius.circular(10),
                        child: const Padding(
                          padding: EdgeInsets.symmetric(
                            vertical: 8,
                            horizontal: 4,
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                'C A L E N D A R',
                                style: TextStyle(
                                  color: homeAccent,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w700,
                                  letterSpacing: 1.5,
                                ),
                              ),
                              SizedBox(width: 6),
                              Icon(
                                Icons.edit_calendar_outlined,
                                size: 17,
                                color: homeAccent,
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          alignment: Alignment.centerRight,
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              IconButton(
                                onPressed: () => _changeMonth(-1),
                                padding: EdgeInsets.zero,
                                constraints: const BoxConstraints.tightFor(
                                  width: 34,
                                  height: 40,
                                ),
                                icon: const Icon(Icons.chevron_left),
                              ),
                              Text(
                                '${_month.year}年 ${_month.month}月',
                                style: const TextStyle(
                                  fontSize: 16,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              IconButton(
                                onPressed: () => _changeMonth(1),
                                padding: EdgeInsets.zero,
                                constraints: const BoxConstraints.tightFor(
                                  width: 34,
                                  height: 40,
                                ),
                                icon: const Icon(Icons.chevron_right),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
                child: Column(
                  children: [
                    if (_upcomingImportantDates.isNotEmpty) ...[
                      _importantDateCountdownStrip(),
                      const SizedBox(height: 10),
                    ],
                    Expanded(
                      flex: 6,
                      child: Container(
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: .78),
                          borderRadius: BorderRadius.circular(18),
                          border: Border.all(
                            color: Colors.white.withValues(alpha: .72),
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: homeAccent.withValues(alpha: .09),
                              blurRadius: 18,
                              offset: const Offset(0, 6),
                            ),
                          ],
                        ),
                        child: Column(
                          children: [
                            Row(
                              children: [
                                for (final day in [
                                  '一',
                                  '二',
                                  '三',
                                  '四',
                                  '五',
                                  '六',
                                  '日',
                                ])
                                  Expanded(
                                    child: Center(
                                      child: Text(
                                        day,
                                        style: TextStyle(
                                          color: homeInactive,
                                          fontSize: 12,
                                        ),
                                      ),
                                    ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Expanded(
                              child: LayoutBuilder(
                                builder: (context, constraints) {
                                  return GridView.builder(
                                    padding: EdgeInsets.zero,
                                    physics:
                                        const NeverScrollableScrollPhysics(),
                                    gridDelegate:
                                        SliverGridDelegateWithFixedCrossAxisCount(
                                          crossAxisCount: 7,
                                          mainAxisExtent:
                                              constraints.maxHeight / weekRows,
                                        ),
                                    itemCount: leading + days,
                                    itemBuilder: (context, index) {
                                      if (index < leading) {
                                        return const SizedBox.shrink();
                                      }
                                      final date = DateTime(
                                        _month.year,
                                        _month.month,
                                        index - leading + 1,
                                      );
                                      final selected = _sameDay(
                                        date,
                                        _selected,
                                      );
                                      final today = _sameDay(
                                        date,
                                        DateTime.now(),
                                      );
                                      final chinese =
                                          CalendarService.chineseInfo(date);
                                      final habitDone = _habitDoneCount(date);
                                      final workDay =
                                          _workCalendar[_dateKey(date)];
                                      final workMarker =
                                          workDay?.isMakeupWorkday == true
                                          ? '班'
                                          : workDay?.isHolidayLeave == true
                                          ? '休'
                                          : null;
                                      final specialEvent = _events
                                          .where(
                                            (event) =>
                                                event.source == 'custom' &&
                                                _sameDay(event.start, date),
                                          )
                                          .firstOrNull;
                                      final specialDate = specialEvent != null;
                                      final dateLabel = specialDate
                                          ? specialEvent.title
                                                .split('·')
                                                .last
                                                .trim()
                                          : chinese.dayLabel;
                                      final marked =
                                          _events.any(
                                            (e) => _sameDay(e.start, date),
                                          ) ||
                                          _todos.any(
                                            (t) => _sameDay(t.date, date),
                                          ) ||
                                          habitDone > 0;
                                      return InkWell(
                                        borderRadius: BorderRadius.circular(12),
                                        onTap: () =>
                                            setState(() => _selected = date),
                                        child: Container(
                                          margin: const EdgeInsets.symmetric(
                                            horizontal: 2,
                                          ),
                                          decoration: BoxDecoration(
                                            color: selected
                                                ? homeAccent
                                                : Colors.transparent,
                                            borderRadius: BorderRadius.circular(
                                              12,
                                            ),
                                            border: today && !selected
                                                ? Border.all(color: homeAccent)
                                                : null,
                                          ),
                                          child: Stack(
                                            alignment: Alignment.center,
                                            children: [
                                              if (specialDate)
                                                Transform.translate(
                                                  offset: const Offset(0, 2),
                                                  child: Icon(
                                                    Icons.favorite,
                                                    size: 34,
                                                    color: selected
                                                        ? Colors.white
                                                              .withValues(
                                                                alpha: .18,
                                                              )
                                                        : homeAccent.withValues(
                                                            alpha: .17,
                                                          ),
                                                  ),
                                                ),
                                              Column(
                                                mainAxisAlignment:
                                                    MainAxisAlignment.center,
                                                children: [
                                                  Row(
                                                    mainAxisSize:
                                                        MainAxisSize.min,
                                                    crossAxisAlignment:
                                                        CrossAxisAlignment
                                                            .start,
                                                    children: [
                                                      Text(
                                                        '${date.day}',
                                                        style: TextStyle(
                                                          color: selected
                                                              ? Colors.white
                                                              : Colors.black87,
                                                          fontSize: 14,
                                                          height: .95,
                                                          fontWeight:
                                                              selected || today
                                                              ? FontWeight.w700
                                                              : FontWeight.w400,
                                                        ),
                                                      ),
                                                      if (workMarker != null)
                                                        Container(
                                                          margin:
                                                              const EdgeInsets.only(
                                                                left: 1,
                                                              ),
                                                          padding:
                                                              workMarker == '班'
                                                              ? const EdgeInsets.all(
                                                                  1.5,
                                                                )
                                                              : EdgeInsets.zero,
                                                          decoration:
                                                              workMarker == '班'
                                                              ? BoxDecoration(
                                                                  color:
                                                                      selected
                                                                      ? Colors
                                                                            .white
                                                                      : homeAccent,
                                                                  shape: BoxShape
                                                                      .circle,
                                                                )
                                                              : null,
                                                          child: Text(
                                                            workMarker,
                                                            style: TextStyle(
                                                              color:
                                                                  workMarker ==
                                                                      '班'
                                                                  ? selected
                                                                        ? homeAccent
                                                                        : Colors
                                                                              .white
                                                                  : selected
                                                                  ? Colors.white
                                                                  : homeAccent,
                                                              fontSize: 7,
                                                              height: 1,
                                                              fontWeight:
                                                                  FontWeight
                                                                      .w700,
                                                            ),
                                                          ),
                                                        ),
                                                    ],
                                                  ),
                                                  Text(
                                                    dateLabel,
                                                    maxLines: 1,
                                                    overflow: TextOverflow.clip,
                                                    style: TextStyle(
                                                      color: selected
                                                          ? Colors.white70
                                                          : chinese
                                                                .festivals
                                                                .isNotEmpty
                                                          ? homeAccent
                                                          : homeInactive,
                                                      fontSize: 9,
                                                      height: .9,
                                                    ),
                                                  ),
                                                  if (marked &&
                                                      chinese
                                                          .festivals
                                                          .isEmpty &&
                                                      !specialDate)
                                                    Container(
                                                      margin: EdgeInsets.zero,
                                                      width: 3,
                                                      height: 2.5,
                                                      decoration: BoxDecoration(
                                                        color:
                                                            habitDone ==
                                                                    _activeHabits(
                                                                      date,
                                                                    ).length &&
                                                                _activeHabits(
                                                                  date,
                                                                ).isNotEmpty
                                                            ? const Color(
                                                                0xFF73A996,
                                                              )
                                                            : selected
                                                            ? Colors.white
                                                            : homeAccent,
                                                        shape: BoxShape.circle,
                                                      ),
                                                    ),
                                                ],
                                              ),
                                            ],
                                          ),
                                        ),
                                      );
                                    },
                                  );
                                },
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Expanded(
                      flex: 5,
                      child: Container(
                        padding: const EdgeInsets.fromLTRB(16, 14, 12, 8),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: .76),
                          borderRadius: BorderRadius.circular(18),
                          border: Border.all(
                            color: Colors.white.withValues(alpha: .7),
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: homeAccent.withValues(alpha: .08),
                              blurRadius: 16,
                              offset: const Offset(0, 5),
                            ),
                          ],
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Text(
                                  '${_selected.month}月${_selected.day}日',
                                  style: const TextStyle(
                                    fontSize: 18,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                if (CalendarService.chineseInfo(
                                      _selected,
                                    ).festivals.firstOrNull
                                    case final festival?) ...[
                                  const SizedBox(width: 8),
                                  Text(
                                    festival,
                                    style: const TextStyle(
                                      color: homeAccent,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ],
                            ),
                            const SizedBox(height: 8),
                            Container(
                              height: 38,
                              padding: const EdgeInsets.all(3),
                              decoration: BoxDecoration(
                                color: const Color(
                                  0xFFF9EFEF,
                                ).withValues(alpha: .78),
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: _DetailTab(
                                      label: '待办',
                                      icon: Icons.check_circle_outline,
                                      selected: !_showHabits,
                                      onTap: () =>
                                          setState(() => _showHabits = false),
                                    ),
                                  ),
                                  Expanded(
                                    child: _DetailTab(
                                      label: '打卡',
                                      icon: Icons.spa_outlined,
                                      selected: _showHabits,
                                      onTap: () =>
                                          setState(() => _showHabits = true),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Expanded(
                              child: _loading
                                  ? const Center(
                                      child: CircularProgressIndicator(
                                        color: homeAccent,
                                      ),
                                    )
                                  : _showHabits
                                  ? ListView(
                                      children: [
                                        Padding(
                                          padding: const EdgeInsets.only(
                                            top: 12,
                                            bottom: 8,
                                          ),
                                          child: Text(
                                            _activeHabits(_selected).isEmpty
                                                ? '还没有打卡项目'
                                                : '已完成 ${_habitDoneCount(_selected)} / ${_activeHabits(_selected).length}',
                                            style: const TextStyle(
                                              color: homeInactive,
                                            ),
                                          ),
                                        ),
                                        if (_activeHabits(_selected).isNotEmpty)
                                          Padding(
                                            padding: const EdgeInsets.only(
                                              bottom: 6,
                                            ),
                                            child: ClipRRect(
                                              borderRadius:
                                                  BorderRadius.circular(4),
                                              child: LinearProgressIndicator(
                                                minHeight: 6,
                                                value:
                                                    _habitDoneCount(_selected) /
                                                    _activeHabits(
                                                      _selected,
                                                    ).length,
                                                backgroundColor: const Color(
                                                  0xFFF1EAEA,
                                                ),
                                                valueColor:
                                                    const AlwaysStoppedAnimation(
                                                      Color(0xFF73A996),
                                                    ),
                                              ),
                                            ),
                                          ),
                                        ListTile(
                                          dense: true,
                                          contentPadding: EdgeInsets.zero,
                                          leading: const Icon(
                                            Icons.insights_outlined,
                                            color: homeInactive,
                                          ),
                                          title: const Text('查看打卡记录'),
                                          trailing: const Icon(
                                            Icons.chevron_right,
                                            color: homeInactive,
                                          ),
                                          onTap: () =>
                                              Navigator.of(context).push(
                                                MaterialPageRoute<void>(
                                                  builder: (_) =>
                                                      HabitStatsPage(
                                                        habits:
                                                            List<HabitItem>.of(
                                                              _habits,
                                                            ),
                                                      ),
                                                ),
                                              ),
                                        ),
                                        for (final habit in _activeHabits(
                                          _selected,
                                        ))
                                          ListTile(
                                            dense: true,
                                            contentPadding: EdgeInsets.zero,
                                            leading: Icon(
                                              habit.isDoneOn(_selected)
                                                  ? Icons.check_circle
                                                  : Icons
                                                        .radio_button_unchecked,
                                              color: habit.isDoneOn(_selected)
                                                  ? const Color(0xFF73A996)
                                                  : homeInactive,
                                            ),
                                            title: Text(
                                              habit.title,
                                              style: TextStyle(
                                                decoration:
                                                    habit.isDoneOn(_selected)
                                                    ? TextDecoration.lineThrough
                                                    : null,
                                                color: habit.isDoneOn(_selected)
                                                    ? homeInactive
                                                    : null,
                                              ),
                                            ),
                                            subtitle: Text(
                                              '连续 ${_habitStreak(habit)} 天',
                                              style: const TextStyle(
                                                color: homeInactive,
                                                fontSize: 11,
                                              ),
                                            ),
                                            onTap: () => _toggleHabit(habit),
                                            onLongPress: () =>
                                                _showHabitDelete(habit),
                                          ),
                                        ListTile(
                                          dense: true,
                                          contentPadding: EdgeInsets.zero,
                                          leading: const Icon(
                                            Icons.add_circle_outline,
                                            color: homeAccent,
                                          ),
                                          title: const Text('添加打卡项目'),
                                          onTap: _openHabitEditor,
                                        ),
                                      ],
                                    )
                                  : ListView(
                                      children: [
                                        for (final event in _selectedEvents)
                                          ListTile(
                                            dense: true,
                                            contentPadding: EdgeInsets.zero,
                                            leading: const Icon(
                                              Icons.event_outlined,
                                              color: homeAccent,
                                            ),
                                            title: Text(event.title),
                                            subtitle: Text(
                                              event.allDay
                                                  ? '全天'
                                                  : '${event.start.hour.toString().padLeft(2, '0')}:${event.start.minute.toString().padLeft(2, '0')}${event.location?.isNotEmpty == true ? ' · ${event.location}' : ''}',
                                            ),
                                          ),
                                        ListTile(
                                          dense: true,
                                          contentPadding: EdgeInsets.zero,
                                          leading: const Icon(
                                            Icons.add_circle_outline,
                                            color: homeAccent,
                                          ),
                                          title: const Text('添加待办'),
                                          onTap: _openTodoEditor,
                                        ),
                                        for (final todo in _selectedTodos)
                                          ListTile(
                                            dense: true,
                                            contentPadding: EdgeInsets.zero,
                                            onTap: () => _showTodoActions(todo),
                                            subtitle: todo.remindAt == null ? null : Text(
                                              "${todo.remindAt!.hour.toString().padLeft(2, '0')}:${todo.remindAt!.minute.toString().padLeft(2, '0')} 提醒"),
                                            title: Text(
                                              todo.title,
                                              style: TextStyle(
                                                decoration: todo.done
                                                    ? TextDecoration.lineThrough
                                                    : null,
                                                color: todo.done
                                                    ? homeInactive
                                                    : null,
                                              ),
                                            ),
                                            trailing: Checkbox(
                                              activeColor: homeAccent,
                                              value: todo.done,
                                              onChanged: (_) => _toggle(todo),
                                            ),
                                          ),
                                        if (_selectedEvents.isEmpty &&
                                            _selectedTodos.isEmpty)
                                          const Padding(
                                            padding: EdgeInsets.only(top: 28),
                                            child: Center(
                                              child: Text(
                                                '这一天还没有安排',
                                                style: TextStyle(
                                                  color: homeInactive,
                                                ),
                                              ),
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
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DetailTab extends StatelessWidget {
  const _DetailTab({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: selected ? Colors.white : Colors.transparent,
    borderRadius: BorderRadius.circular(9),
    child: InkWell(
      borderRadius: BorderRadius.circular(9),
      onTap: onTap,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 16, color: selected ? homeAccent : homeInactive),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              color: selected ? homeAccent : homeInactive,
            ),
          ),
        ],
      ),
    ),
  );
}

class _HabitEditorDialog extends StatefulWidget {
  const _HabitEditorDialog();

  @override
  State<_HabitEditorDialog> createState() => _HabitEditorDialogState();
}

class _HabitEditorDialogState extends State<_HabitEditorDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    backgroundColor: homeBackground,
    title: const Text('添加打卡项目'),
    content: TextField(
      controller: _controller,
      autofocus: true,
      textInputAction: TextInputAction.done,
      onSubmitted: (value) => Navigator.pop(context, value.trim()),
      decoration: const InputDecoration(hintText: '例如：拉伸 10 分钟'),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('取消'),
      ),
      FilledButton(
        onPressed: () => Navigator.pop(context, _controller.text.trim()),
        child: const Text('保存'),
      ),
    ],
  );
}

class _ImportantDateEditorDialog extends StatefulWidget {
  const _ImportantDateEditorDialog({this.initial, required this.defaultDate});

  final ImportantDate? initial;
  final DateTime defaultDate;

  @override
  State<_ImportantDateEditorDialog> createState() =>
      _ImportantDateEditorDialogState();
}

class _TodoEditorDialog extends StatefulWidget {
  const _TodoEditorDialog({required this.selectedDate, this.initial});
  final DateTime selectedDate;
  final TodoItem? initial;
  @override
  State<_TodoEditorDialog> createState() => _TodoEditorDialogState();
}
class _TodoEditorDialogState extends State<_TodoEditorDialog> {
  late final TextEditingController _controller;
  late DateTime _date;
  TimeOfDay? _time;
  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initial?.title ?? '');
    _date = widget.initial?.date ?? widget.selectedDate;
    final at = widget.initial?.remindAt;
    _time = at == null ? null : TimeOfDay.fromDateTime(at);
  }
  @override
  void dispose() { _controller.dispose(); super.dispose(); }
  void _submit() {
    final title = _controller.text.trim();
    if (title.isEmpty) return;
    final at = _time == null ? null : DateTime(_date.year, _date.month, _date.day, _time!.hour, _time!.minute);
    if (at != null && !at.isAfter(DateTime.now())) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('请选择未来的提醒时间')));
      return;
    }
    Navigator.of(context).pop(TodoItem(id: widget.initial?.id ?? '', title: title,
      date: _date, done: widget.initial?.done ?? false, remindAt: at,
      repeatRule: null));
  }
  @override
  Widget build(BuildContext context) => AlertDialog(
    backgroundColor: homeBackground,
    title: Text(widget.initial == null ? '添加待办' : '编辑待办与提醒'),
    content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: [
      TextField(controller: _controller, autofocus: true, decoration: const InputDecoration(hintText: '想做什么？')),
      ListTile(title: Text('${_date.year}/${_date.month}/${_date.day}'), onTap: () async {
        final date = await showDatePicker(context: context, initialDate: _date,
          firstDate: DateTime(2020), lastDate: DateTime(2100));
        if (date != null && mounted) setState(() => _date = date);
      }),
      ListTile(title: Text(_time == null ? '不提醒' : '提醒时间：${_time!.format(context)}'),
        trailing: _time == null ? null : IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() { _time = null; })),
        onTap: () async {
          final time = await showTimePicker(context: context, initialTime: _time ?? TimeOfDay.now());
          if (time != null && mounted) setState(() => _time = time);
        }),
    ])),
    actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('取消')),
      FilledButton(onPressed: _submit, child: const Text('保存'))],
  );
}

class _ImportantDateEditorDialogState
    extends State<_ImportantDateEditorDialog> {
  late final TextEditingController _controller;
  late DateTime _date;
  late ImportantDateType _type;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initial?.title ?? '');
    _date = widget.initial?.date ?? widget.defaultDate;
    _type = widget.initial?.type ?? ImportantDateType.anniversary;
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _pickDate() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _date,
      firstDate: DateTime(1900),
      lastDate: DateTime(2100),
    );
    if (picked != null && mounted) setState(() => _date = picked);
  }

  void _save() {
    final title = _controller.text.trim();
    if (title.isEmpty) return;
    Navigator.of(context).pop(
      ImportantDate(
        id: widget.initial?.id,
        title: title,
        date: _date,
        type: _type,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: homeBackground,
      title: Text(widget.initial == null ? '添加重要日子' : '编辑重要日子'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _controller,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: '名称',
              hintText: '例如：结婚纪念日',
            ),
          ),
          const SizedBox(height: 12),
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(
              Icons.calendar_today_outlined,
              color: homeAccent,
            ),
            title: Text('${_date.year}年${_date.month}月${_date.day}日'),
            onTap: _pickDate,
          ),
          DropdownButtonFormField<ImportantDateType>(
            initialValue: _type,
            isExpanded: true,
            decoration: const InputDecoration(
              labelText: '日期类型',
              prefixIcon: Icon(Icons.category_outlined, color: homeAccent),
            ),
            items: ImportantDateType.values
                .map(
                  (type) => DropdownMenuItem(
                    value: type,
                    child: Text(
                      switch (type) {
                        ImportantDateType.anniversary => '纪念日（自动算周年）',
                        ImportantDateType.birthday => '生日（每年）',
                        ImportantDateType.yearly => '每年重复',
                        ImportantDateType.oneTime => '一次性日期',
                      },
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                )
                .toList(),
            onChanged: (value) {
              if (value != null) setState(() => _type = value);
            },
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(onPressed: _save, child: const Text('保存')),
      ],
    );
  }
}

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';

import '../models/timeline_event.dart';
import '../services/libra_api.dart';
import '../services/life_status_display.dart';
import '../widgets/companion_end_button.dart';
import '../services/display_names.dart';
import '../services/libra_schedule_day.dart';
import 'home_page.dart';

class LibraActivityPage extends StatefulWidget {
  const LibraActivityPage({super.key, this.api});

  final LibraApi? api;

  @override
  State<LibraActivityPage> createState() => _LibraActivityPageState();
}

class _LibraActivityPageState extends State<LibraActivityPage> {
  late final _api = widget.api ?? LibraApi();
  late Future<_ActivityDetailData> _data;
  Timer? _refreshTimer;
  LifeSystemStatus? _latestStatus;
  late DateTime _selectedTimelineDay;
  late DateTime _observedTimelineToday;
  List<TimelineEvent>? _selectedTimelineEvents;
  bool _timelineLoading = false;
  bool _refreshing = false;

  @override
  void initState() {
    super.initState();
    _selectedTimelineDay = libraScheduleDay();
    _observedTimelineToday = _selectedTimelineDay;
    _data = _loadData();
    _refreshTimer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => unawaited(_refreshLifeState()),
    );
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _api.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: DecoratedBox(
        decoration: const BoxDecoration(
          image: DecorationImage(
            image: AssetImage('assets/images/home_background.png'),
            fit: BoxFit.cover,
            alignment: Alignment.topCenter,
          ),
        ),
        child: SafeArea(
          child: FutureBuilder<_ActivityDetailData>(
            future: _data,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(
                  child: CircularProgressIndicator(color: homeAccent),
                );
              }
              if (snapshot.hasError) {
                return _ErrorView(onRetry: _reload);
              }
              final data = snapshot.data!;
              return Column(
                children: [
                  _Header(onBack: _goBack),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(14, 4, 14, 14),
                      child: Column(
                        children: [
                          SizedBox(
                            height: 142,
                            child: _LifeStatusCard(
                              status: _latestStatus ?? data.lifeStatus,
                              onCompanionEnded: () =>
                                  unawaited(_refreshLifeState()),
                            ),
                          ),
                          const SizedBox(height: 8),
                          Expanded(
                            child: _TimelineCard(
                              events: _withCoarsePlans(
                                _selectedTimelineEvents ?? data.events,
                                _latestStatus ?? data.lifeStatus,
                                _selectedTimelineDay,
                              ),
                              selectedDay: _selectedTimelineDay,
                              loading: _timelineLoading,
                              onDayChanged: _changeTimelineDay,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }

  void _goBack() => Navigator.of(context).pop();

  List<TimelineEvent> _withCoarsePlans(
    List<TimelineEvent> events,
    LifeSystemStatus status,
    DateTime selectedDay,
  ) {
    final rows = <TimelineEvent>[...events];
    rows.sort((a, b) => a.occurredAt.compareTo(b.occurredAt));
    return rows;
  }

  Future<_ActivityDetailData> _loadData() async {
    final values = await Future.wait<Object>([
      _api.getLifeSystemStatus(),
      _api.getLibraTimelineEvents(_selectedTimelineDay),
    ]);
    return _ActivityDetailData(
      lifeStatus: values[0] as LifeSystemStatus,
      events: values[1] as List<TimelineEvent>,
    );
  }

  Future<void> _refreshLifeState() async {
    if (_refreshing) return;
    _refreshing = true;
    try {
      final today = libraScheduleDay();
      final selected =
          _selectedTimelineDay == _observedTimelineToday ||
              today.difference(_selectedTimelineDay).inDays > 2
          ? today
          : _selectedTimelineDay;
      final requestedDay = _selectedTimelineDay;
      final values = await Future.wait<Object>([
        _api.getLifeSystemStatus(),
        _api.getLibraTimelineEvents(selected),
      ]);
      if (mounted) {
        setState(() {
          _latestStatus = values[0] as LifeSystemStatus;
          if (_selectedTimelineDay == requestedDay && !_timelineLoading) {
            _selectedTimelineDay = selected;
            _selectedTimelineEvents = values[1] as List<TimelineEvent>;
            _observedTimelineToday = today;
          }
        });
      }
    } catch (_) {
      // Keep the last verified life snapshot and retry on the next refresh.
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _reload() async {
    setState(() => _data = _loadData());
    await _data;
  }

  Future<void> _changeTimelineDay(DateTime day) async {
    final selected = DateUtils.dateOnly(day);
    if (selected == _selectedTimelineDay || _timelineLoading) return;
    setState(() {
      _timelineLoading = true;
    });
    try {
      final events = await _api.getLibraTimelineEvents(selected);
      if (mounted) {
        setState(() {
          _selectedTimelineDay = selected;
          _selectedTimelineEvents = events;
        });
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('事件加载失败，请稍后重试')));
      }
    } finally {
      if (mounted) setState(() => _timelineLoading = false);
    }
  }
}

class _ActivityDetailData {
  const _ActivityDetailData({required this.lifeStatus, required this.events});

  final LifeSystemStatus lifeStatus;
  final List<TimelineEvent> events;
}

class _Header extends StatelessWidget {
  const _Header({required this.onBack});

  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 54,
    child: Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.only(left: 18),
        child: InkWell(
          onTap: onBack,
          borderRadius: BorderRadius.circular(24),
          child: Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .48),
              shape: BoxShape.circle,
              border: Border.all(color: homeAccent.withValues(alpha: .34)),
            ),
            child: const Icon(Icons.chevron_left_rounded, color: homeAccent),
          ),
        ),
      ),
    ),
  );
}

class _LifeStatusCard extends StatelessWidget {
  const _LifeStatusCard({required this.status, required this.onCompanionEnded});

  final VoidCallback onCompanionEnded;

  final LifeSystemStatus status;

  @override
  Widget build(BuildContext context) {
    final activity = status.activity;
    final coarseActivity = status.coarseActivity;
    final sleeping = status.sleepStatus == 'sleeping';
    final stateText = coarseLifeStatusLabel(status);
    final actionText = sleeping
        ? '正在睡觉'
        : status.companionSessionId == null && activity?.kind == 'watching'
        ? movieProgressLabel(activity!)
        : coarseActivity != null
        ? _coarseActivityDescription(coarseActivity)
        : activity == null
        ? '暂时没有进行中的活动'
        : _activityDescription(activity);
    return _GlassCard(
      child: Stack(
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(14, 12, 14, 10),
            child: Row(
              children: [
                Container(
                  width: 72,
                  height: 72,
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: Colors.white.withValues(alpha: .75),
                    border: Border.all(
                      color: homeAccent.withValues(alpha: .62),
                      width: 2,
                    ),
                  ),
                  child: ClipOval(
                    child: Image(
                      image:
                          DisplayNames.libraAvatarPath != null &&
                              File(DisplayNames.libraAvatarPath!).existsSync()
                          ? FileImage(File(DisplayNames.libraAvatarPath!))
                          : const AssetImage('assets/avatars/libra.png'),
                      fit: BoxFit.cover,
                    ),
                  ),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            DisplayNames.libra,
                            style: const TextStyle(
                              fontSize: 22,
                              fontWeight: FontWeight.w600,
                              color: Color(0xFF4E4745),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Flexible(child: _StatusChip(text: stateText)),
                        ],
                      ),
                      const SizedBox(height: 9),
                      Visibility(
                        visible: status.companionSessionId == null,
                        maintainState: true,
                        maintainAnimation: true,
                        maintainSize: true,
                        child: _InfoLine(
                          icon: Icons.location_on_rounded,
                          text: '当前位置：${status.placeName}',
                          maxLines: 2,
                        ),
                      ),
                      const SizedBox(height: 5),
                      _InfoLine(
                        icon: _lifeActivityIcon(
                          coarseActivity?.kind ?? activity?.kind,
                          sleeping: sleeping,
                        ),
                        text: actionText,
                        maxLines: 2,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (status.companionSessionId != null)
            Positioned(
              top: 0,
              right: 0,
              child: CompanionEndButton(
                sessionId: status.companionSessionId!,
                onEnded: onCompanionEnded,
                iconOnly: true,
              ),
            ),
        ],
      ),
    );
  }

  String _activityDescription(LifeActivityStatus activity) {
    final label = switch (activity.kind) {
      'moving' => '正在前往${activity.targetName}',
      'work' => '正在工作',
      'reading' => '正在阅读',
      'watching' => '正在观影',
      'cooking' => '正在做饭',
      'serving' => '正在搬运餐食',
      'eating' => '正在吃饭',
      'showering' => '正在洗澡',
      _ => '正在进行活动',
    };
    if (activity.kind != 'reading' && activity.kind != 'watching') {
      return label;
    }
    final total = activity.total;
    if (total == null || total == 0) return label;
    return '$label · 进度 ${activity.progress}/$total';
  }

  String _coarseActivityDescription(LifeCoarseActivity activity) {
    final title = DisplayNames.companionText(activity.title.trim());
    if (title.isNotEmpty) return '当前安排：$title';
    return switch (activity.kind) {
      'working' || 'work' => '正在工作',
      'eating' || 'meal' => '正在用餐',
      'exercising' || 'exercise' => '正在运动',
      'resting' || 'rest' => '正在休息',
      'commuting' || 'commute' => '正在通勤',
      _ => '正在进行当前安排',
    };
  }
}

IconData _lifeActivityIcon(String? kind, {required bool sleeping}) {
  if (sleeping) return Icons.bedtime_rounded;
  return switch (kind) {
    'working' => Icons.work_outline_rounded,
    'eating' => Icons.restaurant_rounded,
    'exercising' => Icons.fitness_center_rounded,
    'resting' => Icons.self_improvement_rounded,
    'commuting' => Icons.directions_walk_rounded,
    'moving' => Icons.directions_walk_rounded,
    'work' => Icons.work_outline_rounded,
    'reading' => Icons.menu_book_rounded,
    'watching' => Icons.movie_outlined,
    'cooking' => Icons.soup_kitchen_rounded,
    'serving' => Icons.room_service_outlined,
    'showering' => Icons.shower_rounded,
    _ => Icons.auto_awesome_rounded,
  };
}

class _TimelineCard extends StatefulWidget {
  const _TimelineCard({
    required this.events,
    required this.selectedDay,
    required this.loading,
    required this.onDayChanged,
  });

  final List<TimelineEvent> events;
  final DateTime selectedDay;
  final bool loading;
  final ValueChanged<DateTime> onDayChanged;

  @override
  State<_TimelineCard> createState() => _TimelineCardState();
}

class _TimelineCardState extends State<_TimelineCard> {
  final _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _scrollToLatest();
  }

  @override
  void didUpdateWidget(covariant _TimelineCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.events.length != widget.events.length) _scrollToLatest();
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToLatest() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scrollController.hasClients) return;
      _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
    });
  }

  @override
  Widget build(BuildContext context) {
    final today = libraScheduleDay();
    final offset = today.difference(widget.selectedDay).inDays;
    final label = switch (offset) {
      1 => '昨天动态',
      2 => '前天动态',
      _ => '今日动态',
    };
    return _GlassCard(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Spacer(),
                PopupMenuButton<int>(
                  initialValue: offset.clamp(0, 2),
                  onSelected: (value) => widget.onDayChanged(
                    today.subtract(Duration(days: value)),
                  ),
                  color: const Color(0xFFFFF8F7),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 0, child: Text('今天')),
                    PopupMenuItem(value: 1, child: Text('昨天')),
                    PopupMenuItem(value: 2, child: Text('前天')),
                  ],
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        label,
                        style: TextStyle(
                          color: homeAccent.withValues(alpha: .78),
                          fontSize: 14,
                        ),
                      ),
                      const SizedBox(width: 2),
                      Icon(
                        Icons.keyboard_arrow_down_rounded,
                        size: 18,
                        color: homeAccent.withValues(alpha: .72),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Expanded(
              child: widget.loading
                  ? const Center(
                      child: CircularProgressIndicator(color: homeAccent),
                    )
                  : widget.events.isEmpty
                  ? Center(
                      child: Text(
                        '$label暂无记录',
                        style: const TextStyle(color: homeInactive),
                      ),
                    )
                  : ListView.separated(
                      controller: _scrollController,
                      padding: EdgeInsets.zero,
                      physics: const BouncingScrollPhysics(),
                      itemCount: widget.events.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 2),
                      itemBuilder: (_, index) =>
                          _TimelineRow(widget.events[index]),
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TimelineRow extends StatelessWidget {
  const _TimelineRow(this.event);

  final TimelineEvent event;

  @override
  Widget build(BuildContext context) => IntrinsicHeight(
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 30,
          child: Icon(
            _eventIcon(event.event),
            size: 18,
            color: homeAccent.withValues(alpha: .72),
          ),
        ),
        SizedBox(
          width: 48,
          child: Text(
            _time(event.occurredAt),
            style: TextStyle(
              fontSize: 13,
              color: homeAccent.withValues(alpha: .78),
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Text(
              _displayEvent(event.event),
              style: const TextStyle(
                fontSize: 14,
                height: 1.3,
                color: Color(0xFF5C5553),
              ),
            ),
          ),
        ),
      ],
    ),
  );

  String _displayEvent(String event) {
    final text = DisplayNames.companionText(event.trim());
    if (text.startsWith('左然')) {
      return '${DisplayNames.libra}${text.substring(2)}';
    }
    if (text.startsWith('Libra')) {
      return '${DisplayNames.libra}${text.substring(5)}';
    }
    return '${DisplayNames.libra}$text';
  }
}

class _GlassCard extends StatelessWidget {
  const _GlassCard({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .68),
      borderRadius: BorderRadius.circular(24),
      border: Border.all(
        color: Colors.white.withValues(alpha: .92),
        width: 1.4,
      ),
      boxShadow: [
        BoxShadow(
          color: homeAccent.withValues(alpha: .17),
          blurRadius: 18,
          offset: const Offset(0, 6),
        ),
      ],
    ),
    child: child,
  );
}

class _StatusChip extends StatelessWidget {
  const _StatusChip({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
    decoration: BoxDecoration(
      gradient: LinearGradient(
        colors: [
          Colors.white.withValues(alpha: .88),
          const Color(0xFFFFE4E6).withValues(alpha: .92),
        ],
      ),
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: homeAccent.withValues(alpha: .52)),
      boxShadow: [
        BoxShadow(
          color: homeAccent.withValues(alpha: .20),
          blurRadius: 9,
          offset: const Offset(0, 3),
        ),
      ],
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(
          Icons.favorite_rounded,
          size: 11,
          color: homeAccent.withValues(alpha: .68),
        ),
        const SizedBox(width: 4),
        Flexible(
          child: Text(
            text,
            maxLines: 1,
            softWrap: false,
            overflow: TextOverflow.fade,
            style: const TextStyle(
              color: Color(0xFFEE6868),
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ],
    ),
  );
}

class _InfoLine extends StatelessWidget {
  const _InfoLine({required this.icon, required this.text, this.maxLines = 1});

  final IconData icon;
  final String text;
  final int maxLines;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Icon(icon, color: homeAccent.withValues(alpha: .76), size: 18),
      const SizedBox(width: 6),
      Expanded(
        child: Text(
          text,
          maxLines: maxLines,
          overflow: TextOverflow.visible,
          style: const TextStyle(fontSize: 13, color: Color(0xFF655E5C)),
        ),
      ),
    ],
  );
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.onRetry});

  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text('动态加载失败', style: TextStyle(color: Color(0xFF655E5C))),
        TextButton(onPressed: onRetry, child: const Text('重新加载')),
      ],
    ),
  );
}

IconData _eventIcon(String description) {
  if (description.contains('到达') || description.contains('离开')) {
    return Icons.location_on_rounded;
  }
  if (description.contains('WIFI') || description.contains('WiFi')) {
    return Icons.wifi_rounded;
  }
  if (description.contains('移动数据')) {
    return Icons.signal_cellular_alt_rounded;
  }
  if (description.contains('充电')) return Icons.battery_charging_full_rounded;
  if (description.contains('打卡')) return Icons.event_available_rounded;
  if (description.contains('工作')) return Icons.work_outline_rounded;
  if (description.contains('运动')) return Icons.directions_run_rounded;
  if (description.contains('打开') || description.contains('关闭')) {
    return Icons.apps_rounded;
  }
  return Icons.auto_awesome_rounded;
}

String _time(DateTime value) =>
    '${value.hour.toString().padLeft(2, '0')}:${value.minute.toString().padLeft(2, '0')}';

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:dotted_border/dotted_border.dart';

import '../models/weather_summary.dart';
import '../models/app_usage_event.dart';
import '../models/timeline_event.dart';
import '../services/libra_api.dart';
import 'home_life_events.dart';

const homeBackground = Color(0xFFFFF8F8);
const homeHeader = Color(0xFFF7E3E1);
const homeAccent = Color(0xFFDE776C);
const homeInactive = Color(0xFF9DAAAD);

const _statusOptions = <(String, IconData)>[
  ('元气满满', Icons.wb_sunny_outlined),
  ('专注', Icons.star_border_rounded),
  ('忙碌', Icons.work_outline_rounded),
  ('有点累', Icons.sentiment_dissatisfied_rounded),
  ('疲惫', Icons.sentiment_very_dissatisfied_rounded),
  ('放松', Icons.eco_outlined),
  ('悠闲', Icons.local_cafe_outlined),
  ('心情不错', Icons.sentiment_satisfied_alt_rounded),
  ('紧绷', Icons.bolt_rounded),
  ('在路上', Icons.directions_car_outlined),
  ('运动中', Icons.directions_run_rounded),
  ('休息中', Icons.bedtime_outlined),
];

class HomePage extends StatelessWidget {
  const HomePage({
    super.key,
    required this.note,
    required this.weather,
    required this.weatherLoading,
    required this.weatherError,
    required this.onWeatherRetry,
    required this.usageEvents,
    this.lifeEvents,
    this.coarseActivity,
    this.coarsePlans = const [],
    this.lifeEventsLoading = false,
    this.companionSessionId,
    this.onCompanionEnded,
    required this.libraStatus,
    required this.userStatus,
    required this.onUserStatusChanged,
    required this.onManualTimelineAdded,
    required this.onSettingsTap,
    required this.onLibraTimelineTap,
    required this.todayMessageCount,
    required this.todayAppDuration,
    required this.lastChatAt,
    required this.libraName,
    required this.userName,
    required this.libraNickname,
    required this.userNickname,
    required this.metAt,
    this.libraAvatarPath,
    this.userAvatarPath,
  });

  final String note;
  final WeatherSummary? weather;
  final bool weatherLoading;
  final String? weatherError;
  final VoidCallback onWeatherRetry;
  final List<AppUsageEvent> usageEvents;
  final List<TimelineEvent>? lifeEvents;
  final LifeCoarseActivity? coarseActivity;
  final List<LifeScheduleEntry> coarsePlans;
  final bool lifeEventsLoading;
  final String? companionSessionId;
  final VoidCallback? onCompanionEnded;
  final String libraStatus;
  final String userStatus;
  final ValueChanged<String> onUserStatusChanged;
  final Future<void> Function(DateTime occurredAt, String description)
  onManualTimelineAdded;
  final VoidCallback onSettingsTap;
  final VoidCallback onLibraTimelineTap;
  final int todayMessageCount;
  final Duration todayAppDuration;
  final DateTime? lastChatAt;
  final String libraName;
  final String userName;
  final String libraNickname;
  final String userNickname;
  final DateTime metAt;
  final String? libraAvatarPath;
  final String? userAvatarPath;

  int get _daysTogether {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    return today
        .difference(DateTime(metAt.year, metAt.month, metAt.day))
        .inDays;
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox.expand(
      child: LayoutBuilder(
        builder: (context, constraints) {
          final widthScale = (constraints.maxWidth / 595).clamp(0.52, 0.80);
          final heightScale = (constraints.maxHeight / 1045).clamp(0.52, 0.80);
          final scale = widthScale < heightScale ? widthScale : heightScale;
          double d(double value) => value * scale;
          return SingleChildScrollView(
            physics: const BouncingScrollPhysics(),
            padding: EdgeInsets.fromLTRB(d(28), 0, d(28), d(28)),
            child: Column(
              children: [
                SizedBox(
                  height: d(50),
                  child: Stack(
                    alignment: Alignment.bottomCenter,
                    children: [
                      Text(
                        'W E L C O M E    H O M E',
                        style: TextStyle(
                          color: homeAccent,
                          fontSize: d(16),
                          fontWeight: FontWeight.w700,
                          letterSpacing: d(1.8),
                        ),
                      ),
                      Align(
                        alignment: Alignment.bottomLeft,
                        child: Transform.translate(
                          offset: Offset(-d(18), 0),
                          child: IconButton(
                            onPressed: onSettingsTap,
                            padding: EdgeInsets.zero,
                            constraints: const BoxConstraints(),
                            icon: Icon(
                              Icons.settings_outlined,
                              size: d(40),
                              color: homeInactive,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(height: d(14)),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Text.rich(
                    TextSpan(
                      children: [
                        TextSpan(text: '$libraName '),
                        const TextSpan(
                          text: '&',
                          style: TextStyle(color: Color(0xFFD85042)),
                        ),
                        TextSpan(text: ' $userName'),
                      ],
                    ),
                    maxLines: 1,
                    style: TextStyle(
                      fontSize: d(58),
                      fontStyle: FontStyle.italic,
                      fontFamily: 'serif',
                      letterSpacing: d(3),
                      color: const Color(0xFF393534),
                    ),
                  ),
                ),
                SizedBox(height: d(12)),
                Wrap(
                  alignment: WrapAlignment.center,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  spacing: d(12),
                  children: [
                    Text(
                      '$_daysTogether',
                      style: TextStyle(
                        color: const Color(0xFFD85042),
                        fontSize: d(30),
                        fontStyle: FontStyle.italic,
                        fontWeight: FontWeight.w600,
                        letterSpacing: d(3),
                      ),
                    ),
                    Text(
                      'days together',
                      style: TextStyle(fontSize: d(17), letterSpacing: d(3)),
                    ),
                  ],
                ),
                SizedBox(height: d(6)),
                Text(
                  'Since ${metAt.year}.${metAt.month}.${metAt.day}',
                  style: TextStyle(fontSize: d(17), letterSpacing: d(3)),
                ),
                SizedBox(height: d(24)),
                _HomeCard(
                  height: d(132),
                  padding: 0,
                  radius: d(24),
                  child: _QuoteCard(note: note, scale: scale),
                ),
                SizedBox(height: d(14)),
                Row(
                  children: [
                    Expanded(
                      flex: 14,
                      child: _HomeCard(
                        height: d(234),
                        padding: d(18),
                        radius: d(22),
                        child: _WeatherCard(
                          weather: weather,
                          loading: weatherLoading,
                          error: weatherError,
                          onRetry: onWeatherRetry,
                          scale: scale,
                        ),
                      ),
                    ),
                    SizedBox(width: d(12)),
                    Expanded(
                      flex: 8,
                      child: _HomeCard(
                        height: d(234),
                        padding: d(12),
                        radius: d(22),
                        child: _TogetherCard(
                          scale: scale,
                          todayMessageCount: todayMessageCount,
                          todayAppDuration: todayAppDuration,
                          lastChatAt: lastChatAt,
                        ),
                      ),
                    ),
                  ],
                ),
                SizedBox(height: d(14)),
                _HomeCard(
                  height: d(470),
                  padding: d(14),
                  radius: d(24),
                  child: _ActivityCard(
                    events: usageEvents,
                    lifeEvents: lifeEvents,
                    coarseActivity: coarseActivity,
                    coarsePlans: coarsePlans,
                    lifeEventsLoading: lifeEventsLoading,
                    companionSessionId: companionSessionId,
                    onCompanionEnded: onCompanionEnded,
                    libraStatus: libraStatus,
                    userStatus: userStatus,
                    onUserStatusChanged: onUserStatusChanged,
                    onManualTimelineAdded: onManualTimelineAdded,
                    onLibraTimelineTap: onLibraTimelineTap,
                    libraAvatarPath: libraAvatarPath,
                    userAvatarPath: userAvatarPath,
                    libraNickname: libraNickname,
                    userNickname: userNickname,
                    scale: scale,
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _TogetherCard extends StatelessWidget {
  const _TogetherCard({
    required this.scale,
    required this.todayMessageCount,
    required this.todayAppDuration,
    required this.lastChatAt,
  });

  final double scale;
  final int todayMessageCount;
  final Duration todayAppDuration;
  final DateTime? lastChatAt;

  @override
  Widget build(BuildContext context) {
    final elapsed = lastChatAt == null
        ? null
        : DateTime.now().difference(lastChatAt!);
    final isRecent =
        elapsed != null &&
        !elapsed.isNegative &&
        elapsed < const Duration(minutes: 5);
    final isAway = elapsed != null && elapsed > const Duration(hours: 1);
    final asset = isRecent
        ? 'assets/images/companion_love.png'
        : isAway
        ? 'assets/images/companion_moon.png'
        : 'assets/images/companion_stars.png';
    final status = isRecent ? '陪着你' : (isAway ? '等你回来' : '一直都在');

    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        SizedBox(
          width: 152 * scale,
          height: 74 * scale,
          child: Image.asset(asset, fit: BoxFit.cover),
        ),
        SizedBox(height: 2 * scale),
        Text(
          '今日陪伴',
          style: TextStyle(color: homeInactive, fontSize: 15.5 * scale),
        ),
        SizedBox(height: 2 * scale),
        Text(
          status,
          style: TextStyle(
            color: const Color(0xFF4D4745),
            fontSize: 22 * scale,
            fontWeight: FontWeight.w600,
          ),
        ),
        SizedBox(height: 6 * scale),
        Container(
          width: 38 * scale,
          height: 3 * scale,
          decoration: BoxDecoration(
            color: homeAccent.withValues(alpha: .62),
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        SizedBox(height: 7 * scale),
        FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            '$todayMessageCount条消息 · ${_durationText(todayAppDuration)}',
            maxLines: 1,
            style: TextStyle(color: homeInactive, fontSize: 14 * scale),
          ),
        ),
        SizedBox(height: 2 * scale),
        Text(
          _lastChatText(elapsed),
          style: TextStyle(color: homeInactive, fontSize: 14 * scale),
        ),
      ],
    );
  }

  String _durationText(Duration duration) {
    final hours = duration.inHours;
    final minutes = duration.inMinutes.remainder(60);
    if (hours > 0) return '${hours}h${minutes}min';
    if (minutes > 0) return '${minutes}min';
    return '不足1min';
  }

  String _lastChatText(Duration? elapsed) {
    if (lastChatAt == null || elapsed == null) return '暂无聊天';
    if (elapsed.isNegative || elapsed.inMinutes < 1) return '刚刚';
    if (elapsed.inHours < 1) return '${elapsed.inMinutes}分钟前';
    if (elapsed.inHours < 24) return '${elapsed.inHours}小时前';
    final time = lastChatAt!;
    return '${time.month.toString().padLeft(2, '0')}.${time.day.toString().padLeft(2, '0')} '
        '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  }
}

class _ActivityCard extends StatelessWidget {
  const _ActivityCard({
    required this.events,
    this.lifeEvents,
    this.coarseActivity,
    this.coarsePlans = const [],
    this.lifeEventsLoading = false,
    this.companionSessionId,
    this.onCompanionEnded,
    required this.libraStatus,
    required this.userStatus,
    required this.onUserStatusChanged,
    required this.onManualTimelineAdded,
    required this.onLibraTimelineTap,
    this.libraAvatarPath,
    this.userAvatarPath,
    required this.libraNickname,
    required this.userNickname,
    required this.scale,
  });

  final List<AppUsageEvent> events;
  final List<TimelineEvent>? lifeEvents;
  final LifeCoarseActivity? coarseActivity;
  final List<LifeScheduleEntry> coarsePlans;
  final bool lifeEventsLoading;
  final String? companionSessionId;
  final VoidCallback? onCompanionEnded;
  final String libraStatus;
  final String userStatus;
  final ValueChanged<String> onUserStatusChanged;
  final Future<void> Function(DateTime occurredAt, String description)
  onManualTimelineAdded;
  final VoidCallback onLibraTimelineTap;
  final String? libraAvatarPath;
  final String? userAvatarPath;
  final String libraNickname;
  final String userNickname;
  final double scale;

  String _time(DateTime value) {
    final hour = value.hour.toString().padLeft(2, '0');
    final minute = value.minute.toString().padLeft(2, '0');
    return '$hour:$minute';
  }

  Future<void> _addManualTimelineEvent(BuildContext context) async {
    var occurredAt = DateTime.now();
    var subject = userNickname;
    var content = '';
    final result = await showDialog<_ManualTimelineDraft>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('添加一条动态'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextButton.icon(
                  onPressed: () async {
                    final date = await showDatePicker(
                      context: dialogContext,
                      initialDate: occurredAt,
                      firstDate: DateTime(2020),
                      lastDate: DateTime(2100),
                      helpText: '选择日期',
                      confirmText: '确定',
                      cancelText: '取消',
                    );
                    if (date == null || !dialogContext.mounted) return;
                    final time = await showTimePicker(
                      context: dialogContext,
                      initialTime: TimeOfDay.fromDateTime(occurredAt),
                      helpText: '选择时间',
                      confirmText: '确定',
                      cancelText: '取消',
                    );
                    if (time == null) return;
                    setDialogState(() {
                      occurredAt = DateTime(
                        date.year,
                        date.month,
                        date.day,
                        time.hour,
                        time.minute,
                      );
                    });
                  },
                  icon: const Icon(Icons.schedule_rounded),
                  label: Text(
                    '${occurredAt.year}.${occurredAt.month.toString().padLeft(2, '0')}.${occurredAt.day.toString().padLeft(2, '0')} '
                    '${_time(occurredAt)}',
                  ),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  initialValue: subject,
                  onChanged: (value) => subject = value,
                  decoration: const InputDecoration(
                    labelText: '人称',
                    hintText: '例如：我、Simple',
                  ),
                ),
                const SizedBox(height: 10),
                TextFormField(
                  onChanged: (value) => content = value,
                  maxLines: 3,
                  textCapitalization: TextCapitalization.sentences,
                  decoration: const InputDecoration(
                    labelText: '动态内容',
                    hintText: '例如：开始整理今天的笔记',
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  '会以“人称 + 内容”的形式记录，并同步给左然。',
                  style: TextStyle(fontSize: 12, color: Color(0xFF8D817E)),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () {
                final cleanSubject = subject.trim();
                final cleanContent = content.trim();
                if (cleanContent.isEmpty) return;
                final description = cleanSubject.isEmpty
                    ? cleanContent
                    : '$cleanSubject$cleanContent';
                Navigator.pop(
                  dialogContext,
                  _ManualTimelineDraft(occurredAt, description),
                );
              },
              child: const Text('添加'),
            ),
          ],
        ),
      ),
    );
    if (result == null) return;
    try {
      await onManualTimelineAdded(result.occurredAt, result.description);
      if (context.mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('动态已添加，左然会看到这条变化。')));
      }
    } catch (_) {
      if (context.mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('动态已保存到本机，连接后端后会自动同步。')));
      }
    }
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

  Widget _eventRow(DateTime occurredAt, String description) {
    return Container(
      padding: EdgeInsets.symmetric(horizontal: 7 * scale, vertical: 7 * scale),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: EdgeInsets.only(top: 1.5 * scale),
            child: Icon(
              _eventIcon(description),
              size: 20 * scale,
              color: homeAccent.withValues(alpha: .78),
            ),
          ),
          SizedBox(width: 6 * scale),
          SizedBox(
            width: 48 * scale,
            child: Text(
              _time(occurredAt),
              style: TextStyle(
                fontSize: 15 * scale,
                color: homeAccent.withValues(alpha: .72),
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          SizedBox(width: 5 * scale),
          Expanded(
            child: Text(
              description,
              style: TextStyle(
                fontSize: 17 * scale,
                height: 1.42,
                color: const Color(0xFF5D5755),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _userEventText(String description) {
    var text = description.trim();
    if (userNickname.isNotEmpty && text.startsWith(userNickname)) return text;
    text = text.replaceFirst(
      RegExp(r'^(?:用户|我|simple)', caseSensitive: false),
      '',
    );
    while (text.toLowerCase().startsWith('simple')) {
      text = text.substring(6);
    }
    return '$userNickname$text';
  }

  Widget _eventSeparator() => SizedBox(height: 4 * scale);

  Future<void> _editStatus(
    BuildContext context,
    String current,
    ValueChanged<String> onChanged,
  ) async {
    var selected = _statusOptions.any((item) => item.$1 == current)
        ? current
        : _statusOptions.first.$1;
    final result = await showDialog<String>(
      context: context,
      barrierColor: const Color(0xFF4A3D3D).withValues(alpha: .56),
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => Dialog(
          insetPadding: const EdgeInsets.symmetric(horizontal: 22),
          backgroundColor: Colors.transparent,
          child: Container(
            constraints: const BoxConstraints(maxWidth: 390),
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 20),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(28),
              border: Border.all(color: Colors.white, width: 1.5),
              image: const DecorationImage(
                image: AssetImage('assets/images/state_back.png'),
                fit: BoxFit.fill,
              ),
              boxShadow: [
                BoxShadow(
                  color: homeAccent.withValues(alpha: .32),
                  blurRadius: 28,
                  offset: const Offset(0, 12),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: IconButton(
                    onPressed: () => Navigator.pop(dialogContext),
                    icon: const Icon(Icons.close_rounded, color: homeAccent),
                  ),
                ),
                const Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      Icons.auto_awesome_rounded,
                      size: 21,
                      color: Color(0xFFE98992),
                    ),
                    SizedBox(width: 12),
                    Text(
                      '设置状态',
                      style: TextStyle(
                        fontSize: 23,
                        fontWeight: FontWeight.w600,
                        color: Color(0xFF554B4A),
                      ),
                    ),
                    SizedBox(width: 12),
                    Icon(
                      Icons.auto_awesome_rounded,
                      size: 21,
                      color: Color(0xFFE98992),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                const Text(
                  '选择你当前展示的状态',
                  style: TextStyle(fontSize: 13, color: Color(0xFF9B8887)),
                ),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 24,
                    vertical: 9,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: .76),
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(
                      color: homeAccent.withValues(alpha: .42),
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: homeAccent.withValues(alpha: .18),
                        blurRadius: 10,
                        offset: const Offset(0, 3),
                      ),
                    ],
                  ),
                  child: Text(
                    selected,
                    style: const TextStyle(
                      color: homeAccent,
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                const SizedBox(height: 15),
                GridView.builder(
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  itemCount: _statusOptions.length,
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 3,
                    mainAxisSpacing: 10,
                    crossAxisSpacing: 9,
                    childAspectRatio: 2.15,
                  ),
                  itemBuilder: (_, index) {
                    final option = _statusOptions[index];
                    final active = selected == option.$1;
                    return InkWell(
                      onTap: () => setDialogState(() => selected = option.$1),
                      borderRadius: BorderRadius.circular(18),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 160),
                        decoration: BoxDecoration(
                          gradient: active
                              ? const LinearGradient(
                                  colors: [
                                    Color(0xFFF39A9A),
                                    Color(0xFFE97D7D),
                                  ],
                                )
                              : null,
                          color: active
                              ? null
                              : Colors.white.withValues(alpha: .58),
                          borderRadius: BorderRadius.circular(18),
                          border: Border.all(
                            color: active
                                ? Colors.white.withValues(alpha: .84)
                                : homeAccent.withValues(alpha: .28),
                          ),
                          boxShadow: active
                              ? [
                                  BoxShadow(
                                    color: homeAccent.withValues(alpha: .28),
                                    blurRadius: 9,
                                    offset: const Offset(0, 3),
                                  ),
                                ]
                              : null,
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(
                              option.$2,
                              size: 17,
                              color: active ? Colors.white : homeAccent,
                            ),
                            const SizedBox(width: 4),
                            Flexible(
                              child: FittedBox(
                                fit: BoxFit.scaleDown,
                                child: Text(
                                  option.$1,
                                  maxLines: 1,
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: active
                                        ? Colors.white
                                        : const Color(0xFF756866),
                                    fontWeight: active
                                        ? FontWeight.w600
                                        : FontWeight.w400,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
                const SizedBox(height: 19),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () => Navigator.pop(dialogContext),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: const Color(0xFF756866),
                          side: BorderSide(
                            color: homeAccent.withValues(alpha: .30),
                          ),
                          minimumSize: const Size.fromHeight(46),
                          shape: const StadiumBorder(),
                          backgroundColor: Colors.white.withValues(alpha: .66),
                        ),
                        child: const Text('取消'),
                      ),
                    ),
                    const SizedBox(width: 13),
                    Expanded(
                      child: FilledButton(
                        onPressed: () => Navigator.pop(dialogContext, selected),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFFE98080),
                          minimumSize: const Size.fromHeight(46),
                          shape: const StadiumBorder(),
                          elevation: 4,
                          shadowColor: homeAccent.withValues(alpha: .34),
                        ),
                        child: const Text('确认'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
    if (result != null) onChanged(result);
  }

  @override
  Widget build(BuildContext context) {
    final recentUserEvents = events.length > 10
        ? events.sublist(events.length - 10)
        : events;
    return Column(
      children: [
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 142 * scale,
                child: Stack(
                  children: [
                    _AvatarWithStatus(
                      asset: 'assets/avatars/libra.png',
                      filePath: libraAvatarPath,
                      status: libraStatus,
                      scale: scale,
                      onTap: null,
                    ),
                  ],
                ),
              ),
              SizedBox(width: 8 * scale),
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: onLibraTimelineTap,
                  child: _DashedPanel(
                    scale: scale,
                    padding: EdgeInsets.fromLTRB(
                      12 * scale,
                      9 * scale,
                      8 * scale,
                      9 * scale,
                    ),
                    child: HomeLifeEvents(
                      events: lifeEvents,
                      coarseActivity: coarseActivity,
                      coarsePlans: coarsePlans,
                      loading: lifeEventsLoading,
                      scale: scale,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        Padding(
          padding: EdgeInsets.symmetric(vertical: 9 * scale),
          child: Row(
            children: [
              Expanded(
                child: Divider(color: homeAccent.withValues(alpha: .34)),
              ),
              Padding(
                padding: EdgeInsets.symmetric(horizontal: 8 * scale),
                child: Icon(
                  Icons.favorite_rounded,
                  size: 18 * scale,
                  color: homeAccent.withValues(alpha: .62),
                ),
              ),
              Expanded(
                child: Divider(color: homeAccent.withValues(alpha: .34)),
              ),
            ],
          ),
        ),
        Expanded(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Stack(
                  children: [
                    _DashedPanel(
                      scale: scale,
                      padding: EdgeInsets.fromLTRB(
                        12 * scale,
                        9 * scale,
                        36 * scale,
                        34 * scale,
                      ),
                      child: recentUserEvents.isEmpty
                          ? Center(
                              child: Text(
                                '$userNickname今天还没有活动记录',
                                style: TextStyle(
                                  fontSize: 16 * scale,
                                  color: homeInactive,
                                ),
                              ),
                            )
                          : ListView.separated(
                              padding: EdgeInsets.zero,
                              reverse: true,
                              itemCount: recentUserEvents.length,
                              separatorBuilder: (_, _) => _eventSeparator(),
                              itemBuilder: (_, index) {
                                final event =
                                    recentUserEvents[recentUserEvents.length -
                                        1 -
                                        index];
                                return _eventRow(
                                  event.timestamp,
                                  _userEventText(event.description),
                                );
                              },
                            ),
                    ),
                    Positioned(
                      bottom: 1 * scale,
                      right: 1 * scale,
                      child: IconButton(
                        tooltip: '添加动态',
                        padding: EdgeInsets.zero,
                        constraints: BoxConstraints.tightFor(
                          width: 30 * scale,
                          height: 30 * scale,
                        ),
                        onPressed: () => _addManualTimelineEvent(context),
                        icon: Icon(
                          Icons.edit_note_rounded,
                          color: homeAccent,
                          size: 23 * scale,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              SizedBox(width: 8 * scale),
              _AvatarWithStatus(
                asset: 'assets/avatars/simple.png',
                filePath: userAvatarPath,
                status: userStatus,
                scale: scale,
                onTap: () =>
                    _editStatus(context, userStatus, onUserStatusChanged),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ManualTimelineDraft {
  const _ManualTimelineDraft(this.occurredAt, this.description);

  final DateTime occurredAt;
  final String description;
}

class _DashedPanel extends StatelessWidget {
  const _DashedPanel({required this.scale, this.padding, this.child});

  final double scale;
  final EdgeInsets? padding;
  final Widget? child;

  @override
  Widget build(BuildContext context) => Container(
    padding: EdgeInsets.all(8 * scale),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .62),
      borderRadius: BorderRadius.circular(20 * scale),
      border: Border.all(
        color: Colors.white.withValues(alpha: .90),
        width: 1.5 * scale,
      ),
      boxShadow: [
        BoxShadow(
          color: homeAccent.withValues(alpha: .16),
          blurRadius: 14 * scale,
          spreadRadius: 1 * scale,
          offset: Offset(0, 5 * scale),
        ),
      ],
    ),
    child: DottedBorder(
      options: RoundedRectDottedBorderOptions(
        color: homeAccent.withValues(alpha: .34),
        strokeWidth: 1.4 * scale,
        dashPattern: [5 * scale, 4 * scale],
        radius: Radius.circular(16 * scale),
        padding: padding ?? EdgeInsets.zero,
      ),
      child: SizedBox.expand(child: child),
    ),
  );
}

class _AvatarWithStatus extends StatelessWidget {
  const _AvatarWithStatus({
    required this.asset,
    this.filePath,
    required this.status,
    required this.scale,
    required this.onTap,
  });

  final String asset;
  final String? filePath;
  final String status;
  final double scale;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 142 * scale,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 136 * scale,
            height: 136 * scale,
            padding: EdgeInsets.all(4 * scale),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .88),
              shape: BoxShape.circle,
              border: Border.all(
                color: homeAccent.withValues(alpha: .68),
                width: 2.2 * scale,
              ),
              boxShadow: [
                BoxShadow(
                  color: homeAccent.withValues(alpha: .20),
                  blurRadius: 14 * scale,
                  spreadRadius: 2 * scale,
                  offset: Offset(0, 4 * scale),
                ),
              ],
            ),
            child: ClipOval(
              child: filePath != null && File(filePath!).existsSync()
                  ? Image.file(File(filePath!), fit: BoxFit.cover)
                  : Image.asset(asset, fit: BoxFit.cover),
            ),
          ),
          SizedBox(height: 10 * scale),
          Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: onTap,
              borderRadius: BorderRadius.circular(20 * scale),
              child: Container(
                width: 132 * scale,
                height: 42 * scale,
                alignment: Alignment.center,
                padding: EdgeInsets.symmetric(horizontal: 12 * scale),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    colors: [
                      Colors.white.withValues(alpha: .88),
                      const Color(0xFFFFE4E6).withValues(alpha: .92),
                    ],
                  ),
                  borderRadius: BorderRadius.circular(20 * scale),
                  border: Border.all(
                    color: homeAccent.withValues(alpha: .52),
                    width: 1.5 * scale,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: homeAccent.withValues(alpha: .22),
                      blurRadius: 10 * scale,
                      offset: Offset(0, 3 * scale),
                    ),
                  ],
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Icon(
                      Icons.favorite_rounded,
                      size: 14 * scale,
                      color: homeAccent.withValues(alpha: .68),
                    ),
                    SizedBox(width: 6 * scale),
                    Flexible(
                      child: Text(
                        status,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 15.5 * scale,
                          fontWeight: FontWeight.w500,
                          color: const Color(0xFFEE6868),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _WeatherCard extends StatelessWidget {
  const _WeatherCard({
    required this.weather,
    required this.loading,
    required this.error,
    required this.onRetry,
    required this.scale,
  });

  final WeatherSummary? weather;
  final bool loading;
  final String? error;
  final VoidCallback onRetry;
  final double scale;

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return Center(
        child: SizedBox.square(
          dimension: 22 * scale,
          child: const CircularProgressIndicator(
            color: homeAccent,
            strokeWidth: 2,
          ),
        ),
      );
    }
    if (weather == null) {
      return InkWell(
        onTap: onRetry,
        borderRadius: BorderRadius.circular(18 * scale),
        child: Padding(
          padding: EdgeInsets.symmetric(vertical: 2 * scale),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    Icons.location_on_outlined,
                    size: 24 * scale,
                    color: homeInactive,
                  ),
                  SizedBox(width: 5 * scale),
                  Text(
                    '西安市 · 长安区',
                    style: TextStyle(
                      fontSize: 17 * scale,
                      fontFamily: 'serif',
                      color: const Color(0xFF4D4745),
                    ),
                  ),
                ],
              ),
              Expanded(
                child: Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.cloud_off_outlined,
                        size: 30 * scale,
                        color: homeAccent.withValues(alpha: .62),
                      ),
                      SizedBox(height: 8 * scale),
                      Text(
                        '天气暂时无法获取\n点击重试',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 15 * scale,
                          height: 1.45,
                          color: const Color(0xFF777171),
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

    final data = weather!;
    final contentScale = (scale * 1.22).clamp(.72, 1.0);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Row(
          children: [
            Icon(
              Icons.location_on_outlined,
              size: 24 * contentScale,
              color: homeInactive,
            ),
            SizedBox(width: 5 * contentScale),
            Expanded(
              child: Text(
                '${data.city} · ${data.district}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 16 * contentScale,
                  fontFamily: 'serif',
                  fontWeight: FontWeight.w400,
                  letterSpacing: .4,
                  color: const Color(0xFF4D4745),
                ),
              ),
            ),
            SizedBox(width: 5 * contentScale),
            Transform.flip(
              flipX: !data.isDaytime,
              child: Icon(
                data.isDaytime
                    ? Icons.wb_sunny_outlined
                    : Icons.nightlight_round,
                size: 29 * contentScale,
                color: data.isDaytime
                    ? const Color(0xFFE5A34E)
                    : const Color(0xFF8D8AA7),
              ),
            ),
          ],
        ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text(
              '${data.temperature}°C',
              style: TextStyle(
                fontSize: 34 * contentScale,
                height: 1,
                fontFamily: 'serif',
                fontWeight: FontWeight.w400,
                letterSpacing: .5,
                color: const Color(0xFF302B29),
              ),
            ),
            SizedBox(width: 9 * contentScale),
            Container(
              padding: EdgeInsets.symmetric(
                horizontal: 8 * contentScale,
                vertical: 4 * contentScale,
              ),
              decoration: BoxDecoration(
                color: const Color(0xFFFFE7E3),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                data.currentWeather,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 13 * contentScale,
                  fontFamily: 'serif',
                  color: const Color(0xFF8D5C56),
                  fontWeight: FontWeight.w400,
                ),
              ),
            ),
          ],
        ),
        Row(
          children: [
            Icon(
              Icons.calendar_today_outlined,
              size: 13 * contentScale,
              color: homeInactive,
            ),
            SizedBox(width: 5 * contentScale),
            Expanded(
              child: Text(
                '明天  ${data.tomorrowWeather}  ${data.tomorrowMin}~${data.tomorrowMax}°C',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12.5 * contentScale,
                  fontFamily: 'serif',
                  color: const Color(0xFF696363),
                ),
              ),
            ),
          ],
        ),
        const Divider(height: 1, color: Color(0xFFE6DAD8)),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: EdgeInsets.only(top: 1.5 * contentScale),
              child: Icon(
                Icons.favorite_border_rounded,
                size: 14 * contentScale,
                color: homeAccent,
              ),
            ),
            SizedBox(width: 5 * contentScale),
            Expanded(
              child: Text(
                data.reminder,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 12 * contentScale,
                  height: 1.25,
                  fontFamily: 'serif',
                  color: const Color(0xFF77706E),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _QuoteCard extends StatelessWidget {
  const _QuoteCard({required this.note, required this.scale});

  final String note;
  final double scale;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned(
          left: -22 * scale,
          top: -13 * scale,
          child: Image.asset(
            'assets/images/quote_marks.png',
            width: 110 * scale,
            height: 110 * scale,
            fit: BoxFit.contain,
          ),
        ),
        Positioned.fill(
          child: Padding(
            padding: EdgeInsets.fromLTRB(
              92 * scale,
              18 * scale,
              150 * scale,
              12 * scale,
            ),
            child: Align(
              alignment: Alignment.centerLeft,
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                child: Text(
                  note.isEmpty ? '愿每一天都有温柔回应。' : note,
                  key: ValueKey(note),
                  textAlign: TextAlign.left,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 18 * scale,
                    height: 1.65,
                    letterSpacing: 1.5 * scale,
                    color: const Color(0xFF55504F),
                  ),
                ),
              ),
            ),
          ),
        ),
        Positioned(
          right: -50 * scale,
          bottom: -15 * scale,
          child: Image.asset(
            'assets/images/heart_line.png',
            width: 264 * scale,
            height: 132 * scale,
            fit: BoxFit.contain,
          ),
        ),
      ],
    );
  }
}

class _HomeCard extends StatelessWidget {
  const _HomeCard({
    required this.height,
    required this.padding,
    required this.radius,
    this.child,
  });

  final double height;
  final double padding;
  final double radius;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      width: double.infinity,
      padding: EdgeInsets.all(padding),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: const Color(0xFFFFFEFE).withValues(alpha: .70),
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: const Color(0xFFF5E9E7)),
        boxShadow: [
          BoxShadow(
            color: const Color(0xFF9A6D68).withValues(alpha: .12),
            blurRadius: 16,
            spreadRadius: .5,
            offset: const Offset(0, 5),
          ),
        ],
      ),
      child: child,
    );
  }
}

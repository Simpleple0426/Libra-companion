import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/app_usage_event.dart';
import '../models/timeline_event.dart';
import '../config/api_config.dart';
import '../services/app_usage_service.dart';
import '../services/active_focus_store.dart';
import '../services/focus_status_service.dart';
import '../services/libra_api.dart';
import '../services/life_status_display.dart';
import '../services/weather_service.dart';
import '../services/weather_controller.dart';
import '../services/push_service.dart';
import '../services/calendar_service.dart';
import '../services/activity_event_store.dart';
import '../services/app_duration_store.dart';
import '../services/display_names.dart';
import 'chat_page.dart';
import 'home_page.dart';
import 'room_page.dart';
import 'study_room_page.dart';
import 'calendar_page.dart';
import 'timeline_page.dart';
import 'libra_activity_page.dart';
import 'music_room_page.dart';
import 'movie_room_page.dart';
import 'book_room_page.dart';
import 'personalization_settings_page.dart';

const _navigation = Color(0xFFFFD6D1);
const _accent = Color(0xFFDE776C);
const _inactive = Color(0xFF9DAAAD);

class HomeCache {
  const HomeCache({
    required this.libraName,
    required this.userName,
    required this.libraNickname,
    required this.userNickname,
    required this.metAt,
    required this.userStatus,
    this.libraAvatarPath,
    this.userAvatarPath,
  });

  final String libraName;
  final String userName;
  final String libraNickname;
  final String userNickname;
  final DateTime metAt;
  final String userStatus;
  final String? libraAvatarPath;
  final String? userAvatarPath;

  static Future<HomeCache> load() async {
    final preferences = await SharedPreferences.getInstance();
    return HomeCache(
      libraName: preferences.getString('profile_libra_name') ?? '左然',
      userName: preferences.getString('profile_user_name') ?? '我',
      libraNickname: preferences.getString('profile_libra_nickname') ?? '左然',
      userNickname: preferences.getString('profile_user_nickname') ?? '我',
      metAt:
          DateTime.tryParse(preferences.getString('profile_met_at') ?? '') ??
          DateTime(2026, 4, 26),
      userStatus: preferences.getString('home_user_status') ?? '设置状态',
      libraAvatarPath: preferences.getString('profile_libra_avatar'),
      userAvatarPath: preferences.getString('profile_user_avatar'),
    );
  }
}

class AppShell extends StatefulWidget {
  const AppShell({
    super.key,
    required this.initialWeather,
    required this.homeCache,
  });

  final Future<WeatherLoadResult> initialWeather;
  final HomeCache homeCache;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> with WidgetsBindingObserver {
  int _selectedIndex = 0;
  int _chatUnreadCount = 0;
  int _chatRefreshToken = 0;
  String _homeNote = '';
  String _libraHomeStatus = '平静';
  String _userHomeStatus = '设置状态';
  late final _focusStatus = FocusStatusService(_writeUserHomeStatus);
  bool _appIsActive = true;
  Timer? _weatherRefreshTimer;
  late final WeatherController _weatherController;
  final _usageService = AppUsageService();
  final _activityEventStore = ActivityEventStore();
  final _api = LibraApi();
  late final AppDurationStore _appDurationStore;
  List<AppUsageEvent> _usageEvents = const [];
  List<TimelineEvent>? _homeLifeEvents;
  LifeCoarseActivity? _homeCoarseActivity;
  String? _companionSessionId;
  List<LifeScheduleEntry> _homeCoarsePlans = const [];
  bool _homeLifeEventsLoading = true;
  bool _lifeStatusRefreshInProgress = false;
  Timer? _usageRefreshTimer;
  Timer? _lifeStatusRefreshTimer;
  Timer? _appDurationCheckpointTimer;
  Timer? _presenceHeartbeatTimer;
  bool _usageRefreshInProgress = false;
  bool _companionStatsRefreshInProgress = false;
  int _todayMessageCount = 0;
  Duration _todayAppDuration = Duration.zero;
  DateTime? _lastChatAt;
  bool _proactiveEnabled = false;
  bool _calendarYearSyncInProgress = false;
  int _calendarPermissionRefreshToken = 0;
  String _libraDisplayName = '左然';
  String _userDisplayName = '我';
  String _libraNickname = '左然';
  String _userNickname = '我';
  DateTime _metAt = DateTime(2026, 4, 26);
  String? _libraAvatarPath;
  String? _userAvatarPath;
  bool _studyRoomOpen = false;

  @override
  void initState() {
    super.initState();
    final cache = widget.homeCache;
    _libraDisplayName = cache.libraName;
    _userDisplayName = cache.userName;
    _libraNickname = cache.libraNickname;
    _userNickname = cache.userNickname;
    _metAt = cache.metAt;
    _userHomeStatus = cache.userStatus;
    _libraAvatarPath = cache.libraAvatarPath;
    _userAvatarPath = cache.userAvatarPath;
    DisplayNames.libra = cache.libraNickname;
    DisplayNames.user = cache.userNickname;
    DisplayNames.libraAvatarPath = cache.libraAvatarPath;
    DisplayNames.userAvatarPath = cache.userAvatarPath;
    _appDurationStore = AppDurationStore(_api);
    _weatherController = WeatherController()..addListener(_weatherChanged);
    _selectedIndex = PushService.instance.requestedTab.value ?? 0;
    PushService.instance.requestedTab.addListener(_handlePushNavigation);
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      unawaited(_restoreStudyRoom());
    });
    _appDurationStore.startSession();
    unawaited(_syncAppPresence(true));
    _presenceHeartbeatTimer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (_appIsActive) unawaited(_syncAppPresence(true));
    });
    _loadCompanionStats();
    _appDurationCheckpointTimer = Timer.periodic(const Duration(minutes: 1), (
      _,
    ) {
      if (_appIsActive) unawaited(_checkpointAndRefreshCompanion());
    });
    _loadHomeNote();
    _loadHomeStatuses();
    _loadPersonalization();
    unawaited(_initializeWeather());
    _loadProactiveSetting();
    _loadUsageEvents();
    _loadLifeStatus();
    unawaited(_syncCalendarYearIfNeeded());
    _scheduleLifeStatusRefresh();
    _usageRefreshTimer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (_selectedIndex == 0) _loadUsageEvents();
    });
    _weatherRefreshTimer = Timer.periodic(_weatherController.refreshInterval, (
      _,
    ) {
      if (_appIsActive) _weatherController.refreshIfStale();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    PushService.instance.requestedTab.removeListener(_handlePushNavigation);
    _usageRefreshTimer?.cancel();
    _lifeStatusRefreshTimer?.cancel();
    _appDurationCheckpointTimer?.cancel();
    _presenceHeartbeatTimer?.cancel();
    unawaited(_syncAppPresence(false));
    unawaited(_appDurationStore.endSession());
    _weatherRefreshTimer?.cancel();
    _weatherController
      ..removeListener(_weatherChanged)
      ..dispose();
    _api.close();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
  }

  void _handlePushNavigation() {
    final tab = PushService.instance.requestedTab.value;
    if (!mounted || tab == null) return;
    setState(() {
      _selectedIndex = tab;
      if (tab == 1) {
        _chatUnreadCount = 0;
        _chatRefreshToken++;
      }
    });
    PushService.instance.requestedTab.value = null;
    _refreshTab(tab);
  }

  void _refreshTab(int index) {
    if (index == 0) {
      _loadUsageEvents();
      _loadCompanionStats();
      _loadHomeStatuses();
    }
    if (index == 0 || index == 1) {
      _loadLifeStatus();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appIsActive = state == AppLifecycleState.resumed;
    if (_appIsActive) {
      _appDurationStore.startSession();
      unawaited(_syncAppPresence(true));
      _loadCompanionStats();
      _loadUsageEvents();
      _loadLifeStatus();
      unawaited(_syncCalendarYearIfNeeded());
      _weatherController.refreshIfStale();
      if (mounted) setState(() => _calendarPermissionRefreshToken++);
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached ||
        state == AppLifecycleState.hidden) {
      unawaited(_appDurationStore.endSession());
      unawaited(_syncAppPresence(false));
    }
  }

  Future<void> _syncAppPresence(bool active) async {
    try {
      await _api.setAppPresence(active);
    } catch (_) {
      // A heartbeat expires on the backend, so a failed update cannot leave
      // notifications disabled indefinitely.
    }
  }

  Future<void> _loadUsageEvents() async {
    if (_usageRefreshInProgress) return;
    _usageRefreshInProgress = true;
    try {
      final systemEvents = await _usageService.getTodayEvents();
      final localEvents = await _activityEventStore.loadToday();
      List<AppUsageEvent> remoteEvents = const [];
      try {
        remoteEvents = await _api.getTodayUserTimelineEvents();
      } catch (_) {
        // Local activity remains usable while the backend is unavailable.
      }
      final uniqueEvents = <String, AppUsageEvent>{};
      for (final event in [...remoteEvents, ...systemEvents, ...localEvents]) {
        if (event.description.contains("手机开始充电") ||
            event.description.contains("手机结束充电"))
          continue;
        uniqueEvents['${event.timestamp.toIso8601String()}|${event.description}'] =
            event;
      }
      final events = uniqueEvents.values.toList()
        ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
      try {
        await _api.syncUserTimelineEvents(events);
      } catch (_) {
        // Keep the homepage timeline available locally. The same rows are
        // retried on the next refresh and deduplicated by the backend.
      }
      if (!mounted) return;
      setState(() {
        _usageEvents = events;
      });
    } finally {
      _usageRefreshInProgress = false;
    }
  }

  void _scheduleLifeStatusRefresh() {
    final now = DateTime.now();
    final next = DateTime(
      now.year,
      now.month,
      now.day,
      now.hour,
      now.minute + 1,
    );
    _lifeStatusRefreshTimer = Timer(next.difference(now), () {
      _loadLifeStatus();
      _lifeStatusRefreshTimer = Timer.periodic(
        const Duration(minutes: 1),
        (_) => _loadLifeStatus(),
      );
    });
  }

  Future<void> _loadLifeStatus() async {
    if (_lifeStatusRefreshInProgress) return;
    _lifeStatusRefreshInProgress = true;
    try {
      try {
        final events = await _api.getLibraTimelineEvents();
        if (mounted) setState(() => _homeLifeEvents = events);
      } catch (_) {
        // Retain the last verified events when a refresh fails.
      }
      final life = await _api.getLifeSystemStatus();
      if (!mounted) return;
      setState(() {
        _homeLifeEventsLoading = false;
        _homeCoarseActivity = life.coarseActivity;
        _companionSessionId = life.companionSessionId;
        _homeCoarsePlans = life.schedule
            .where((entry) => !entry.detailed)
            .toList();
      });
      if (!life.ready) return;
      final value = coarseLifeStatusLabel(life);
      setState(() => _libraHomeStatus = value);
    } catch (_) {
      // Keep the last verified life-system status until the next refresh.
    } finally {
      _lifeStatusRefreshInProgress = false;
      if (mounted) setState(() => _homeLifeEventsLoading = false);
    }
  }

  Future<void> _checkpointAndRefreshCompanion() async {
    await _appDurationStore.checkpoint();
    await _loadCompanionStats();
  }

  Future<void> _loadCompanionStats() async {
    if (_companionStatsRefreshInProgress) return;
    _companionStatsRefreshInProgress = true;
    try {
      final stats = await _api.getCompanionStats();
      final duration = await _appDurationStore.todayDuration();
      if (!mounted) return;
      setState(() {
        _todayMessageCount = stats.todayMessageCount;
        _todayAppDuration = duration;
        _lastChatAt = stats.lastChatAt;
      });
    } catch (_) {
      // Keep the last successful values while the backend is unavailable.
    } finally {
      _companionStatsRefreshInProgress = false;
    }
  }

  Future<void> _loadHomeStatuses() async {
    final preferences = await SharedPreferences.getInstance();
    final original = preferences.getString('home_user_status');
    try {
      final remote = await _api.getPersonalizationSettings();
      final status = '${remote['user_home_status'] ?? ''}'.trim();
      if (status.isNotEmpty &&
          preferences.getBool('focus_status_active') != true &&
          preferences.getString('home_user_status') == original) {
        await preferences.setString('home_user_status', status);
      }
    } catch (_) {
      // The local value is only an offline display cache.
    }
    if (!mounted) return;
    setState(() {
      _userHomeStatus = preferences.getString('home_user_status') ?? '设置状态';
    });
  }

  Future<void> _loadPersonalization() async {
    final preferences = await SharedPreferences.getInstance();
    try {
      final remote = await _api.getPersonalizationSettings();
      await preferences.setString(
        'profile_libra_name',
        '${remote['libra_name'] ?? '左然'}',
      );
      await preferences.setString(
        'profile_user_name',
        '${remote['user_name'] ?? '我'}',
      );
      await preferences.setString(
        'profile_libra_nickname',
        '${remote['libra_nickname'] ?? '左然'}',
      );
      await preferences.setString(
        'profile_user_nickname',
        '${remote['user_nickname'] ?? '我'}',
      );
      await preferences.setString(
        'profile_user_address',
        '${remote['user_address'] ?? ''}',
      );
      await preferences.setString(
        'profile_met_at',
        '${remote['met_at'] ?? '2026-04-26'}',
      );
      await preferences.setInt(
        'profile_checkin_min_minutes',
        (remote['checkin_min_minutes'] as num?)?.toInt() ?? 10,
      );
      await preferences.setInt(
        'profile_checkin_max_minutes',
        (remote['checkin_max_minutes'] as num?)?.toInt() ?? 20,
      );
      await preferences.setBool(
        'profile_weather_reminder_enabled',
        remote['weather_reminder_enabled'] != false,
      );
      await preferences.setBool(
        'profile_state_update_enabled',
        remote['state_update_enabled'] != false,
      );
    } catch (_) {
      // Keep the last local copy when the backend is temporarily unavailable.
    }
    await _restoreAvatar('libra_avatar', 'libra_avatar.jpg', preferences);
    await _restoreAvatar('user_avatar', 'user_avatar.jpg', preferences);
    if ((preferences.getInt('profile_defaults_version') ?? 0) < 1) {
      if (!preferences.containsKey('profile_libra_name')) {
        await preferences.setString('profile_libra_name', '左然');
      }
      if (!preferences.containsKey('profile_user_name')) {
        await preferences.setString('profile_user_name', '我');
      }
      if (!preferences.containsKey('profile_libra_nickname')) {
        await preferences.setString('profile_libra_nickname', '左然');
      }
      if (!preferences.containsKey('profile_user_nickname')) {
        await preferences.setString('profile_user_nickname', '我');
      }
      if (!preferences.containsKey('profile_met_at')) {
        await preferences.setString(
          'profile_met_at',
          DateTime(2026, 4, 26).toIso8601String(),
        );
      }
      await preferences.setInt('profile_defaults_version', 1);
    }
    if (!mounted) return;
    setState(() {
      _libraDisplayName = preferences.getString('profile_libra_name') ?? '左然';
      _userDisplayName = preferences.getString('profile_user_name') ?? '我';
      _libraNickname = preferences.getString('profile_libra_nickname') ?? '左然';
      _userNickname = preferences.getString('profile_user_nickname') ?? '我';
      DisplayNames.libra = _libraNickname;
      DisplayNames.user = _userNickname;
      _metAt =
          DateTime.tryParse(preferences.getString('profile_met_at') ?? '') ??
          DateTime(2026, 4, 26);
      _libraAvatarPath = preferences.getString('profile_libra_avatar');
      _userAvatarPath = preferences.getString('profile_user_avatar');
      DisplayNames.libraAvatarPath = _libraAvatarPath;
      DisplayNames.userAvatarPath = _userAvatarPath;
    });
  }

  Future<void> _restoreAvatar(
    String stateKey,
    String filename,
    SharedPreferences preferences,
  ) async {
    try {
      final encoded = await _api.getMobileState(stateKey);
      if (encoded is! String || encoded.isEmpty) return;
      final directory = await getApplicationDocumentsDirectory();
      final file = File('${directory.path}/$filename');
      await file.writeAsBytes(base64Decode(encoded), flush: true);
      final preferenceKey =
          'profile_${stateKey.replaceFirst('_avatar', '')}_avatar';
      await preferences.setString(preferenceKey, file.path);
    } catch (_) {
      // Avatar files are reconstructed from the database when connected.
    }
  }

  Future<void> _openPersonalizationSettings() async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => PersonalizationSettingsPage(
          proactiveEnabled: _proactiveEnabled,
          libraNickname: _libraNickname,
          onProactiveChanged: (enabled) async {
            await _setProactiveEnabled(enabled);
          },
          onCalendarPermission: _requestCalendarPermission,
          onSaved: _loadPersonalization,
        ),
      ),
    );
    if (changed == true) await _loadPersonalization();
  }

  Future<void> _setUserHomeStatus(String status) async {
    await _focusStatus.selectManually(status);
  }

  Future<void> _writeUserHomeStatus(String status) async {
    final value = status.trim().isEmpty ? '设置状态' : status.trim();
    if (mounted) {
      setState(() => _userHomeStatus = value);
    }
    final preferences = await SharedPreferences.getInstance();
    await preferences.setString('home_user_status', value);
    try {
      await _api.updateUserStatus(value);
    } catch (_) {
      // The selected status remains available locally and can be changed
      // again even when the backend is temporarily unavailable.
    }
  }

  Future<void> _recordFocusEvent(String description) async {
    await _usageService.recordFocusEvent(description);
    await _loadUsageEvents();
  }

  Future<void> _recordCalendarActivity(
    String action,
    String appName,
    String description,
  ) async {
    final event = AppUsageEvent(
      timestamp: DateTime.now(),
      action: action,
      appName: appName,
      customDescription: description,
    );
    await _activityEventStore.add(event);
    if (!mounted) return;
    setState(() {
      _usageEvents = [..._usageEvents, event]
        ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
    });
    // Room navigation only needs the local record. A slow or unavailable
    // backend must not keep the user waiting on the room selection screen.
    unawaited(_syncCalendarActivity(List<AppUsageEvent>.of(_usageEvents)));
  }

  Future<void> _syncCalendarActivity(List<AppUsageEvent> events) async {
    try {
      await _api.syncUserTimelineEvents(events);
    } catch (_) {
      // The local event remains visible and the regular sync will retry it.
    }
  }

  Future<void> _recordManualTimelineActivity(
    DateTime occurredAt,
    String description,
  ) async {
    final event = AppUsageEvent(
      timestamp: occurredAt,
      action: 'manual_timeline',
      appName: '手动动态',
      customDescription: description,
    );
    await _activityEventStore.add(event);
    if (!mounted) return;
    setState(() {
      _usageEvents = [..._usageEvents, event]
        ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
    });
    await _api.syncUserTimelineEvents([event]);
  }

  Future<void> _recordRoomActivity(String roomName, String activity) async {
    final displayName = _userNickname.trim().isEmpty
        ? '我'
        : _userNickname.trim();
    await _recordCalendarActivity(
      'room_entered',
      roomName,
      '$displayName正在$activity',
    );
  }

  Future<void> _recordRoomLeave(String roomName) async {
    final displayName = _userNickname.trim().isEmpty
        ? '我'
        : _userNickname.trim();
    await _recordCalendarActivity(
      'room_left',
      roomName,
      '$displayName离开了$roomName',
    );
  }

  Future<void> _restoreStudyRoom() async {
    final saved = await ActiveFocusStore().load();
    if (saved == null && mounted) await _focusStatus.end();
    if (!mounted || saved == null || _studyRoomOpen) return;
    await _openRoom('自习室');
  }

  Future<void> _openRoom(String roomName) async {
    if (roomName == '自习室' && _studyRoomOpen) return;
    if (roomName == '书房') {
      await _recordRoomActivity('书房', '书房阅读');
      if (!mounted) return;
      await Navigator.of(
        context,
      ).push(MaterialPageRoute<void>(builder: (_) => const BookRoomPage()));
      if (!mounted) return;
      await _recordRoomLeave('书房');
      return;
    }
    if (roomName != '自习室' && roomName != '音乐室' && roomName != '电影室') return;
    if (roomName == '音乐室') {
      await _recordRoomActivity('音乐室', '音乐室听歌');
    } else if (roomName == '电影室') {
      await _recordRoomActivity('电影室', '电影室看电影');
    }
    if (!mounted) return;
    if (roomName == '自习室') _studyRoomOpen = true;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => switch (roomName) {
          '音乐室' => const MusicRoomPage(),
          '电影室' => const MovieRoomPage(),
          _ => StudyRoomPage(
            onFocusEvent: _recordFocusEvent,
            onFocusStarted: _focusStatus.start,
            onFocusEnded: _focusStatus.end,
          ),
        },
      ),
    );
    if (roomName == '自习室') _studyRoomOpen = false;
    if (!mounted) return;
    if (roomName == '音乐室' || roomName == '电影室') {
      await _recordRoomLeave(roomName);
    }
  }

  Future<void> _loadProactiveSetting() async {
    var enabled = await _usageService.getProactiveEnabled();
    try {
      enabled = await _api.getProactiveEnabled();
    } catch (_) {
      // The phone value is an offline cache only; never push it on startup.
    }
    if (!mounted) return;
    setState(() => _proactiveEnabled = enabled);
    await _usageService.setProactiveEnabled(enabled, ApiConfig.baseUrl);
  }

  Future<void> _setProactiveEnabled(bool enabled) async {
    setState(() => _proactiveEnabled = enabled);
    await _usageService.setProactiveEnabled(enabled, ApiConfig.baseUrl);
    try {
      await _api.setProactiveEnabled(enabled);
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('设置已保存在手机，连接后端后会自动同步')));
      }
    }
  }

  Future<void> _requestCalendarPermission() async {
    final result = await CalendarService().loadMonth(
      DateTime.now(),
      requestPermission: true,
    );
    if (!mounted) return;
    setState(() => _calendarPermissionRefreshToken++);
    if (result.hasPermission) {
      unawaited(_syncCalendarYearIfNeeded(force: true));
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          result.hasPermission ? '已允许读取手机日历' : '未获得日历权限，可稍后在系统设置中开启',
        ),
      ),
    );
  }

  Future<void> _syncCalendarYearIfNeeded({bool force = false}) async {
    if (_calendarYearSyncInProgress) return;
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final dayKey =
        '${today.year.toString().padLeft(4, '0')}-'
        '${today.month.toString().padLeft(2, '0')}-'
        '${today.day.toString().padLeft(2, '0')}';
    final preferences = await SharedPreferences.getInstance();
    if (!force && preferences.getString('calendar_year_synced_on') == dayKey) {
      return;
    }
    _calendarYearSyncInProgress = true;
    final start = today.subtract(const Duration(days: 30));
    final end = today.add(const Duration(days: 366));
    try {
      final result = await CalendarService().loadRange(start, end);
      await _api.uploadCalendarEvents(
        result.events,
        syncStart: start,
        syncEnd: end,
        reconcileSystem: result.hasPermission,
      );
      await preferences.setString('calendar_year_synced_on', dayKey);
    } catch (_) {
      // Keep the previous sync date so the next app resume retries automatically.
    } finally {
      _calendarYearSyncInProgress = false;
    }
  }

  void _showPrivacySettings() {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: homeBackground,
      showDragHandle: true,
      isScrollControlled: true,
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * 0.9,
      ),
      builder: (sheetContext) => StatefulBuilder(
        builder: (context, setSheetState) => SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(24, 4, 24, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '隐私与设备状态',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 10),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(
                  Icons.calendar_month_outlined,
                  color: homeAccent,
                ),
                title: const Text('系统日历权限'),
                subtitle: const Text('读取手机日程，让 Libra 理解节日和安排'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  Navigator.of(sheetContext).pop();
                  await _requestCalendarPermission();
                },
              ),
              const Divider(height: 24),
              SwitchListTile.adaptive(
                contentPadding: EdgeInsets.zero,
                activeThumbColor: homeAccent,
                title: const Text('允许左然主动发消息'),
                subtitle: const Text('左然会在随机时间醒来，并根据聊天和生活状态决定联系你或保持安静。'),
                value: _proactiveEnabled,
                onChanged: (enabled) async {
                  await _setProactiveEnabled(enabled);
                  if (sheetContext.mounted) setSheetState(() {});
                },
              ),
              const Text(
                '关闭后左然不会主动发起新的对话。',
                style: TextStyle(fontSize: 13, color: Colors.black54),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _weatherChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _initializeWeather() async {
    await _weatherController.initialize(widget.initialWeather);
    if (!mounted) return;
    // The server-side observation renders immediately; refresh GPS quietly.
    await _weatherController.refresh(showLoading: false);
  }

  Future<void> _loadHomeNote() async {
    try {
      final source = await rootBundle.loadString('assets/text/libra_notes.md');
      final notes = _parseNotes(source);
      if (!mounted || notes.isEmpty) return;
      setState(() => _homeNote = notes[Random().nextInt(notes.length)]);
    } catch (_) {
      // The home page can still render if the notes asset is unavailable.
    }
  }

  List<String> _parseNotes(String source) {
    final notes = <String>[];
    final paragraph = <String>[];
    void addParagraph() {
      if (paragraph.isEmpty) return;
      notes.add(paragraph.join('\n').trim());
      paragraph.clear();
    }

    for (final rawLine in source.split(RegExp(r'\r?\n'))) {
      final line = rawLine.trim();
      if (line.isEmpty) {
        addParagraph();
        continue;
      }
      final bullet = RegExp(r'^[-*+]\s+(.+)$').firstMatch(line);
      if (bullet != null) {
        addParagraph();
        notes.add(bullet.group(1)!.trim());
      } else {
        paragraph.add(line);
      }
    }
    addParagraph();
    return notes.where((note) => note.isNotEmpty).toList();
  }

  @override
  Widget build(BuildContext context) {
    final keyboardVisible = MediaQuery.viewInsetsOf(context).bottom > 0;
    return Scaffold(
      resizeToAvoidBottomInset: _selectedIndex != 3,
      backgroundColor: Colors.transparent,
      extendBody: true,
      body: DecoratedBox(
        decoration: BoxDecoration(
          color: homeHeader,
          image: const DecorationImage(
            image: AssetImage('assets/images/home_background.png'),
            fit: BoxFit.cover,
            alignment: Alignment.topCenter,
          ),
        ),
        child: SafeArea(
          bottom: false,
          child: Column(
            children: [
              Expanded(
                child: IndexedStack(
                  index: _selectedIndex,
                  children: [
                    HomePage(
                      note: _homeNote,
                      companionSessionId: _companionSessionId,
                      onCompanionEnded: () => unawaited(_loadLifeStatus()),
                      weather: _weatherController.weather,
                      weatherLoading: _weatherController.loading,
                      weatherError: _weatherController.error,
                      onWeatherRetry: () =>
                          unawaited(_weatherController.refresh()),
                      usageEvents: _usageEvents,
                      lifeEvents: _homeLifeEvents,
                      coarseActivity: _homeCoarseActivity,
                      coarsePlans: _homeCoarsePlans,
                      lifeEventsLoading: _homeLifeEventsLoading,
                      libraStatus: _libraHomeStatus,
                      libraAvatarPath: _libraAvatarPath,
                      userAvatarPath: _userAvatarPath,
                      userStatus: _userHomeStatus,
                      onUserStatusChanged: _setUserHomeStatus,
                      onManualTimelineAdded: _recordManualTimelineActivity,
                      onSettingsTap: _openPersonalizationSettings,
                      onLibraTimelineTap: () => Navigator.of(context).push(
                        MaterialPageRoute<void>(
                          builder: (_) => const LibraActivityPage(),
                        ),
                      ),
                      todayMessageCount: _todayMessageCount,
                      todayAppDuration: _todayAppDuration,
                      lastChatAt: _lastChatAt,
                      libraName: _libraDisplayName,
                      userName: _userDisplayName,
                      libraNickname: _libraNickname,
                      userNickname: _userNickname,
                      metAt: _metAt,
                    ),
                    ChatPage(
                      deviceContextEnabled: false,
                      refreshToken: _chatRefreshToken,
                      libraStatus: _libraHomeStatus,
                      libraAvatarPath: _libraAvatarPath,
                      userAvatarPath: _userAvatarPath,
                      onAssistantMessagesReceived: (count) {
                        if (_selectedIndex == 1 || count <= 0) return;
                        setState(() {
                          _chatUnreadCount = min(99, _chatUnreadCount + count);
                        });
                      },
                    ),
                    RoomPage(onRoomSelected: _openRoom),
                    CalendarPage(
                      deviceContextEnabled: false,
                      permissionRefreshToken: _calendarPermissionRefreshToken,
                      onActivityRecorded: _recordCalendarActivity,
                    ),
                    TimelinePage(active: _selectedIndex == 3),
                  ],
                ),
              ),
              if (!keyboardVisible)
                _BottomNavigation(
                  selectedIndex: _selectedIndex,
                  chatUnreadCount: _chatUnreadCount,
                  onSelected: (index) {
                    setState(() {
                      _selectedIndex = index;
                      if (index == 1) {
                        _chatUnreadCount = 0;
                        _chatRefreshToken++;
                      }
                      if (index == 3) {
                        _calendarPermissionRefreshToken++;
                      }
                    });
                    _refreshTab(index);
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _BottomNavigation extends StatelessWidget {
  const _BottomNavigation({
    required this.selectedIndex,
    required this.chatUnreadCount,
    required this.onSelected,
  });

  final int selectedIndex;
  final int chatUnreadCount;
  final ValueChanged<int> onSelected;
  static const icons = [
    Icons.home_outlined,
    Icons.forum_outlined,
    Icons.favorite_border_rounded,
    Icons.calendar_month_outlined,
    Icons.camera_outlined,
  ];

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    return Container(
      height: 52 + bottomInset,
      padding: EdgeInsets.only(bottom: bottomInset),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [
            _navigation.withValues(alpha: .88),
            _navigation.withValues(alpha: .40),
            _navigation.withValues(alpha: .08),
          ],
          stops: const [0, .58, 1],
        ),
      ),
      child: Row(
        children: List.generate(icons.length, (index) {
          return Expanded(
            child: IconButton(
              onPressed: () => onSelected(index),
              iconSize: 27,
              color: selectedIndex == index ? _accent : _inactive,
              icon: Stack(
                clipBehavior: Clip.none,
                children: [
                  Icon(icons[index]),
                  if (index == 1 && chatUnreadCount > 0)
                    Positioned(
                      right: -10,
                      top: -8,
                      child: Container(
                        constraints: const BoxConstraints(minWidth: 18),
                        height: 18,
                        padding: const EdgeInsets.symmetric(horizontal: 5),
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: _accent,
                          borderRadius: BorderRadius.circular(9),
                          border: Border.all(color: Colors.white, width: 1.5),
                        ),
                        child: Text(
                          chatUnreadCount >= 99 ? '99+' : '$chatUnreadCount',
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            height: 1,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          );
        }),
      ),
    );
  }
}

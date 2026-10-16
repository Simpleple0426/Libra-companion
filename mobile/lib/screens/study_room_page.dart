import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../controllers/study_room_controller.dart';
import '../services/app_usage_service.dart';
import '../services/focus_stats_store.dart';

const _accent = Color(0xFFE27676);
const _ink = Color(0xFF554B49);

class StudyRoomPage extends StatefulWidget {
  const StudyRoomPage({
    super.key,
    required this.onFocusEvent,
    this.onFocusStarted,
    this.onFocusEnded,
  });

  final Future<void> Function(String description) onFocusEvent;
  final Future<void> Function()? onFocusStarted;
  final Future<void> Function()? onFocusEnded;

  @override
  State<StudyRoomPage> createState() => _StudyRoomPageState();
}

class _StudyRoomPageState extends State<StudyRoomPage>
    with WidgetsBindingObserver {
  static const _focusVideoAsset = 'assets/study_room/focus_video.mp4';
  static const _focusAudioAssets = [
    'study_room/focus_audio_01.mp3',
    'study_room/focus_audio_02.mp3',
    'study_room/focus_audio_03.mp3',
  ];

  final _contentController = TextEditingController();
  late final StudyRoomController _studyController;
  final _focusAudio = AudioPlayer();
  late final VideoPlayerController _focusVideo;
  StreamSubscription<void>? _audioCompleteSubscription;
  bool _videoReady = false;
  bool _appIsActive = true;
  bool _muted = false;
  int _audioIndex = 0;
  Duration _lastVideoPosition = Duration.zero;
  int _stalledVideoTicks = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // A platform view is used deliberately here. Some Android devices keep a
    // Flutter texture on the first decoded frame even though ExoPlayer is
    // advancing normally, which makes the focus video look like a still image.
    _focusVideo = VideoPlayerController.asset(
      _focusVideoAsset,
      videoPlayerOptions: VideoPlayerOptions(mixWithOthers: true),
      viewType: VideoViewType.platformView,
    );
    _studyController = StudyRoomController(
      focusEventSink: widget.onFocusEvent,
      onSessionStarted: () async {
        final status = widget.onFocusStarted?.call();
        await _startFocusMedia();
        await status;
      },
      onSessionTick: _ensureFocusVideoIsAdvancing,
      onSessionEnded: () async {
        // Start the next session with the default prompt, not the previous topic.
        _contentController.clear();
        final status = widget.onFocusEnded?.call();
        await _stopFocusMedia();
        await status;
      },
    )..addListener(_onStudyStateChanged);
    unawaited(
      _focusAudio.setAudioContext(
        AudioContext(
          android: const AudioContextAndroid(
            stayAwake: true,
            contentType: AndroidContentType.music,
            usageType: AndroidUsageType.media,
            audioFocus: AndroidAudioFocus.gain,
          ),
        ),
      ),
    );
    _audioCompleteSubscription = _focusAudio.onPlayerComplete.listen((_) {
      if (!_studyController.isFocusing) return;
      _audioIndex = (_audioIndex + 1) % _focusAudioAssets.length;
      unawaited(_playCurrentFocusAudio());
    });
    unawaited(_initializeFocusVideo());
    unawaited(_studyController.refreshStats());
    unawaited(_studyController.restore());
  }

  void _onStudyStateChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _studyController
      ..removeListener(_onStudyStateChanged)
      ..dispose();
    _contentController.dispose();
    _audioCompleteSubscription?.cancel();
    _focusAudio.dispose();
    unawaited(_setBackgroundPlayback(false));
    _focusVideo.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _appIsActive = state == AppLifecycleState.resumed;
    if (!_studyController.isFocusing) return;
    if (state == AppLifecycleState.resumed) {
      _studyController.onAppResumed();
      if (_videoReady) _playFocusVideoAfterLayout();
    } else {
      if (_videoReady) unawaited(_focusVideo.pause());
      unawaited(_studyController.checkpoint());
    }
  }

  Future<void> _initializeFocusVideo() async {
    try {
      await _focusVideo.initialize();
      await _focusVideo.setLooping(true);
      await _focusVideo.setVolume(0);
      if (!mounted) return;
      setState(() => _videoReady = true);
      if (_studyController.isFocusing) _playFocusVideoAfterLayout();
    } catch (error, stackTrace) {
      debugPrint('Study room video initialization failed: $error');
      debugPrintStack(stackTrace: stackTrace);
      // Keep the static study-room artwork if the video cannot be decoded.
    }
  }

  Future<void> _startFocusMedia() async {
    await _setBackgroundPlayback(true);
    if (!mounted || !_studyController.isFocusing) {
      await _setBackgroundPlayback(false);
      return;
    }
    _audioIndex = 0;
    if (_videoReady) {
      await _focusVideo.seekTo(Duration.zero);
      _playFocusVideoAfterLayout();
    }
    await _playCurrentFocusAudio();
  }

  void _playFocusVideoAfterLayout() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted ||
          !_appIsActive ||
          !_videoReady ||
          !_studyController.isFocusing) {
        return;
      }
      // Platform views are attached asynchronously on Android. Give the native
      // SurfaceView time to exist before starting playback, then verify it.
      Future<void>.delayed(const Duration(milliseconds: 600), () async {
        if (!mounted ||
            !_appIsActive ||
            !_videoReady ||
            !_studyController.isFocusing) {
          return;
        }
        await _focusVideo.play();
        await Future<void>.delayed(const Duration(milliseconds: 500));
        if (mounted &&
            _appIsActive &&
            _studyController.isFocusing &&
            !_focusVideo.value.isPlaying) {
          await _focusVideo.play();
        }
      });
    });
  }

  void _ensureFocusVideoIsAdvancing() {
    if (!_appIsActive || !_videoReady || !_studyController.isFocusing) return;
    final value = _focusVideo.value;
    final position = value.position;
    if (!value.isPlaying) {
      unawaited(_focusVideo.play());
    }
    if (position <= _lastVideoPosition + const Duration(milliseconds: 80)) {
      _stalledVideoTicks++;
    } else {
      _stalledVideoTicks = 0;
    }
    if (_stalledVideoTicks >= 2) {
      _stalledVideoTicks = 0;
      unawaited(
        _focusVideo.pause().then((_) {
          if (mounted && _appIsActive && _studyController.isFocusing) {
            return _focusVideo.play();
          }
        }),
      );
    }
    _lastVideoPosition = position;
    debugPrint(
      'Study room video: ready=$_videoReady playing=${value.isPlaying} '
      'position=${position.inMilliseconds} error=${value.errorDescription}',
    );
  }

  Future<void> _playCurrentFocusAudio() async {
    if (!_studyController.isFocusing || _focusAudioAssets.isEmpty) return;
    try {
      await _focusAudio.setVolume(_muted ? 0 : 1);
      await _focusAudio.play(AssetSource(_focusAudioAssets[_audioIndex]));
      debugPrint(
        'Study room audio started: ${_focusAudioAssets[_audioIndex]} '
        'muted=$_muted',
      );
    } catch (error, stackTrace) {
      debugPrint('Study room audio failed: $error');
      debugPrintStack(stackTrace: stackTrace);
      await _setBackgroundPlayback(false);
    }
  }

  Future<void> _stopFocusMedia() async {
    try {
      await _focusAudio.stop();
    } finally {
      await _setBackgroundPlayback(false);
    }
    if (_videoReady) {
      await _focusVideo.pause();
      await _focusVideo.seekTo(Duration.zero);
    }
  }

  Future<void> _toggleMuted() async {
    setState(() => _muted = !_muted);
    await _focusAudio.setVolume(_muted ? 0 : 1);
  }

  Future<void> _setBackgroundPlayback(bool enabled) async {
    try {
      await AppUsageService().setFocusBackgroundPlayback(enabled);
    } catch (error) {
      debugPrint('Study room background playback service failed: $error');
    }
  }

  Future<void> _chooseDuration() async {
    var selectedMinutes = 25;
    final controller = FixedExtentScrollController(initialItem: 24);
    final result = await showDialog<int>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.58),
      builder: (dialogContext) => Dialog(
        insetPadding: const EdgeInsets.symmetric(horizontal: 42),
        backgroundColor: Colors.transparent,
        elevation: 0,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              height: 300,
              decoration: BoxDecoration(
                color: const Color(0xFFFFFAF9).withValues(alpha: 0.96),
                border: Border.all(color: Colors.white, width: 2),
                borderRadius: BorderRadius.circular(26),
                boxShadow: [
                  BoxShadow(
                    color: _accent.withValues(alpha: 0.2),
                    blurRadius: 28,
                    offset: const Offset(0, 12),
                  ),
                ],
              ),
              clipBehavior: Clip.antiAlias,
              child: Column(
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 14, bottom: 10),
                    child: Text('设置时长计划', style: TextStyle(fontSize: 17)),
                  ),
                  const Divider(height: 1, indent: 20, endIndent: 20),
                  Expanded(
                    child: CupertinoPicker.builder(
                      scrollController: controller,
                      itemExtent: 48,
                      selectionOverlay: Container(
                        decoration: BoxDecoration(
                          color: _accent.withValues(alpha: 0.13),
                          border: Border.symmetric(
                            horizontal: BorderSide(
                              color: _accent.withValues(alpha: 0.25),
                            ),
                          ),
                        ),
                      ),
                      onSelectedItemChanged: (index) =>
                          selectedMinutes = index + 1,
                      childCount: 60,
                      itemBuilder: (_, index) => Center(
                        child: Text(
                          '${index + 1}分钟',
                          style: const TextStyle(
                            color: Color(0xFF33313C),
                            fontSize: 20,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                _DialogButton(
                  label: '取消',
                  color: Colors.white.withValues(alpha: 0.92),
                  textColor: _ink,
                  onPressed: () => Navigator.pop(dialogContext),
                ),
                const SizedBox(width: 12),
                _DialogButton(
                  label: '确定',
                  color: _accent,
                  textColor: Colors.white,
                  onPressed: () =>
                      Navigator.pop(dialogContext, selectedMinutes),
                ),
              ],
            ),
          ],
        ),
      ),
    );
    controller.dispose();
    if (result != null && mounted) _startFocus(result);
  }

  void _startFocus(int minutes) {
    FocusManager.instance.primaryFocus?.unfocus();
    _lastVideoPosition = Duration.zero;
    _stalledVideoTicks = 0;
    _studyController.startCountdown(minutes, _contentController.text);
  }

  void _startCountUp() {
    FocusManager.instance.primaryFocus?.unfocus();
    _lastVideoPosition = Duration.zero;
    _stalledVideoTicks = 0;
    _studyController.startCountUp(_contentController.text);
  }

  void _stopFocus() => unawaited(_studyController.finish());

  void _togglePaused() => _studyController.togglePaused();

  Future<void> _editFocusDetails() async {
    if (!_studyController.isFocusing) return;
    final contentController = TextEditingController(
      text: _studyController.content,
    );
    final confirmed = await showDialog<bool>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.58),
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFFFFFAF9),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        title: const Text('修改专注主题'),
        content: TextField(
          controller: contentController,
          maxLength: 60,
          autofocus: true,
          onTapOutside: (_) => FocusManager.instance.primaryFocus?.unfocus(),
          textInputAction: TextInputAction.done,
          onSubmitted: (_) => Navigator.pop(dialogContext, true),
          decoration: const InputDecoration(
            labelText: '学习主题',
            hintText: '例如：复习民法第三章',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            style: FilledButton.styleFrom(backgroundColor: _accent),
            child: const Text('确定'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted && _studyController.isFocusing) {
      final content = contentController.text.trim();
      _studyController.updateContent(content);
      _contentController.text = _studyController.content;
    }
    contentController.dispose();
  }

  Future<void> _showStats() async {
    await _studyController.refreshStats();
    if (!mounted) return;
    await showDialog<void>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.58),
      builder: (_) => _FocusStatsDialog(sessions: _studyController.sessions),
    );
  }

  @override
  Widget build(BuildContext context) {
    final focusing = _studyController.isFocusing;
    final metrics = _FocusMetrics.fromSessions(_studyController.sessions);
    return PopScope(
      canPop: !focusing,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && focusing) _stopFocus();
      },
      child: Scaffold(
        backgroundColor: const Color(0xFFFFF8F7),
        body: Stack(
          fit: StackFit.expand,
          children: [
            if (focusing && _videoReady)
              _FocusVideoBackground(controller: _focusVideo)
            else
              const DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      Color(0xFFFFF9F7),
                      Color(0xFFFFECEA),
                      Color(0xFFF8E3E1),
                    ],
                    stops: [0, .55, 1],
                  ),
                ),
              ),
            if (!focusing) const _StudyRoomBackdrop(),
            if (focusing)
              DecoratedBox(
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: _videoReady ? .12 : 0),
                ),
              ),
            SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(18, 10, 18, 20),
                child: Column(
                  children: [
                    Row(
                      children: [
                        SizedBox(
                          width: 82,
                          child: Align(
                            alignment: Alignment.centerLeft,
                            child: _GlassIconButton(
                              icon: Icons.chevron_left_rounded,
                              tooltip: focusing ? '结束专注' : '返回',
                              transparent: focusing,
                              onPressed: focusing
                                  ? _stopFocus
                                  : () => Navigator.pop(context),
                            ),
                          ),
                        ),
                        Expanded(
                          child: focusing
                              ? Center(
                                  child: _CompactFocusTimer(
                                    label: _studyController.timerLabel,
                                    onStop: _stopFocus,
                                  ),
                                )
                              : const Column(
                                  children: [
                                    Text(
                                      '自习室',
                                      style: TextStyle(
                                        color: _ink,
                                        fontSize: 21,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                    SizedBox(height: 2),
                                    Text(
                                      '一起安静专注',
                                      style: TextStyle(
                                        color: Color(0xFF8E817F),
                                        fontSize: 12,
                                      ),
                                    ),
                                  ],
                                ),
                        ),
                        const SizedBox(width: 82),
                      ],
                    ),
                    if (focusing) ...[
                      const Spacer(),
                      _ActiveFocusHeader(
                        content: _studyController.content,
                        onTap: _editFocusDetails,
                      ),
                      const SizedBox(height: 10),
                      _ActiveFocusControls(
                        muted: _muted,
                        paused: _studyController.paused,
                        onToggleMuted: _toggleMuted,
                        onTogglePaused: _togglePaused,
                        onStop: _stopFocus,
                      ),
                    ] else
                      Expanded(
                        child: _IdleStudyDashboard(
                          metrics: metrics,
                          loading: _studyController.statsLoading,
                          contentController: _contentController,
                          sessions: _studyController.sessions,
                          onStart: _startFocus,
                          onCountUp: _startCountUp,
                          onCustom: _chooseDuration,
                          onStats: _showStats,
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

class _StudyRoomBackdrop extends StatelessWidget {
  const _StudyRoomBackdrop();

  @override
  Widget build(BuildContext context) => Stack(
    children: [
      Positioned(
        top: 92,
        right: -65,
        child: Container(
          width: 210,
          height: 210,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: Colors.white.withValues(alpha: .48),
          ),
        ),
      ),
      Positioned(
        left: -80,
        bottom: 100,
        child: Container(
          width: 230,
          height: 230,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: _accent.withValues(alpha: .08),
          ),
        ),
      ),
    ],
  );
}

class _IdleStudyDashboard extends StatelessWidget {
  const _IdleStudyDashboard({
    required this.metrics,
    required this.loading,
    required this.contentController,
    required this.sessions,
    required this.onStart,
    required this.onCountUp,
    required this.onCustom,
    required this.onStats,
  });

  final _FocusMetrics metrics;
  final bool loading;
  final TextEditingController contentController;
  final List<FocusSession> sessions;
  final ValueChanged<int> onStart;
  final VoidCallback onCountUp;
  final VoidCallback onCustom;
  final VoidCallback onStats;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: const EdgeInsets.only(top: 28, bottom: 8),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.fromLTRB(22, 22, 22, 20),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: .82),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(color: Colors.white),
            boxShadow: [
              BoxShadow(
                color: _accent.withValues(alpha: .1),
                blurRadius: 28,
                offset: const Offset(0, 12),
              ),
            ],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 46,
                    height: 46,
                    decoration: BoxDecoration(
                      color: _accent.withValues(alpha: .12),
                      borderRadius: BorderRadius.circular(15),
                    ),
                    child: const Icon(
                      Icons.hourglass_top_rounded,
                      color: _accent,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: TextField(
                      controller: contentController,
                      maxLength: 40,
                      onTapOutside: (_) =>
                          FocusManager.instance.primaryFocus?.unfocus(),
                      textInputAction: TextInputAction.done,
                      decoration: const InputDecoration(
                        hintText: '这次准备学什么？',
                        hintStyle: TextStyle(
                          color: Color(0xFFB8A7A4),
                          fontSize: 17,
                          fontWeight: FontWeight.w400,
                        ),
                        helperText: '例如：英语听力、复习民法第三章',
                        helperStyle: TextStyle(
                          color: Color(0xFFC1B2AF),
                          fontSize: 11.5,
                        ),
                        counterText: '',
                        border: InputBorder.none,
                        isDense: true,
                      ),
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                        color: _ink,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 22),
              Row(
                children: [
                  for (final minutes in const [15, 25, 45]) ...[
                    Expanded(
                      child: _DurationChoice(
                        minutes: minutes,
                        recommended: minutes == 25,
                        onTap: () => onStart(minutes),
                      ),
                    ),
                    if (minutes != 45) const SizedBox(width: 9),
                  ],
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: SizedBox(
                      height: 48,
                      child: OutlinedButton.icon(
                        onPressed: onCustom,
                        icon: const Icon(Icons.tune_rounded, size: 17),
                        label: const Text(
                          '自定义倒计时',
                          maxLines: 1,
                          softWrap: false,
                        ),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: _ink,
                          textStyle: const TextStyle(fontSize: 12.5),
                          padding: const EdgeInsets.symmetric(horizontal: 7),
                          side: BorderSide(
                            color: _accent.withValues(alpha: .28),
                          ),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: SizedBox(
                      height: 48,
                      child: FilledButton.icon(
                        onPressed: onCountUp,
                        icon: const Icon(Icons.timer_outlined, size: 17),
                        label: const Text('正向计时', maxLines: 1, softWrap: false),
                        style: FilledButton.styleFrom(
                          backgroundColor: const Color(0xFFF4D5D3),
                          foregroundColor: _ink,
                          textStyle: const TextStyle(fontSize: 12.5),
                          padding: const EdgeInsets.symmetric(horizontal: 7),
                          elevation: 0,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(16),
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Material(
          color: Colors.white.withValues(alpha: .72),
          borderRadius: BorderRadius.circular(24),
          child: InkWell(
            onTap: onStats,
            borderRadius: BorderRadius.circular(24),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(18, 17, 14, 17),
              child: Row(
                children: [
                  Expanded(
                    child: _DashboardStat(
                      value: loading ? '—' : metrics.todayMinutes.toString(),
                      unit: '分钟',
                      label: '今日专注',
                    ),
                  ),
                  Container(
                    width: 1,
                    height: 45,
                    color: const Color(0xFFEEDDDC),
                  ),
                  Expanded(
                    child: _DashboardStat(
                      value: loading ? '—' : metrics.streak.toString(),
                      unit: '天',
                      label: '连续专注',
                    ),
                  ),
                  const Icon(Icons.chevron_right_rounded, color: _accent),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 20),
        _TodayFocusRecords(sessions: sessions),
      ],
    ),
  );
}

class _TodayFocusRecords extends StatelessWidget {
  const _TodayFocusRecords({required this.sessions});
  final List<FocusSession> sessions;

  bool _isToday(DateTime value) {
    final local = value.toLocal();
    final now = DateTime.now();
    return local.year == now.year &&
        local.month == now.month &&
        local.day == now.day;
  }

  String _duration(int seconds) {
    if (seconds < 60) return '$seconds秒';
    final minutes = seconds ~/ 60;
    final rest = seconds % 60;
    return rest == 0 ? '$minutes分钟' : '$minutes分$rest秒';
  }

  @override
  Widget build(BuildContext context) {
    final today = sessions.where((item) => _isToday(item.startedAt)).toList()
      ..sort((a, b) => b.startedAt.compareTo(a.startedAt));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Expanded(
              child: Text(
                '今天的专注记录',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: _ink,
                ),
              ),
            ),
            Text(
              '${today.length} 次',
              style: const TextStyle(fontSize: 12, color: Color(0xFF998A88)),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (today.isEmpty)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(vertical: 22),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: .56),
              borderRadius: BorderRadius.circular(18),
            ),
            child: const Text(
              '今天还没有专注记录',
              style: TextStyle(fontSize: 13, color: Color(0xFF9C8D8A)),
            ),
          )
        else
          for (final session in today)
            Container(
              margin: const EdgeInsets.only(bottom: 9),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: .72),
                borderRadius: BorderRadius.circular(17),
              ),
              child: Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: const BoxDecoration(
                      color: _accent,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Text(
                      session.content.trim().isEmpty ? '自由学习' : session.content,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: _ink,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Text(
                    _duration(session.seconds),
                    style: const TextStyle(
                      fontSize: 13,
                      color: _accent,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
      ],
    );
  }
}

class _DurationChoice extends StatelessWidget {
  const _DurationChoice({
    required this.minutes,
    required this.recommended,
    required this.onTap,
  });
  final int minutes;
  final bool recommended;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: recommended ? _accent : const Color(0xFFFFF5F4),
    borderRadius: BorderRadius.circular(17),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(17),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 14),
        child: Column(
          children: [
            Text(
              '$minutes',
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.w700,
                color: recommended ? Colors.white : _ink,
              ),
            ),
            Text(
              '分钟',
              style: TextStyle(
                fontSize: 12,
                color: recommended
                    ? Colors.white.withValues(alpha: .86)
                    : const Color(0xFF958582),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}

class _DashboardStat extends StatelessWidget {
  const _DashboardStat({
    required this.value,
    required this.unit,
    required this.label,
  });
  final String value;
  final String unit;
  final String label;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      RichText(
        text: TextSpan(
          style: const TextStyle(color: _ink),
          children: [
            TextSpan(
              text: value,
              style: const TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
            ),
            TextSpan(
              text: ' $unit',
              style: const TextStyle(fontSize: 12, color: Color(0xFF9A8886)),
            ),
          ],
        ),
      ),
      const SizedBox(height: 3),
      Text(
        label,
        style: const TextStyle(fontSize: 12, color: Color(0xFF8D807E)),
      ),
    ],
  );
}

class _ActiveFocusControls extends StatelessWidget {
  const _ActiveFocusControls({
    required this.muted,
    required this.paused,
    required this.onToggleMuted,
    required this.onTogglePaused,
    required this.onStop,
  });
  final bool muted;
  final bool paused;
  final VoidCallback onToggleMuted;
  final VoidCallback onTogglePaused;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .86),
      borderRadius: BorderRadius.circular(24),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        IconButton(
          onPressed: onToggleMuted,
          tooltip: muted ? '打开声音' : '静音',
          icon: Icon(
            muted ? Icons.volume_off_rounded : Icons.volume_up_rounded,
            color: _ink,
          ),
        ),
        IconButton(
          onPressed: onTogglePaused,
          tooltip: paused ? '继续' : '暂停',
          icon: Icon(
            paused ? Icons.play_arrow_rounded : Icons.pause_rounded,
            color: _ink,
          ),
        ),
        const SizedBox(width: 4),
        FilledButton.icon(
          onPressed: onStop,
          icon: const Icon(Icons.stop_rounded, size: 18),
          label: const Text('结束'),
          style: FilledButton.styleFrom(backgroundColor: _accent),
        ),
      ],
    ),
  );
}

class _ActiveFocusHeader extends StatelessWidget {
  const _ActiveFocusHeader({required this.content, required this.onTap});
  final String content;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white.withValues(alpha: .86),
    borderRadius: BorderRadius.circular(22),
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(22),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 14, 14, 14),
        child: Row(
          children: [
            Expanded(
              child: Text(
                content,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: _ink,
                ),
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.edit_rounded, size: 19, color: Color(0xFF8D807E)),
          ],
        ),
      ),
    ),
  );
}

class _FocusMetrics {
  const _FocusMetrics({
    required this.todayMinutes,
    required this.todayCount,
    required this.weekMinutes,
    required this.totalMinutes,
    required this.totalCount,
    required this.averageMinutes,
    required this.longestMinutes,
    required this.streak,
    required this.bestDayMinutes,
    required this.bestDay,
  });

  final int todayMinutes;
  final int todayCount;
  final int weekMinutes;
  final int totalMinutes;
  final int totalCount;
  final int averageMinutes;
  final int longestMinutes;
  final int streak;
  final int bestDayMinutes;
  final DateTime? bestDay;

  static DateTime _day(DateTime value) =>
      DateTime(value.year, value.month, value.day);

  factory _FocusMetrics.fromSessions(List<FocusSession> sessions) {
    final now = DateTime.now();
    final today = _day(now);
    final weekStart = today.subtract(Duration(days: today.weekday - 1));
    final totals = <DateTime, int>{};
    for (final session in sessions) {
      final day = _day(session.startedAt.toLocal());
      totals[day] = (totals[day] ?? 0) + session.seconds;
    }
    final todaySessions = sessions
        .where((item) => _day(item.startedAt.toLocal()) == today)
        .toList();
    final totalSeconds = sessions.fold<int>(
      0,
      (sum, item) => sum + item.seconds,
    );
    final weekSeconds = totals.entries
        .where(
          (item) => !item.key.isBefore(weekStart) && !item.key.isAfter(today),
        )
        .fold<int>(0, (sum, item) => sum + item.value);
    var cursor = totals.containsKey(today)
        ? today
        : today.subtract(const Duration(days: 1));
    var streak = 0;
    while ((totals[cursor] ?? 0) > 0) {
      streak++;
      cursor = cursor.subtract(const Duration(days: 1));
    }
    DateTime? bestDay;
    var bestSeconds = 0;
    for (final item in totals.entries) {
      if (item.value > bestSeconds) {
        bestSeconds = item.value;
        bestDay = item.key;
      }
    }
    return _FocusMetrics(
      todayMinutes:
          todaySessions.fold<int>(0, (sum, item) => sum + item.seconds) ~/ 60,
      todayCount: todaySessions.length,
      weekMinutes: weekSeconds ~/ 60,
      totalMinutes: totalSeconds ~/ 60,
      totalCount: sessions.length,
      averageMinutes: sessions.isEmpty
          ? 0
          : (totalSeconds / sessions.length / 60).round(),
      longestMinutes: sessions.isEmpty
          ? 0
          : sessions
                    .map((item) => item.seconds)
                    .reduce((a, b) => a > b ? a : b) ~/
                60,
      streak: streak,
      bestDayMinutes: bestSeconds ~/ 60,
      bestDay: bestDay,
    );
  }
}

class _FocusStatsDialog extends StatelessWidget {
  const _FocusStatsDialog({required this.sessions});

  final List<FocusSession> sessions;

  bool _sameDay(DateTime first, DateTime second) =>
      first.year == second.year &&
      first.month == second.month &&
      first.day == second.day;

  String _durationLabel(int seconds) {
    final minutes = seconds ~/ 60;
    if (minutes < 60) return '$minutes分钟';
    final hours = minutes ~/ 60;
    final rest = minutes % 60;
    return rest == 0 ? '$hours小时' : '$hours小时$rest分钟';
  }

  String _sessionDuration(int seconds) {
    final minutes = seconds ~/ 60;
    final rest = seconds % 60;
    if (minutes == 0) return '$rest秒';
    return rest == 0 ? '$minutes分钟' : '$minutes分$rest秒';
  }

  Future<void> _showDaySessions(BuildContext context, DateTime date) async {
    final daySessions =
        sessions
            .where((session) => _sameDay(session.startedAt.toLocal(), date))
            .toList()
          ..sort((a, b) => a.startedAt.compareTo(b.startedAt));
    final totalSeconds = daySessions.fold<int>(
      0,
      (total, session) => total + session.seconds,
    );
    await showDialog<void>(
      context: context,
      barrierColor: Colors.black.withValues(alpha: 0.58),
      builder: (dialogContext) => Dialog(
        insetPadding: const EdgeInsets.symmetric(horizontal: 28, vertical: 52),
        backgroundColor: Colors.transparent,
        elevation: 0,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 380, maxHeight: 540),
          child: Container(
            padding: const EdgeInsets.fromLTRB(18, 16, 18, 14),
            decoration: BoxDecoration(
              color: const Color(0xFFFFFBFA),
              borderRadius: BorderRadius.circular(28),
              border: Border.all(color: Colors.white, width: 1.5),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF5B3B38).withValues(alpha: .18),
                  blurRadius: 32,
                  offset: const Offset(0, 14),
                ),
              ],
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Container(
                      width: 42,
                      height: 42,
                      decoration: BoxDecoration(
                        color: _accent.withValues(alpha: .12),
                        borderRadius: BorderRadius.circular(14),
                      ),
                      child: const Icon(
                        Icons.calendar_today_rounded,
                        color: _accent,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${date.month}月${date.day}日',
                            style: const TextStyle(
                              color: _ink,
                              fontSize: 19,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          const Text(
                            '专注明细',
                            style: TextStyle(
                              color: Color(0xFF9A8C89),
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      onPressed: () => Navigator.pop(dialogContext),
                      icon: const Icon(Icons.close_rounded),
                      color: const Color(0xFF8D807E),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 11,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFEFED),
                    borderRadius: BorderRadius.circular(16),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: _DaySummaryValue(
                          value: '${daySessions.length}',
                          label: '专注次数',
                        ),
                      ),
                      Container(
                        width: 1,
                        height: 28,
                        color: const Color(0xFFEBCBC8),
                      ),
                      Expanded(
                        child: _DaySummaryValue(
                          value: _durationLabel(totalSeconds),
                          label: '累计时长',
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                if (daySessions.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 30),
                    child: Column(
                      children: [
                        Icon(
                          Icons.hourglass_empty_rounded,
                          color: Color(0xFFC9B9B6),
                          size: 34,
                        ),
                        SizedBox(height: 9),
                        Text(
                          '当天暂无专注记录',
                          style: TextStyle(color: Color(0xFF9A8C89)),
                        ),
                      ],
                    ),
                  )
                else
                  Flexible(
                    child: ListView.separated(
                      shrinkWrap: true,
                      itemCount: daySessions.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 8),
                      itemBuilder: (_, index) {
                        final session = daySessions[index];
                        final time = session.startedAt.toLocal();
                        final timeLabel =
                            '${time.hour.toString().padLeft(2, '0')}:'
                            '${time.minute.toString().padLeft(2, '0')}';
                        return Container(
                          padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFBF5F4),
                            borderRadius: BorderRadius.circular(15),
                            border: Border.all(color: const Color(0xFFF1E4E2)),
                          ),
                          child: Row(
                            children: [
                              Text(
                                timeLabel,
                                style: const TextStyle(
                                  color: Color(0xFF9A8C89),
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(width: 11),
                              Container(
                                width: 6,
                                height: 6,
                                decoration: const BoxDecoration(
                                  color: _accent,
                                  shape: BoxShape.circle,
                                ),
                              ),
                              const SizedBox(width: 11),
                              Expanded(
                                child: Text(
                                  session.content.trim().isEmpty
                                      ? '自由学习'
                                      : session.content.trim(),
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: _ink,
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 9,
                                  vertical: 5,
                                ),
                                decoration: BoxDecoration(
                                  color: Colors.white,
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Text(
                                  _sessionDuration(session.seconds),
                                  style: const TextStyle(
                                    color: _accent,
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ],
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
    );
  }

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final metrics = _FocusMetrics.fromSessions(sessions);
    final todaySessions = sessions.where(
      (session) => _sameDay(session.startedAt, now),
    );
    final todaySeconds = todaySessions.fold<int>(
      0,
      (total, session) => total + session.seconds,
    );
    final days = List.generate(7, (index) {
      final date = DateTime(now.year, now.month, now.day - 6 + index);
      final seconds = sessions
          .where((session) => _sameDay(session.startedAt, date))
          .fold<int>(0, (total, session) => total + session.seconds);
      return (date: date, seconds: seconds);
    });

    return Dialog(
      insetPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 32),
      backgroundColor: Colors.white.withValues(alpha: 0.96),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(26)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 430, maxHeight: 680),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '专注统计',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w700,
                        color: _ink,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(
                      Icons.close_rounded,
                      color: Color(0xFF8E807E),
                    ),
                  ),
                ],
              ),
              const Text(
                '同步手机与后端本月记录',
                style: TextStyle(fontSize: 12, color: Color(0xFF9A8C89)),
              ),
              const SizedBox(height: 18),
              Container(
                padding: const EdgeInsets.symmetric(vertical: 17),
                decoration: BoxDecoration(
                  color: const Color(0xFFFFF3F2),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: _TodayStat(
                        value: '${todaySessions.length}',
                        label: '今日次数',
                      ),
                    ),
                    Container(
                      width: 1,
                      height: 46,
                      color: const Color(0xFFECCFCD),
                    ),
                    Expanded(
                      child: _TodayStat(
                        value: _durationLabel(todaySeconds),
                        label: '今日时长',
                      ),
                    ),
                    Container(
                      width: 1,
                      height: 46,
                      color: const Color(0xFFECCFCD),
                    ),
                    Expanded(
                      child: _TodayStat(
                        value: '${metrics.streak}天',
                        label: '连续专注',
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              const Text(
                '近七天趋势',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: _ink,
                ),
              ),
              const SizedBox(height: 10),
              SizedBox(
                height: 165,
                child: _SevenDayChart(
                  days: days,
                  onDayTap: (date) => _showDaySessions(context, date),
                ),
              ),
              const SizedBox(height: 20),
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                childAspectRatio: 2.15,
                mainAxisSpacing: 10,
                crossAxisSpacing: 10,
                children: [
                  _DetailStat(
                    icon: Icons.date_range_rounded,
                    value: '${metrics.weekMinutes}分钟',
                    label: '本周累计',
                  ),
                  _DetailStat(
                    icon: Icons.calendar_view_week_rounded,
                    value: '${metrics.totalMinutes}分钟',
                    label: '本月累计',
                  ),
                  _DetailStat(
                    icon: Icons.check_circle_outline_rounded,
                    value: '${metrics.totalCount}次',
                    label: '本月次数',
                  ),
                  _DetailStat(
                    icon: Icons.timelapse_rounded,
                    value: '${metrics.averageMinutes}分钟',
                    label: '平均每次',
                  ),
                  _DetailStat(
                    icon: Icons.workspace_premium_outlined,
                    value: '${metrics.longestMinutes}分钟',
                    label: '最长一次',
                  ),
                  _DetailStat(
                    icon: Icons.emoji_events_outlined,
                    value: '${metrics.bestDayMinutes}分钟',
                    label: metrics.bestDay == null
                        ? '最佳一天'
                        : '${metrics.bestDay!.month}/${metrics.bestDay!.day} 最佳',
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DetailStat extends StatelessWidget {
  const _DetailStat({
    required this.icon,
    required this.value,
    required this.label,
  });
  final IconData icon;
  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
    decoration: BoxDecoration(
      color: const Color(0xFFFBF7F6),
      borderRadius: BorderRadius.circular(15),
      border: Border.all(color: const Color(0xFFF1E5E3)),
    ),
    child: Row(
      children: [
        Icon(icon, color: _accent, size: 20),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(
                value,
                maxLines: 1,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: _ink,
                ),
              ),
              Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 10.5,
                  color: Color(0xFF978986),
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class _DaySummaryValue extends StatelessWidget {
  const _DaySummaryValue({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text(
        value,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(
          color: _accent,
          fontSize: 16,
          fontWeight: FontWeight.w700,
        ),
      ),
      const SizedBox(height: 2),
      Text(
        label,
        style: const TextStyle(color: Color(0xFF9A8C89), fontSize: 10.5),
      ),
    ],
  );
}

class _TodayStat extends StatelessWidget {
  const _TodayStat({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Column(
    children: [
      Text(
        value,
        style: const TextStyle(
          color: _accent,
          fontSize: 22,
          fontWeight: FontWeight.w600,
        ),
      ),
      const SizedBox(height: 4),
      Text(label, style: const TextStyle(fontSize: 13, color: Colors.black54)),
    ],
  );
}

class _SevenDayChart extends StatelessWidget {
  const _SevenDayChart({required this.days, required this.onDayTap});

  final List<({DateTime date, int seconds})> days;
  final ValueChanged<DateTime> onDayTap;

  @override
  Widget build(BuildContext context) {
    final maxSeconds = days.fold<int>(
      0,
      (maximum, day) => day.seconds > maximum ? day.seconds : maximum,
    );
    const weekNames = ['一', '二', '三', '四', '五', '六', '日'];
    return LayoutBuilder(
      builder: (context, constraints) {
        final chartHeight = constraints.maxHeight - 40;
        return Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            for (final day in days)
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onDayTap(day.date),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: [
                      Text(
                        day.seconds == 0 ? '' : '${day.seconds ~/ 60}m',
                        style: const TextStyle(
                          fontSize: 10,
                          color: Colors.black45,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Container(
                        width: 22,
                        height: day.seconds == 0
                            ? 4
                            : (chartHeight * day.seconds / maxSeconds).clamp(
                                12.0,
                                chartHeight,
                              ),
                        decoration: BoxDecoration(
                          color: day.seconds == 0
                              ? const Color(0xFFE8E3E4)
                              : _accent.withValues(
                                  alpha: 0.32 + 0.68 * day.seconds / maxSeconds,
                                ),
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(5),
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '周${weekNames[day.date.weekday - 1]}',
                        style: const TextStyle(
                          fontSize: 11,
                          color: Colors.black54,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _FocusVideoBackground extends StatelessWidget {
  const _FocusVideoBackground({required this.controller});

  final VideoPlayerController controller;

  @override
  Widget build(BuildContext context) {
    return SizedBox.expand(child: VideoPlayer(controller));
  }
}

class _GlassIconButton extends StatelessWidget {
  const _GlassIconButton({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
    this.transparent = false,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback onPressed;
  final bool transparent;

  @override
  Widget build(BuildContext context) => Material(
    color: transparent
        ? Colors.transparent
        : Colors.white.withValues(alpha: 0.72),
    shape: const CircleBorder(),
    child: IconButton(
      onPressed: onPressed,
      tooltip: tooltip,
      icon: Icon(
        icon,
        color: transparent ? Colors.black : _accent,
        size: 29,
        shadows: transparent
            ? const [
                Shadow(color: Colors.white, blurRadius: 8),
                Shadow(color: Color(0x66000000), blurRadius: 3),
              ]
            : null,
      ),
    ),
  );
}

class _CompactFocusTimer extends StatelessWidget {
  const _CompactFocusTimer({required this.label, required this.onStop});

  final String label;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) => Material(
    color: Colors.transparent,
    borderRadius: BorderRadius.circular(22),
    child: InkWell(
      onTap: onStop,
      borderRadius: BorderRadius.circular(22),
      child: Container(
        width: double.infinity,
        height: 48,
        alignment: Alignment.center,
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            label,
            maxLines: 1,
            softWrap: false,
            style: const TextStyle(
              color: Colors.black,
              fontSize: 25,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.8,
              shadows: [
                Shadow(color: Colors.white, blurRadius: 8),
                Shadow(color: Color(0x55000000), blurRadius: 2),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class _DialogButton extends StatelessWidget {
  const _DialogButton({
    required this.label,
    required this.color,
    required this.textColor,
    required this.onPressed,
  });
  final String label;
  final Color color;
  final Color textColor;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: 92,
    height: 44,
    child: FilledButton(
      onPressed: onPressed,
      style: FilledButton.styleFrom(
        backgroundColor: color,
        foregroundColor: textColor,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
      child: Text(label, style: const TextStyle(fontSize: 16)),
    ),
  );
}

import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../config/api_config.dart';
import '../services/libra_api.dart';

class CallPage extends StatefulWidget {
  const CallPage({super.key, required this.deviceContextEnabled});

  final bool deviceContextEnabled;

  @override
  State<CallPage> createState() => _CallPageState();
}

class _CallPageState extends State<CallPage> {
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  final LibraApi _api = LibraApi();
  Timer? _clock;
  Timer? _vadTimer;
  DateTime? _recordingStartedAt;
  String? _callId;
  String? _activeGenerationId;
  bool _heardSpeech = false;
  int _speechMs = 0;
  int _silenceMs = 0;
  int _turnSequence = 0;
  int _seconds = 0;
  bool _connected = false;
  bool _recording = false;
  bool _busy = false;
  bool _muted = false;
  bool _speakerOn = true;
  bool _playbackDucked = false;
  Completer<void>? _playbackDone;
  String _status = '等待 Libra 接听…';

  @override
  void initState() {
    super.initState();
    _connect();
  }

  Future<void> _connect() async {
    try {
      if (!await _recorder.hasPermission()) throw Exception('请允许麦克风权限');
      _callId = await _api.startCall();
      if (!mounted) return;
      setState(() {
        _connected = true;
        _status = '正在听…';
      });
      _clock = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() => _seconds++);
      });
      await _startListening();
    } catch (_) {
      if (mounted) setState(() => _status = '通话连接失败');
    }
  }

  String get _duration {
    final minutes = (_seconds ~/ 60).toString().padLeft(2, '0');
    final seconds = (_seconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  Future<void> _startListening({bool duringPlayback = false}) async {
    if (!_connected || (_busy && !duringPlayback) || _muted || _recording) {
      return;
    }
    final directory = await getTemporaryDirectory();
    final path =
        '${directory.path}/call_${DateTime.now().millisecondsSinceEpoch}.wav';
    await _recorder.start(
      const RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
        echoCancel: true,
        noiseSuppress: true,
        autoGain: true,
      ),
      path: path,
    );
    if (!mounted) return;
    setState(() {
      _recording = true;
      _recordingStartedAt = DateTime.now();
      _heardSpeech = false;
      _speechMs = 0;
      _silenceMs = 0;
      if (!duringPlayback) _status = '正在听…';
    });
    _vadTimer?.cancel();
    _vadTimer = Timer.periodic(
      const Duration(milliseconds: 200),
      (_) => _checkVoice(),
    );
  }

  Future<void> _checkVoice() async {
    if (!_recording) return;
    final amplitude = await _recorder.getAmplitude();
    final speechThreshold = _busy ? -31.0 : -38.0;
    final silenceThreshold = _busy ? -37.0 : -43.0;
    if (amplitude.current > speechThreshold) {
      _heardSpeech = true;
      _speechMs += 200;
      _silenceMs = 0;
      if (_busy && !_playbackDucked && _speechMs >= 240) {
        _playbackDucked = true;
        await _player.setVolume(0.22);
      }
      if (_busy && _speechMs >= 520) await _interruptPlayback();
    } else if (_heardSpeech && amplitude.current < silenceThreshold) {
      _silenceMs += 200;
      if (_busy && _playbackDucked && _silenceMs >= 160 && _speechMs < 520) {
        _playbackDucked = false;
        _speechMs = 0;
        _silenceMs = 0;
        _heardSpeech = false;
        await _player.setVolume(1);
      }
    }
    final elapsed = DateTime.now().difference(_recordingStartedAt!).inSeconds;
    if (!_heardSpeech && elapsed >= 25) {
      _vadTimer?.cancel();
      await _recorder.stop();
      _recording = false;
      await _startListening();
    } else {
      final endpointMs = _speechMs < 1800 ? 900 : 1350;
      if (_heardSpeech && !_busy && _silenceMs >= endpointMs) {
        if (_speechMs >= 400) {
          await _sendRecording();
        } else {
          _heardSpeech = false;
          _speechMs = 0;
          _silenceMs = 0;
        }
      } else if (elapsed >= 60) {
        _vadTimer?.cancel();
        await _recorder.stop();
        _recording = false;
        await _startListening();
      }
    }
  }

  Future<void> _interruptPlayback() async {
    if (!_busy) return;
    final generationId = _activeGenerationId;
    _activeGenerationId = null;
    await _player.stop();
    await _player.setVolume(1);
    _playbackDucked = false;
    if (!(_playbackDone?.isCompleted ?? true)) _playbackDone!.complete();
    if (_callId != null && generationId != null) {
      unawaited(_api.interruptCall(_callId!, generationId));
    }
    if (mounted) {
      setState(() {
        _busy = false;
        _status = '正在听…';
      });
    }
  }

  String _nextIdentity(String kind) {
    _turnSequence++;
    return '${kind}_${DateTime.now().microsecondsSinceEpoch}_$_turnSequence';
  }

  Future<void> _playReply(String mediaUrl) async {
    final completer = Completer<void>();
    _playbackDone = completer;
    final subscription = _player.onPlayerComplete.listen((_) {
      if (!completer.isCompleted) completer.complete();
    });
    await _player.setVolume(1);
    await _player.play(UrlSource('${ApiConfig.baseUrl}$mediaUrl'));
    await completer.future;
    await subscription.cancel();
    if (identical(_playbackDone, completer)) _playbackDone = null;
    await _player.setVolume(1);
    _playbackDucked = false;
  }

  Future<void> _sendRecording() async {
    _vadTimer?.cancel();
    final path = await _recorder.stop();
    final elapsed = DateTime.now()
        .difference(_recordingStartedAt!)
        .inSeconds
        .clamp(1, 300);
    if (!mounted) return;
    setState(() {
      _recording = false;
      _busy = true;
      _status = 'Libra 正在思考…';
    });
    if (path == null) {
      setState(() => _busy = false);
      await _startListening();
      return;
    }
    try {
      final turnId = _nextIdentity('turn');
      final generationId = _nextIdentity('gen');
      final result = await _api.sendCallTurn(
        _callId!,
        path,
        elapsed,
        deviceContextEnabled: widget.deviceContextEnabled,
        turnId: turnId,
        generationId: generationId,
      );
      if (!mounted) return;
      _activeGenerationId = result.generationId;
      setState(() => _status = 'Libra 正在说话…');
      await _playReply(result.mediaUrl);
      if (mounted) {
        setState(() {
          _busy = false;
          _activeGenerationId = null;
          _status = _muted ? '麦克风已关闭' : '正在听…';
        });
        await _startListening();
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _busy = false;
          _status = _muted ? '麦克风已关闭' : '没听清，正在重新听…';
        });
        await _startListening();
      }
    }
  }

  Future<void> _toggleMute() async {
    _muted = !_muted;
    if (_muted) {
      _vadTimer?.cancel();
      if (_recording) await _recorder.stop();
      if (mounted) {
        setState(() {
          _recording = false;
          _status = '麦克风已关闭';
        });
      }
    } else {
      if (mounted) setState(() => _status = '正在听…');
      await _startListening();
    }
  }

  Future<void> _hangUp() async {
    _vadTimer?.cancel();
    if (_recording) await _recorder.stop();
    await _player.stop();
    if (_callId != null) await _api.finishCall(_callId!);
    if (mounted) Navigator.of(context).pop(true);
  }

  @override
  void dispose() {
    _clock?.cancel();
    _vadTimer?.cancel();
    _recorder.dispose();
    _player.dispose();
    _api.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: true,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) {
          _vadTimer?.cancel();
          if (_recording) _recorder.stop();
          _player.stop();
          if (_callId != null) _api.finishCall(_callId!);
        }
      },
      child: Scaffold(
        body: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [Color(0xFF171310), Color(0xFF3B352D), Color(0xFF141C20)],
            ),
          ),
          child: SafeArea(
            child: Column(
              children: [
                SizedBox(
                  height: 72,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      if (_connected)
                        CustomPaint(
                          size: const Size(72, 28),
                          painter: _CallTimerPainter(_duration),
                        ),
                    ],
                  ),
                ),
                const Spacer(flex: 2),
                ClipRRect(
                  borderRadius: BorderRadius.circular(22),
                  child: Image.asset(
                    'assets/avatars/libra.png',
                    width: 136,
                    height: 136,
                    fit: BoxFit.cover,
                  ),
                ),
                const SizedBox(height: 22),
                const Text(
                  'Libra',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 32,
                    fontWeight: FontWeight.w400,
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  _status,
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.66),
                    fontSize: 17,
                  ),
                ),
                const Spacer(flex: 3),
                Padding(
                  padding: const EdgeInsets.fromLTRB(30, 0, 30, 42),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      _CallAction(
                        icon: _muted
                            ? Icons.mic_off_rounded
                            : Icons.mic_rounded,
                        label: _muted ? '麦克风已关' : '麦克风已开',
                        active: !_muted,
                        onTap: _toggleMute,
                      ),
                      _CallAction(
                        icon: Icons.call_end_rounded,
                        label: '挂断',
                        background: const Color(0xFFE34D4F),
                        onTap: _hangUp,
                      ),
                      _CallAction(
                        icon: _speakerOn
                            ? Icons.volume_up_rounded
                            : Icons.volume_off_rounded,
                        label: _speakerOn ? '扬声器已开' : '扬声器已关',
                        active: _speakerOn,
                        onTap: () async {
                          setState(() => _speakerOn = !_speakerOn);
                          await _player.setVolume(_speakerOn ? 1 : 0);
                        },
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _CallTimerPainter extends CustomPainter {
  const _CallTimerPainter(this.value);

  final String value;

  @override
  void paint(Canvas canvas, Size size) {
    final painter = TextPainter(
      text: TextSpan(
        text: value,
        style: const TextStyle(color: Colors.white, fontSize: 18),
      ),
      textDirection: TextDirection.ltr,
      textAlign: TextAlign.center,
    )..layout(maxWidth: size.width);
    painter.paint(
      canvas,
      Offset(
        (size.width - painter.width) / 2,
        (size.height - painter.height) / 2,
      ),
    );
  }

  @override
  bool shouldRepaint(covariant _CallTimerPainter oldDelegate) {
    return oldDelegate.value != value;
  }
}

class _CallAction extends StatelessWidget {
  const _CallAction({
    required this.icon,
    required this.label,
    required this.onTap,
    this.active = false,
    this.background,
  });
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool active;
  final Color? background;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 96,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          InkWell(
            onTap: onTap,
            customBorder: const CircleBorder(),
            child: Container(
              width: 76,
              height: 76,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color:
                    background ??
                    (active
                        ? Colors.white
                        : Colors.black.withValues(alpha: 0.3)),
              ),
              child: Icon(
                icon,
                size: 36,
                color: background != null
                    ? Colors.white
                    : (active ? Colors.black : Colors.white),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            label,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white, fontSize: 14),
          ),
        ],
      ),
    );
  }
}

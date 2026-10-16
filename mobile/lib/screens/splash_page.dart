import 'dart:async';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../services/weather_service.dart';
import 'app_shell.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({super.key});

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  late final VideoPlayerController _controller;
  late final Future<WeatherLoadResult> _weatherFuture;
  late final Future<HomeCache> _homeCacheFuture;
  Timer? _fallbackTimer;
  bool _ready = false;
  bool _openingChat = false;
  bool _appShown = false;

  @override
  void initState() {
    super.initState();
    _weatherFuture = loadInitialWeatherSafely();
    _homeCacheFuture = HomeCache.load();
    _controller = VideoPlayerController.asset('assets/open_video.mp4')
      ..addListener(_handlePlayback);
    _initializeVideo();
    _fallbackTimer = Timer(const Duration(seconds: 8), _openAppImmediately);
  }

  Future<void> _initializeVideo() async {
    try {
      await _controller.initialize();
      await _controller.setLooping(false);
      await _controller.setVolume(0);
      if (!mounted) return;
      setState(() => _ready = true);
      await _controller.play();
    } catch (_) {
      _openApp();
    }
  }

  void _handlePlayback() {
    if (!_controller.value.isInitialized || _openingChat) return;
    final value = _controller.value;
    if (value.position >= value.duration - const Duration(milliseconds: 80)) {
      _openApp();
    }
  }

  Future<void> _openApp() async {
    if (!mounted || _openingChat) return;
    _openingChat = true;
    await _weatherFuture;
    await _homeCacheFuture;
    if (!mounted || _appShown) return;
    _showApp();
  }

  Future<void> _openAppImmediately() async {
    if (!mounted || _appShown) return;
    await _homeCacheFuture;
    if (!mounted || _appShown) return;
    _showApp();
  }

  Future<void> _showApp() async {
    if (_appShown) return;
    final homeCache = await _homeCacheFuture;
    if (!mounted || _appShown) return;
    _appShown = true;
    _fallbackTimer?.cancel();
    Navigator.of(context).pushReplacement(
      PageRouteBuilder<void>(
        transitionDuration: const Duration(milliseconds: 280),
        pageBuilder: (_, animation, secondaryAnimation) =>
            AppShell(initialWeather: _weatherFuture, homeCache: homeCache),
        transitionsBuilder: (_, animation, secondaryAnimation, child) {
          return FadeTransition(opacity: animation, child: child);
        },
      ),
    );
  }

  @override
  void dispose() {
    _fallbackTimer?.cancel();
    _controller
      ..removeListener(_handlePlayback)
      ..dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFFFF5F3),
      body: _ready
          ? SizedBox.expand(
              child: FittedBox(
                fit: BoxFit.cover,
                child: SizedBox(
                  width: _controller.value.size.width,
                  height: _controller.value.size.height,
                  child: VideoPlayer(_controller),
                ),
              ),
            )
          : const SizedBox.expand(),
    );
  }
}

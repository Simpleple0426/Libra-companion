import 'dart:async';

import 'package:flutter/material.dart';

import '../services/weather_service.dart';
import 'app_shell.dart';

class SplashPage extends StatefulWidget {
  const SplashPage({super.key});

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  late final Future<WeatherLoadResult> _weatherFuture;
  late final Future<HomeCache> _homeCacheFuture;
  @override
  void initState() {
    super.initState();
    _weatherFuture = loadInitialWeatherSafely();
    _homeCacheFuture = HomeCache.load();
    unawaited(_showApp());
  }

  Future<void> _showApp() async {
    final homeCache = await _homeCacheFuture;
    if (!mounted) return;
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
  Widget build(BuildContext context) =>
      const Scaffold(backgroundColor: Color(0xFFFFF5F3));
}

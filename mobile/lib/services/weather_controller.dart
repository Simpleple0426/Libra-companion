import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/weather_summary.dart';
import 'weather_service.dart';

typedef WeatherLoader = Future<WeatherLoadResult> Function();

class WeatherController extends ChangeNotifier {
  WeatherController({
    WeatherLoader? loader,
    this.refreshInterval = const Duration(minutes: 30),
  }) : _loader = loader ?? loadWeatherSafely;

  final WeatherLoader _loader;
  final Duration refreshInterval;

  WeatherSummary? weather;
  String? error;
  bool loading = true;
  DateTime? lastSuccessAt;

  bool _requestInProgress = false;
  bool _disposed = false;

  Future<void> initialize(Future<WeatherLoadResult> initialResult) async {
    if (_requestInProgress) return;
    _requestInProgress = true;
    try {
      _apply(await initialResult);
    } catch (_) {
      _apply(const WeatherLoadResult(error: '天气暂时无法获取'));
    }
  }

  Future<void> refresh({bool showLoading = true}) async {
    if (_requestInProgress) return;
    _requestInProgress = true;
    if (showLoading || weather == null) {
      loading = true;
      error = null;
      _notify();
    }
    try {
      _apply(await _loader());
    } catch (_) {
      _apply(const WeatherLoadResult(error: '天气暂时无法获取'));
    }
  }

  void refreshIfStale() {
    final refreshedAt = lastSuccessAt;
    final hasFreshWeather =
        weather != null &&
        refreshedAt != null &&
        DateTime.now().difference(refreshedAt) < refreshInterval;
    if (!_requestInProgress && !hasFreshWeather) {
      unawaited(refresh(showLoading: false));
    }
  }

  void _apply(WeatherLoadResult result) {
    if (_disposed) return;
    if (result.weather != null) {
      weather = result.weather;
      error = null;
      lastSuccessAt = DateTime.now();
    } else {
      error = result.error;
    }
    loading = false;
    _requestInProgress = false;
    notifyListeners();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

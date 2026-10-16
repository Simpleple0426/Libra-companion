import 'package:flutter/services.dart';

import '../models/app_usage_event.dart';

class AppUsageService {
  static const _channel = MethodChannel('com.libra.companion/app_usage');

  Future<bool> getProactiveEnabled() async {
    return await _channel.invokeMethod<bool>('getProactiveEnabled') ?? false;
  }

  Future<void> setProactiveEnabled(bool enabled, String baseUrl) =>
      _channel.invokeMethod<void>('setProactiveEnabled', {
        'enabled': enabled,
        'baseUrl': baseUrl,
      });

  Future<List<AppUsageEvent>> getTodayEvents() async {
    final rows =
        await _channel.invokeListMethod<Object?>('getTodayEvents') ?? [];
    return rows
        .whereType<Map<Object?, Object?>>()
        .map(AppUsageEvent.fromMap)
        .toList();
  }

  Future<void> recordFocusEvent(String description) => _channel
      .invokeMethod<void>('recordFocusEvent', {'description': description});

  Future<void> setKeepScreenOn(bool enabled) =>
      _channel.invokeMethod<void>('setKeepScreenOn', {'enabled': enabled});

  Future<void> setFocusBackgroundPlayback(bool enabled) => _channel
      .invokeMethod<void>('setFocusBackgroundPlayback', {'enabled': enabled});
}

import 'dart:convert';
import 'dart:async';
import 'dart:io';

import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import '../models/weather_summary.dart';

class WeatherLoadResult {
  const WeatherLoadResult({this.weather, this.error});

  final WeatherSummary? weather;
  final String? error;
}

Future<WeatherLoadResult> loadWeatherSafely() async {
  final service = WeatherService();
  try {
    return WeatherLoadResult(weather: await service.load());
  } catch (error) {
    try {
      return WeatherLoadResult(weather: await service.loadLastKnown());
    } catch (_) {
      return WeatherLoadResult(
        error: error is WeatherException ? error.message : '天气暂时无法获取',
      );
    }
  }
}

/// Load a server-side observation first so the home page never waits for GPS.
/// A live location refresh runs after the shell is visible.
Future<WeatherLoadResult> loadInitialWeatherSafely() async {
  final service = WeatherService();
  try {
    return WeatherLoadResult(weather: await service.loadLastKnown());
  } catch (_) {
    return loadWeatherSafely();
  }
}

class WeatherService {
  Future<WeatherSummary> loadLastKnown() async {
    late final http.Response response;
    try {
      response = await http
          .get(Uri.parse('${ApiConfig.baseUrl}/weather/last'))
          .timeout(const Duration(seconds: 30));
    } on TimeoutException {
      throw const WeatherException('连接天气服务超时，点击重试');
    } on SocketException {
      throw const WeatherException('无法连接电脑后端，请检查 Tailscale');
    } on http.ClientException {
      throw const WeatherException('无法连接电脑后端，请检查 Tailscale');
    }
    return _decodeResponse(response);
  }

  Future<WeatherSummary> load() async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      throw const WeatherException('请先打开手机定位');
    }

    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied) {
      throw const WeatherException('需要定位权限才能显示天气');
    }
    if (permission == LocationPermission.deniedForever) {
      throw const WeatherException('请在系统设置中允许定位权限');
    }

    late final Position position;
    try {
      position =
          await Geolocator.getCurrentPosition(
            locationSettings: Platform.isAndroid
                ? AndroidSettings(
                    accuracy: LocationAccuracy.high,
                    forceLocationManager: true,
                    timeLimit: Duration(seconds: 20),
                  )
                : const LocationSettings(
                    accuracy: LocationAccuracy.high,
                    timeLimit: Duration(seconds: 20),
                  ),
          ).onError((_, _) async {
            final cached = await Geolocator.getLastKnownPosition().timeout(
              const Duration(seconds: 5),
              onTimeout: () => null,
            );
            if (cached != null) return cached;
            throw const WeatherException('无法获取手机实时位置，请到开阔处后重试');
          });
    } on TimeoutException {
      throw const WeatherException('定位超时，请到开阔处后点击重试');
    }

    late final http.Response response;
    try {
      response = await http
          .post(
            Uri.parse('${ApiConfig.baseUrl}/weather'),
            headers: const {'Content-Type': 'application/json; charset=UTF-8'},
            body: jsonEncode({
              'latitude': position.latitude,
              'longitude': position.longitude,
            }),
          )
          .timeout(const Duration(seconds: 30));
    } on TimeoutException {
      throw const WeatherException('连接天气服务超时，点击重试');
    } on SocketException {
      throw const WeatherException('无法连接电脑后端，请检查 Tailscale');
    } on http.ClientException {
      throw const WeatherException('无法连接电脑后端，请检查 Tailscale');
    }
    return _decodeResponse(response, position: position);
  }

  WeatherSummary _decodeResponse(http.Response response, {Position? position}) {
    final body = jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode != 200 || body is! Map<String, dynamic>) {
      throw const WeatherException('天气暂时无法获取');
    }
    if (body['success'] != true) {
      throw WeatherException('${body['error'] ?? '天气暂时无法获取'}');
    }
    if (position != null) {
      body['latitude'] = position.latitude;
      body['longitude'] = position.longitude;
    }
    return WeatherSummary.fromJson(body);
  }
}

class WeatherException implements Exception {
  const WeatherException(this.message);
  final String message;

  @override
  String toString() => message;
}

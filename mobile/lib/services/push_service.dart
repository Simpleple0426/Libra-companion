import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'libra_api.dart';
import 'display_names.dart';
import '../config/api_config.dart';

class PushService {
  PushService._();

  static final instance = PushService._();
  final requestedTab = ValueNotifier<int?>(null);
  final chatMessageReceived = ValueNotifier<int>(0);
  StreamSubscription<String>? _tokenSubscription;
  Timer? _retryTimer;
  bool _firebaseReady = false;
  static const _nativeChannel = MethodChannel('com.libra.companion/app_usage');

  Future<void> initialize() async {
    if (appFlavor == 'dev') {
      await _enablePollingFallback();
      return;
    }
    try {
      if (!_firebaseReady) {
        await Firebase.initializeApp();
        _firebaseReady = true;
        final messaging = FirebaseMessaging.instance;
        await messaging.requestPermission(
          alert: true,
          badge: true,
          sound: true,
        );
        FirebaseMessaging.onMessageOpenedApp.listen(_openMessage);
        FirebaseMessaging.onMessage.listen((message) async {
          if (message.data['route'] == 'chat') {
            chatMessageReceived.value++;
            final body = message.notification?.body?.trim() ?? '';
            if (body.isNotEmpty) {
              try {
                await _nativeChannel.invokeMethod<void>(
                  'showProactiveNotification',
                  {
                    'title': message.notification?.title ?? DisplayNames.libra,
                    'body': body,
                    'messageId':
                        message.data['message_id'] ?? message.messageId ?? '',
                  },
                );
              } catch (error) {
                debugPrint('Foreground notification failed: $error');
              }
            }
          }
        });
        final initialMessage = await messaging.getInitialMessage();
        if (initialMessage != null) _openMessage(initialMessage);
        _tokenSubscription = messaging.onTokenRefresh.listen(_registerToken);
      }
      final token = await FirebaseMessaging.instance.getToken().timeout(
        const Duration(seconds: 20),
      );
      if (token != null && token.isNotEmpty) await _registerToken(token);
      // FCM is the fast path, but it is not a delivery guarantee on every
      // Android device/network. Keep the native poller as a safety net so a
      // delayed or lost FCM notification can still be surfaced.
      await _enablePollingFallback();
      _retryTimer?.cancel();
    } catch (error) {
      debugPrint('Firebase push initialization failed: $error');
      await _enablePollingFallback();
      _retryTimer?.cancel();
      _retryTimer = Timer(const Duration(seconds: 30), initialize);
    }
  }

  Future<void> _enablePollingFallback() async {
    final api = LibraApi();
    try {
      final messages = await api.getMessages();
      final latestId = messages.fold<int>(
        0,
        (value, message) =>
            message.id != null && message.id! > value ? message.id! : value,
      );
      await _setPollingFallback(true, latestMessageId: latestId);
    } catch (error) {
      debugPrint('Push polling fallback initialization failed: $error');
    } finally {
      api.close();
    }
  }

  Future<void> _setPollingFallback(bool enabled, {int? latestMessageId}) =>
      _nativeChannel.invokeMethod<void>('setPushFallbackEnabled', {
        'enabled': enabled,
        'baseUrl': ApiConfig.baseUrl,
        if (latestMessageId != null) 'latestMessageId': latestMessageId,
      });

  void _openMessage(RemoteMessage message) {
    if (message.data['route'] == 'chat') {
      chatMessageReceived.value++;
      requestedTab.value = 1;
    }
  }

  Future<void> _registerToken(String token) async {
    final api = LibraApi();
    try {
      await api.registerPushToken(token);
    } finally {
      api.close();
    }
  }

  void dispose() {
    _retryTimer?.cancel();
    _tokenSubscription?.cancel();
  }
}

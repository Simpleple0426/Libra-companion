import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'config/api_config.dart';
import 'screens/backend_connection_page.dart';
import 'screens/splash_page.dart';
import 'services/push_service.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ApiConfig.initialize();
  await SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.dark,
      statusBarBrightness: Brightness.light,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarIconBrightness: Brightness.dark,
      systemNavigationBarDividerColor: Colors.transparent,
      systemStatusBarContrastEnforced: false,
      systemNavigationBarContrastEnforced: false,
    ),
  );
  runApp(const LibraApp());
  if (ApiConfig.isConfigured) {
    unawaited(PushService.instance.initialize());
  }
}

class LibraApp extends StatelessWidget {
  const LibraApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seedColor = Color(0xFF796A61);

    return MaterialApp(
      title: '同归',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: seedColor,
          brightness: Brightness.light,
        ),
        scaffoldBackgroundColor: const Color(0xFFF7E3E1),
        useMaterial3: true,
      ),
      home: ApiConfig.isConfigured
          ? const SplashPage()
          : const BackendConnectionPage(),
    );
  }
}

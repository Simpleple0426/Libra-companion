import 'dart:async';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../config/api_config.dart';
import '../services/push_service.dart';
import '../services/backend_connection.dart';
import 'splash_page.dart';

class BackendConnectionPage extends StatefulWidget {
  const BackendConnectionPage({super.key});

  @override
  State<BackendConnectionPage> createState() => _BackendConnectionPageState();
}

class _BackendConnectionPageState extends State<BackendConnectionPage> {
  final _controller = TextEditingController(text: ApiConfig.baseUrl);
  bool _showAddress = false;
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _continue() async {
    final value = _controller.text.trim();
    setState(() {
      _saving = true;
      _error = null;
    });
    final client = http.Client();
    try {
      final verified = await verifyBackendConnection(value, client);
      if (!mounted) return;
      await ApiConfig.saveBaseUrl(verified);
      unawaited(PushService.instance.initialize());
      if (!mounted) return;
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute<void>(builder: (_) => const SplashPage()),
        (_) => false,
      );
    } on FormatException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) {
        setState(() => _error = '无法连接，请检查地址、网络和服务器运行状态');
      }
    } finally {
      client.close();
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: Navigator.of(context).canPop()
          ? AppBar(title: const Text('服务器连接'))
          : null,
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFFFFE4E2), Color(0xFFFFF7F5)],
          ),
        ),
        child: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) => SingleChildScrollView(
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              padding: EdgeInsets.fromLTRB(
                28,
                28,
                28,
                28 + MediaQuery.viewInsetsOf(context).bottom,
              ),
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: constraints.maxHeight),
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 430),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        const Icon(
                          Icons.favorite_outline,
                          color: Color(0xFFE37C7C),
                          size: 42,
                        ),
                        const SizedBox(height: 20),
                        const Text(
                          '连接你的 Libra',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 28,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          '粘贴服务器的完整私人连接地址。\n本地测试可填写电脑的局域网地址。',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Color(0xFF766B68),
                            height: 1.6,
                          ),
                        ),
                        const SizedBox(height: 28),
                        TextField(
                          controller: _controller,
                          enabled: !_saving,
                          obscureText: !_showAddress,
                          keyboardType: TextInputType.url,
                          autocorrect: false,
                          enableSuggestions: false,
                          decoration: InputDecoration(
                            labelText: '后端地址',
                            hintText: 'https://服务器域名/connect/…',
                            suffixIcon: IconButton(
                              tooltip: _showAddress ? '隐藏地址' : '显示地址',
                              onPressed: () =>
                                  setState(() => _showAddress = !_showAddress),
                              icon: Icon(
                                _showAddress
                                    ? Icons.visibility_off
                                    : Icons.visibility,
                              ),
                            ),
                            errorText: _error,
                            filled: true,
                            fillColor: Colors.white.withValues(alpha: 0.78),
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.circular(18),
                              borderSide: BorderSide.none,
                            ),
                          ),
                          onSubmitted: (_) {
                            if (!_saving) _continue();
                          },
                        ),
                        const SizedBox(height: 12),
                        FilledButton(
                          onPressed: _saving ? null : _continue,
                          style: FilledButton.styleFrom(
                            padding: const EdgeInsets.symmetric(vertical: 16),
                            backgroundColor: const Color(0xFFE37C7C),
                          ),
                          child: Text(_saving ? '正在验证连接…' : '连接'),
                        ),
                        const SizedBox(height: 16),
                        const Text(
                          '私人地址包含访问密钥，请勿分享。\n以后可以在首页设置中修改连接地址。',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontSize: 12,
                            color: Color(0xFF9A8985),
                            height: 1.45,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

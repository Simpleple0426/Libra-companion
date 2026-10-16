import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:video_player/video_player.dart';

import '../config/api_config.dart';
import 'home_page.dart';

class LocalMoviePlayerPage extends StatefulWidget {
  const LocalMoviePlayerPage({super.key});

  @override
  State<LocalMoviePlayerPage> createState() => _LocalMoviePlayerPageState();
}

class _LocalMoviePlayerPageState extends State<LocalMoviePlayerPage> {
  List<Map<String, dynamic>> _movies = const [];
  VideoPlayerController? _controller;
  String? _selectedUrl;
  bool _loading = true;
  bool _opening = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadMovies();
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  Future<void> _loadMovies() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final response = await http
          .get(Uri.parse('${ApiConfig.baseUrl}/room-media/movies'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw Exception('HTTP ${response.statusCode}');
      }
      final value = jsonDecode(utf8.decode(response.bodyBytes));
      final items = value is Map ? value['movies'] : null;
      if (!mounted) return;
      setState(() {
        _movies = items is List
            ? items
                  .whereType<Map>()
                  .map((item) => Map<String, dynamic>.from(item))
                  .toList()
            : const [];
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '暂时无法读取电脑上的影片';
      });
    }
  }

  Future<void> _openMovie(Map<String, dynamic> movie) async {
    final path = '${movie['url'] ?? ''}';
    if (path.isEmpty || _opening) return;
    setState(() {
      _opening = true;
      _error = null;
    });
    final next = VideoPlayerController.networkUrl(
      Uri.parse('${ApiConfig.baseUrl}$path'),
    );
    try {
      await next.initialize();
      await next.setLooping(false);
      final previous = _controller;
      if (!mounted) {
        await next.dispose();
        return;
      }
      setState(() {
        _controller = next;
        _selectedUrl = path;
        _opening = false;
      });
      await previous?.dispose();
      await next.play();
    } catch (_) {
      await next.dispose();
      if (!mounted) return;
      setState(() {
        _opening = false;
        _error = '这部影片暂时无法播放';
      });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: const Color(0xFFFFF7F6),
    appBar: AppBar(
      backgroundColor: const Color(0xFFFFE2DF),
      foregroundColor: const Color(0xFF5A4542),
      title: const Text('电影室'),
      actions: [
        IconButton(
          onPressed: _loading ? null : _loadMovies,
          icon: const Icon(Icons.refresh),
        ),
      ],
    ),
    body: DecoratedBox(
      decoration: const BoxDecoration(
        image: DecorationImage(
          image: AssetImage('assets/images/home_background.png'),
          fit: BoxFit.cover,
        ),
      ),
      child: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 18, 18, 32),
          children: [
            _player(),
            const SizedBox(height: 18),
            const Text(
              '本地影片',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Color(0xFF493936),
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              '播放你已经放入影片库的电影。',
              style: TextStyle(fontSize: 12, color: Color(0xFF9D8985)),
            ),
            const SizedBox(height: 12),
            if (_loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(30),
                  child: CircularProgressIndicator(),
                ),
              )
            else if (_error != null)
              _message(_error!, Icons.error_outline)
            else if (_movies.isEmpty)
              _message(
                '还没有影片\n把自有 MP4 文件放到本地影片后刷新',
                Icons.movie_creation_outlined,
              )
            else
              ..._movies.map((movie) => _movieTile(movie)),
          ],
        ),
      ),
    ),
  );

  Widget _player() {
    final controller = _controller;
    if (controller == null || !controller.value.isInitialized) {
      return Container(
        height: 205,
        decoration: BoxDecoration(
          color: const Color(0xFF3D3332),
          borderRadius: BorderRadius.circular(22),
        ),
        alignment: Alignment.center,
        child: _opening
            ? const CircularProgressIndicator(color: Colors.white)
            : const Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.movie_outlined,
                    color: Color(0xFFFFC9C3),
                    size: 48,
                  ),
                  SizedBox(height: 8),
                  Text('选一部电影', style: TextStyle(color: Colors.white70)),
                ],
              ),
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(22),
      child: AspectRatio(
        aspectRatio: controller.value.aspectRatio == 0
            ? 16 / 9
            : controller.value.aspectRatio,
        child: Stack(
          fit: StackFit.expand,
          children: [
            VideoPlayer(controller),
            Center(
              child: IconButton.filledTonal(
                iconSize: 38,
                onPressed: () async {
                  controller.value.isPlaying
                      ? await controller.pause()
                      : await controller.play();
                  if (mounted) setState(() {});
                },
                icon: Icon(
                  controller.value.isPlaying
                      ? Icons.pause_rounded
                      : Icons.play_arrow_rounded,
                ),
              ),
            ),
            Align(
              alignment: Alignment.bottomCenter,
              child: VideoProgressIndicator(
                controller,
                allowScrubbing: true,
                padding: const EdgeInsets.all(10),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _movieTile(Map<String, dynamic> movie) {
    final path = '${movie['url'] ?? ''}';
    final selected = path == _selectedUrl;
    final bytes = (movie['size_bytes'] as num?)?.toInt() ?? 0;
    final size = bytes <= 0
        ? ''
        : '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
    return Card(
      color: selected
          ? const Color(0xFFFFDFDB)
          : Colors.white.withValues(alpha: .88),
      child: ListTile(
        leading: Icon(
          selected ? Icons.play_circle_fill_rounded : Icons.movie_outlined,
          color: homeAccent,
        ),
        title: Text(
          '${movie['name'] ?? '未命名影片'}',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        subtitle: size.isEmpty ? null : Text(size),
        trailing: const Icon(Icons.chevron_right_rounded),
        onTap: () => _openMovie(movie),
      ),
    );
  }

  Widget _message(String text, IconData icon) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 34),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .82),
      borderRadius: BorderRadius.circular(22),
    ),
    child: Column(
      children: [
        Icon(icon, size: 42, color: homeAccent),
        const SizedBox(height: 10),
        Text(
          text,
          textAlign: TextAlign.center,
          style: const TextStyle(color: Color(0xFF806E6A), height: 1.5),
        ),
      ],
    ),
  );
}

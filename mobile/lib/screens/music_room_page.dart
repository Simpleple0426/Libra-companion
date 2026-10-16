import 'dart:async';
import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/api_config.dart';
import '../models/chat_message.dart';
import '../services/libra_api.dart';

const _pink = Color(0xFFE77E82);
const _ink = Color(0xFF524849);

class MusicRoomPage extends StatefulWidget {
  const MusicRoomPage({super.key});

  @override
  State<MusicRoomPage> createState() => _MusicRoomPageState();
}

class _MusicRoomPageState extends State<MusicRoomPage> {
  final _player = AudioPlayer();
  final _api = LibraApi();
  final _input = TextEditingController();
  final _lyricsScroll = ScrollController();
  final _chatScroll = ScrollController();
  final _queue = <_Song>[];
  final _chat = <ChatMessage>[];
  Timer? _nowPlayingTimer;
  List<_Lyric> _lyrics = const [];
  _Song? _song;
  _Lyric? _selectedLyric;
  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  bool _playing = false;
  bool _sending = false;
  bool _savingSong = false;
  String _partnerNickname = '左然';
  String _userNickname = '我';
  Set<int> _savedSongIds = {};
  int _membershipRevision = 0;

  @override
  void initState() {
    super.initState();
    _player.onPlayerComplete.listen((_) {
      if (mounted) _skip(1);
    });
    _player.onPositionChanged.listen(
      (v) => mounted ? setState(() => _position = v) : null,
    );
    _player.onDurationChanged.listen(
      (v) => mounted ? setState(() => _duration = v) : null,
    );
    _player.onPlayerStateChanged.listen(
      (v) =>
          mounted ? setState(() => _playing = v == PlayerState.playing) : null,
    );
    _nowPlayingTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => _syncNowPlaying(),
    );
    _loadMusicChat();
    _loadNicknames();
    _refreshPlaylistMembership();
  }

  @override
  void dispose() {
    _nowPlayingTimer?.cancel();
    _player.dispose();
    _input.dispose();
    _lyricsScroll.dispose();
    _chatScroll.dispose();
    super.dispose();
  }

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${ApiConfig.baseUrl}$path').replace(queryParameters: query);

  Future<List<_Song>> _search(String query) async {
    final response = await http
        .get(_uri('/music/search', {'q': query}))
        .timeout(const Duration(seconds: 30));
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (response.statusCode >= 400)
      throw Exception(decoded is Map ? decoded['detail'] : '搜索失败');
    final values = decoded is List
        ? decoded
        : (decoded is Map ? decoded['value'] : null);
    if (values is! List) return const [];
    return values
        .whereType<Map<String, dynamic>>()
        .map(_Song.fromJson)
        .toList();
  }

  Future<void> _play(_Song song) async {
    if (!song.playable) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            song.unavailableReason.isEmpty
                ? '这首歌当前无法播放，但仍可查看歌曲信息'
                : song.unavailableReason,
          ),
        ),
      );
      return;
    }
    setState(() {
      _song = song;
      _lyrics = const [];
      _selectedLyric = null;
    });
    try {
      var url = song.playUrl;
      var fallbackUrl = '';
      if (url.isEmpty) {
        final response = await http
            .get(_uri('/music/url/${song.id}'))
            .timeout(const Duration(seconds: 30));
        if (response.statusCode >= 400) throw Exception('播放地址获取失败，请重试');
        final data = jsonDecode(utf8.decode(response.bodyBytes));
        url = (data is Map ? data['url'] : '')?.toString() ?? '';
        fallbackUrl = (data is Map ? data['cache_url'] : '')?.toString() ?? '';
        if (url.isEmpty) {
          throw Exception(
            data is Map ? data['reason'] ?? '这首歌暂时没有可播放音源' : '这首歌暂时没有可播放音源',
          );
        }
      }
      if (url.startsWith('/')) url = '${ApiConfig.baseUrl}$url';
      if (fallbackUrl.startsWith('/'))
        fallbackUrl = '${ApiConfig.baseUrl}$fallbackUrl';
      if (url.isEmpty) throw Exception('这首歌暂时没有可播放音源');
      try {
        await _player.play(UrlSource(url));
      } catch (_) {
        if (fallbackUrl.isEmpty || fallbackUrl == url) rethrow;
        await _player.play(UrlSource(fallbackUrl));
      }
      unawaited(_loadSongLyrics(song));
      unawaited(_syncNowPlaying());
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  Future<void> _loadSongLyrics(_Song song) async {
    try {
      final response = await http
          .get(_uri('/music/lyric/${song.id}'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode >= 400) return;
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (mounted && identical(_song, song)) {
        setState(() => _lyrics = _parseLrc((data['lyric'] ?? '').toString()));
      }
    } catch (_) {
      // Lyrics are optional and must not prevent audio playback.
    }
  }

  List<_Lyric> _parseLrc(String raw) {
    final regex = RegExp(r'\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]');
    final result = <_Lyric>[];
    for (final line in raw.split('\n')) {
      final match = regex.firstMatch(line);
      if (match == null) continue;
      final fraction = (match.group(3) ?? '0').padRight(3, '0').substring(0, 3);
      final at = Duration(
        minutes: int.parse(match.group(1)!),
        seconds: int.parse(match.group(2)!),
        milliseconds: int.parse(fraction),
      );
      final text = line.substring(match.end).trim();
      if (text.isNotEmpty) result.add(_Lyric(at, text));
    }
    return result;
  }

  Future<void> _send() async {
    final typedText = _input.text.trim();
    if ((typedText.isEmpty && _selectedLyric == null) || _sending) return;
    final text = typedText.isEmpty ? '「${_selectedLyric!.text}」' : typedText;
    _input.clear();
    setState(() {
      _sending = true;
      _chat.add(
        ChatMessage(
          role: 'user',
          content: text,
          createdAt: DateTime.now(),
          source: 'music_room',
        ),
      );
    });
    _scrollChatToBottom();
    final song = _song;
    final musicContext = song == null
        ? ''
        : '当前歌曲：${song.name} - ${song.artist}\n'
              '播放状态：${_playing ? '正在播放' : '已暂停'}\n'
              '当前进度：${_formatDuration(_position)} / ${_formatDuration(_duration)}\n'
              '${_selectedLyric == null ? '' : '用户选中的歌词：${_selectedLyric!.text}'}';
    try {
      final replies = await _api.sendMessage(
        text,
        musicContext: musicContext,
        fromMusicRoom: true,
      );
      if (mounted) {
        setState(() => _chat.addAll(replies));
        _scrollChatToBottom();
      }
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _loadMusicChat() async {
    try {
      final messages = await _api.getTodayMusicMessages();
      if (!mounted) return;
      setState(() {
        _chat
          ..clear()
          ..addAll(messages);
      });
      _scrollChatToBottom();
    } catch (_) {
      // The player remains available when chat history is temporarily offline.
    }
  }

  void _scrollChatToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_chatScroll.hasClients) return;
      _chatScroll.animateTo(
        _chatScroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 240),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _syncNowPlaying() async {
    final song = _song;
    if (song == null) return;
    try {
      await http
          .post(
            _uri('/music/now'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'song_id': song.id,
              'name': song.name,
              'artist': song.artist,
              'position': _position.inMilliseconds / 1000,
              'duration': _duration.inMilliseconds / 1000,
              'playing': _playing,
            }),
          )
          .timeout(const Duration(seconds: 5));
    } catch (_) {
      // Playback must remain usable while the optional context sync is offline.
    }
  }

  String _formatDuration(Duration value) {
    final minutes = value.inMinutes.toString().padLeft(2, '0');
    final seconds = (value.inSeconds % 60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  Future<void> _loadNicknames() async {
    final preferences = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() {
      final partner = preferences.getString('profile_libra_nickname')?.trim();
      final user = preferences.getString('profile_user_nickname')?.trim();
      _partnerNickname = partner == null || partner.isEmpty ? '左然' : partner;
      _userNickname = user == null || user.isEmpty ? '我' : user;
    });
  }

  bool _isSharedPlaylist(Map<String, dynamic> playlist) =>
      playlist['description'] == '一起收藏的歌' &&
      (playlist['name'] == '我和左然的歌单' || playlist['name'] == '我和 Libra 的歌单');

  String _playlistName(Map<String, dynamic> playlist) =>
      _isSharedPlaylist(playlist)
      ? '${_userNickname}和${_partnerNickname}的歌单'
      : '${playlist['name']}';

  Future<void> _refreshPlaylistMembership() async {
    final revision = ++_membershipRevision;
    try {
      final response = await http
          .get(_uri('/music/playlists'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode >= 400) return;
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      final lists = (data['playlists'] as List).cast<Map<String, dynamic>>();
      final memberships = await Future.wait(
        lists.map((playlist) async {
          final response = await http
              .get(_uri('/music/playlists/${playlist['id']}/songs'))
              .timeout(const Duration(seconds: 15));
          if (response.statusCode >= 400) throw Exception('歌单加载失败');
          final data = jsonDecode(utf8.decode(response.bodyBytes));
          return (data['songs'] as List).map(
            (song) => (song['id'] as num).toInt(),
          );
        }),
      );
      if (mounted && revision == _membershipRevision) {
        setState(
          () => _savedSongIds = memberships.expand((ids) => ids).toSet(),
        );
      }
    } catch (_) {
      // Keep the last known membership when the service is unavailable.
    }
  }

  Future<void> _addToPlaylist() async {
    final song = _song;
    if (song == null || _savingSong) return;
    setState(() => _savingSong = true);
    try {
      final listResponse = await http.get(_uri('/music/playlists'));
      if (listResponse.statusCode >= 400) throw Exception('歌单加载失败');
      final data = jsonDecode(utf8.decode(listResponse.bodyBytes));
      final lists = (data['playlists'] as List)
          .whereType<Map<String, dynamic>>()
          .toList();
      if (!mounted || lists.isEmpty) return;
      final chosen = lists.firstWhere(_isSharedPlaylist);
      final saveResponse = await http.post(
        _uri('/music/playlists/${chosen['id']}/songs'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'song_id': song.id,
          'name': song.name,
          'artist': song.artist,
          'cover_url': song.pic,
        }),
      );
      if (saveResponse.statusCode >= 400) throw Exception('加入歌单失败，请重试');
      if (mounted) setState(() => _savedSongIds.add(song.id));
      _refreshPlaylistMembership();
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('已加入「${_playlistName(chosen)}」')),
        );
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$error')));
    } finally {
      if (mounted) setState(() => _savingSong = false);
    }
  }

  Future<void> _openSharedPlaylists() async {
    try {
      final response = await http
          .get(_uri('/music/playlists'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode >= 400) throw Exception('歌单加载失败');
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      final lists = (data['playlists'] as List).cast<Map<String, dynamic>>();
      if (!mounted) return;
      if (lists.isEmpty) throw Exception('暂无共同歌单');
      final chosen = lists.firstWhere(
        _isSharedPlaylist,
        orElse: () => lists.first,
      );
      final songsResponse = await http
          .get(_uri('/music/playlists/${chosen['id']}/songs'))
          .timeout(const Duration(seconds: 15));
      if (songsResponse.statusCode >= 400) throw Exception('歌曲加载失败');
      final songsData = jsonDecode(utf8.decode(songsResponse.bodyBytes));
      final songs = (songsData['songs'] as List)
          .cast<Map<String, dynamic>>()
          .map(_Song.fromJson)
          .toList();
      if (!mounted) return;
      final removing = <int>{};
      final selected = await showModalBottomSheet<_Song>(
        context: context,
        backgroundColor: const Color(0xFFFFF8F7),
        builder: (sheetContext) => StatefulBuilder(
          builder: (sheetContext, updateSheet) => SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ListTile(
                  title: Text('${_playlistName(chosen)} · ${songs.length} 首'),
                  subtitle: const Text('点任意歌曲开始，整张歌单循环播放'),
                  trailing: IconButton(
                    tooltip: '循环播放全部',
                    icon: const Icon(Icons.repeat, color: _pink),
                    onPressed: songs.isEmpty
                        ? null
                        : () => Navigator.pop(sheetContext, songs.first),
                  ),
                ),
                if (songs.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(24),
                    child: Text('歌单还是空的，先搜索歌曲，再点爱心加入我们的歌单吧'),
                  ),
                Flexible(
                  child: ListView.builder(
                    shrinkWrap: true,
                    itemCount: songs.length,
                    itemBuilder: (_, index) => ListTile(
                      title: Text(songs[index].name),
                      subtitle: Text(songs[index].artist),
                      trailing: IconButton(
                        tooltip: '从歌单移除',
                        icon: const Icon(
                          Icons.remove_circle_outline,
                          color: _pink,
                        ),
                        onPressed: removing.contains(songs[index].id)
                            ? null
                            : () async {
                                final song = songs[index];
                                updateSheet(() => removing.add(song.id));
                                try {
                                  final response = await http
                                      .delete(
                                        _uri(
                                          '/music/playlists/${chosen['id']}/songs/${song.id}',
                                        ),
                                      )
                                      .timeout(const Duration(seconds: 15));
                                  if (response.statusCode >= 400)
                                    throw Exception('移除失败，请重试');
                                  await _refreshPlaylistMembership();
                                  if (sheetContext.mounted) {
                                    updateSheet(
                                      () => songs.removeWhere(
                                        (s) => s.id == song.id,
                                      ),
                                    );
                                  }
                                } catch (error) {
                                  if (mounted)
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(content: Text('$error')),
                                    );
                                } finally {
                                  if (sheetContext.mounted)
                                    updateSheet(() => removing.remove(song.id));
                                }
                              },
                      ),
                      onTap: () => Navigator.pop(sheetContext, songs[index]),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      );
      if (selected == null || !mounted) return;
      setState(() {
        _queue
          ..clear()
          ..addAll(songs);
      });
      await _play(selected);
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('打开我们的歌单失败：$error')));
    }
  }

  Future<void> _openNeteasePlaylists() async {
    try {
      final response = await http
          .get(_uri('/music/netease/playlists'))
          .timeout(const Duration(seconds: 35));
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode >= 400) {
        if (response.statusCode == 401) {
          if (mounted)
            await _showNeteaseCredentialHelp(
              '${data is Map ? data['detail'] ?? '' : ''}',
            );
          return;
        }
        throw Exception(data is Map ? data['detail'] : '网易云歌单加载失败');
      }
      final account = data is Map ? data['account'] : null;
      final values = data is Map && data['playlists'] is List
          ? (data['playlists'] as List)
                .whereType<Map<String, dynamic>>()
                .toList()
          : <Map<String, dynamic>>[];
      if (!mounted) return;
      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        isScrollControlled: true,
        backgroundColor: const Color(0xFFFFF8F7),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
        builder: (_) => SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(context).height * .72,
            child: Column(
              children: [
                ListTile(
                  leading: const CircleAvatar(
                    backgroundColor: Color(0xFFFFE3E2),
                    child: Icon(Icons.cloud_done_rounded, color: _pink),
                  ),
                  title: Text(
                    '${account is Map ? account['nickname'] : ''}的网易云歌单',
                  ),
                  subtitle: const Text('直接浏览云端歌单，不会修改网易云中的内容'),
                ),
                const Divider(height: 1),
                Expanded(
                  child: values.isEmpty
                      ? const Center(child: Text('这个账号还没有歌单'))
                      : ListView.builder(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          itemCount: values.length,
                          itemBuilder: (_, index) {
                            final playlist = values[index];
                            final cover = '${playlist['cover_url'] ?? ''}';
                            return ListTile(
                              leading: ClipRRect(
                                borderRadius: BorderRadius.circular(10),
                                child: cover.isEmpty
                                    ? const SizedBox(
                                        width: 50,
                                        height: 50,
                                        child: Icon(
                                          Icons.queue_music,
                                          color: _pink,
                                        ),
                                      )
                                    : Image.network(
                                        cover,
                                        width: 50,
                                        height: 50,
                                        fit: BoxFit.cover,
                                      ),
                              ),
                              title: Text('${playlist['name'] ?? '未命名歌单'}'),
                              subtitle: Text(
                                '${playlist['track_count'] ?? 0} 首',
                              ),
                              trailing: const Icon(
                                Icons.chevron_right,
                                color: _pink,
                              ),
                              onTap: () => Navigator.pop(context, playlist),
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      );
      if (selected != null && mounted) {
        await _openNeteasePlaylistSongs(selected);
      }
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('无法读取网易云歌单：$error')));
    }
  }

  Future<void> _showNeteaseCredentialHelp(String detail) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: const Color(0xFFFFF8F7),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        title: const Text('网易云登录需要在电脑端更新'),
        content: Text(
          detail.isEmpty
              ? '请在电脑后端的 .env 中配置 MUSIC_U，然后重启后端。手机端不会保存网易云 Cookie。'
              : '$detail\n\n请在电脑后端更新 MUSIC_U。手机端不会保存网易云 Cookie。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('知道了'),
          ),
        ],
      ),
    );
  }

  Future<void> _openNeteasePlaylistSongs(Map<String, dynamic> playlist) async {
    final playlistId = (playlist['id'] as num?)?.toInt();
    if (playlistId == null) return;
    try {
      final response = await http
          .get(_uri('/music/netease/playlists/$playlistId/songs'))
          .timeout(const Duration(minutes: 2));
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode >= 400) {
        throw Exception(data is Map ? data['detail'] : '歌曲加载失败');
      }
      final songs = data is Map && data['songs'] is List
          ? (data['songs'] as List)
                .whereType<Map<String, dynamic>>()
                .map(_Song.fromJson)
                .toList()
          : <_Song>[];
      final playableSongs = songs.where((song) => song.playable).toList();
      if (!mounted) return;
      final selected = await showModalBottomSheet<_Song>(
        context: context,
        isScrollControlled: true,
        backgroundColor: const Color(0xFFFFF8F7),
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
        ),
        builder: (_) => SafeArea(
          child: SizedBox(
            height: MediaQuery.sizeOf(context).height * .78,
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.queue_music_rounded, color: _pink),
                  title: Text('${playlist['name'] ?? '网易云歌单'}'),
                  subtitle: Text('${songs.length} 首 · 歌单循环 · 跳过灰色歌曲'),
                  trailing: IconButton(
                    tooltip: '循环播放全部',
                    icon: const Icon(Icons.repeat, color: _pink),
                    onPressed: playableSongs.isEmpty
                        ? null
                        : () => Navigator.pop(context, playableSongs.first),
                  ),
                ),
                const Divider(height: 1),
                Expanded(
                  child: songs.isEmpty
                      ? const Center(child: Text('这个歌单还没有歌曲'))
                      : ListView.separated(
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          itemCount: songs.length,
                          separatorBuilder: (_, _) =>
                              const Divider(height: 1, indent: 76),
                          itemBuilder: (_, index) {
                            final song = songs[index];
                            return ListTile(
                              enabled: song.playable,
                              leading: _SongArtwork(song: song),
                              title: Text(
                                song.name,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              subtitle: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    song.artist,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  if (!song.playable)
                                    Text(
                                      song.unavailableReason.isEmpty
                                          ? '当前没有可播放音源'
                                          : song.unavailableReason,
                                      style: const TextStyle(
                                        color: _pink,
                                        fontSize: 12,
                                      ),
                                    ),
                                ],
                              ),
                              trailing: song.playable
                                  ? const Icon(
                                      Icons.play_circle_outline,
                                      color: _pink,
                                    )
                                  : const Icon(
                                      Icons.info_outline,
                                      color: Color(0xFFAA9E9D),
                                    ),
                              onTap: song.playable
                                  ? () => Navigator.pop(context, song)
                                  : null,
                            );
                          },
                        ),
                ),
              ],
            ),
          ),
        ),
      );
      if (selected != null && mounted) {
        setState(() {
          _queue
            ..clear()
            ..addAll(playableSongs);
        });
        await _play(selected);
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('无法读取歌单歌曲：$error')));
      }
    }
  }

  Future<bool> _loginNetease() async {
    try {
      final keyResponse = await http
          .get(_uri('/music/netease/qr/key'))
          .timeout(const Duration(seconds: 20));
      final keyData = jsonDecode(utf8.decode(keyResponse.bodyBytes));
      final key = '${keyData['key'] ?? ''}';
      if (key.isEmpty) throw Exception('无法生成登录二维码');
      final qrResponse = await http
          .get(_uri('/music/netease/qr/create', {'key': key}))
          .timeout(const Duration(seconds: 20));
      final qrData = jsonDecode(utf8.decode(qrResponse.bodyBytes));
      final rawImage = '${qrData['qr_image'] ?? ''}';
      final comma = rawImage.indexOf(',');
      final bytes = base64Decode(
        comma >= 0 ? rawImage.substring(comma + 1) : rawImage,
      );
      if (!mounted) return false;
      return await showDialog<bool>(
            context: context,
            barrierDismissible: false,
            builder: (dialogContext) {
              var checking = false;
              var hint = '请用网易云音乐 App 扫码并确认登录';
              return StatefulBuilder(
                builder: (context, setDialogState) => AlertDialog(
                  backgroundColor: const Color(0xFFFFF8F7),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(24),
                  ),
                  title: const Text('连接网易云音乐'),
                  content: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(16),
                        child: Image.memory(bytes, width: 220, height: 220),
                      ),
                      const SizedBox(height: 12),
                      Text(hint, textAlign: TextAlign.center),
                    ],
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(dialogContext, false),
                      child: const Text('取消'),
                    ),
                    FilledButton(
                      onPressed: checking
                          ? null
                          : () async {
                              setDialogState(() {
                                checking = true;
                                hint = '正在确认登录…';
                              });
                              try {
                                final response = await http.get(
                                  _uri('/music/netease/qr/check', {'key': key}),
                                );
                                final result = jsonDecode(
                                  utf8.decode(response.bodyBytes),
                                );
                                if (result['code'] == 803) {
                                  if (dialogContext.mounted)
                                    Navigator.pop(dialogContext, true);
                                  return;
                                }
                                setDialogState(() {
                                  checking = false;
                                  hint = result['code'] == 800
                                      ? '二维码已过期，请关闭后重新打开'
                                      : '尚未确认，请扫码后在网易云中点击授权';
                                });
                              } catch (_) {
                                setDialogState(() {
                                  checking = false;
                                  hint = '确认失败，请稍后重试';
                                });
                              }
                            },
                      child: Text(checking ? '确认中' : '我已确认'),
                    ),
                  ],
                ),
              );
            },
          ) ??
          false;
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('网易云登录失败：$error')));
      }
      return false;
    }
  }

  Future<void> _importNeteasePlaylist(Map<String, dynamic> remote) async {
    final playlistId = (remote['id'] as num?)?.toInt();
    if (playlistId == null) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('正在导入「${remote['name']}」…')));
    try {
      final response = await http
          .post(_uri('/music/netease/playlists/$playlistId/import'))
          .timeout(const Duration(minutes: 2));
      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (response.statusCode >= 400) {
        throw Exception(data is Map ? data['detail'] : '导入失败');
      }
      final localId = (data['playlist_id'] as num).toInt();
      final songsResponse = await http.get(
        _uri('/music/playlists/$localId/songs'),
      );
      final songsData = jsonDecode(utf8.decode(songsResponse.bodyBytes));
      final songs = (songsData['songs'] as List)
          .whereType<Map<String, dynamic>>()
          .map(_Song.fromJson)
          .toList();
      if (!mounted) return;
      setState(() {
        for (final song in songs) {
          if (!_queue.any((item) => item.id == song.id)) _queue.add(song);
          _savedSongIds.add(song.id);
        }
      });
      _refreshPlaylistMembership();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('已导入 ${data['total']} 首，歌单已加入播放列表')),
      );
      if (_song == null && songs.isNotEmpty) await _play(songs.first);
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('导入歌单失败：$error')));
    }
  }

  Future<void> _openSearch() async {
    final selected = await showModalBottomSheet<_Song>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFFFFF8F7),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (_) => _MusicSearchSheet(search: _search),
    );
    if (selected != null && mounted) {
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted) return;
      if (!_queue.any((song) => song.id == selected.id)) {
        setState(() => _queue.add(selected));
      }
      await _play(selected);
    }
  }

  Future<void> _openList() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: const Color(0xFFFFF8F7),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(28)),
      ),
      builder: (_) => _MusicQueueSheet(
        queue: List<_Song>.of(_queue),
        currentSongId: _song?.id,
        onPlay: (song) async {
          Navigator.of(context).pop();
          await _play(song);
        },
        onRemove: (song) {
          final removedCurrent = _song?.id == song.id;
          setState(() {
            _queue.removeWhere((item) => item.id == song.id);
            if (removedCurrent) {
              _song = null;
              _lyrics = const [];
              _selectedLyric = null;
              _position = Duration.zero;
              _duration = Duration.zero;
            }
          });
          if (removedCurrent) _player.stop();
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    final current = _lyrics.lastWhere(
      (line) => line.at <= _position,
      orElse: () => const _Lyric(Duration.zero, '选择一首歌，和 Libra 一起听吧'),
    );
    return Scaffold(
      backgroundColor: const Color(0xFFFFF7F5),
      body: Stack(
        fit: StackFit.expand,
        children: [
          const DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Color(0xFFFFFBFA),
                  Color(0xFFFFEDEA),
                  Color(0xFFF8E4E7),
                ],
                stops: [0, .56, 1],
              ),
            ),
          ),
          const _MusicRoomBackdrop(),
          SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 6,
                  ),
                  child: Row(
                    children: [
                      IconButton(
                        onPressed: () => Navigator.pop(context),
                        icon: const Icon(
                          Icons.chevron_left,
                          color: _ink,
                          size: 32,
                        ),
                      ),
                      Expanded(
                        child: Column(
                          children: [
                            const Text(
                              '音乐室',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: _ink,
                                fontSize: 21,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Text(
                              '和${_partnerNickname}一起听歌',
                              style: const TextStyle(
                                color: Color(0xFF8E817F),
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ),
                      ),
                      _topAction('搜索', _openSearch),
                      _topAction('我们的', _openSharedPlaylists),
                      _topAction('歌单', _openNeteasePlaylists),
                    ],
                  ),
                ),
                Expanded(
                  flex: 6,
                  child: Container(
                    margin: const EdgeInsets.fromLTRB(16, 4, 16, 8),
                    padding: EdgeInsets.all(keyboardOpen ? 10 : 18),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: .55),
                      borderRadius: BorderRadius.circular(28),
                      boxShadow: [
                        BoxShadow(
                          color: _pink.withValues(alpha: .16),
                          blurRadius: 20,
                        ),
                      ],
                    ),
                    child: Column(
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    _song?.name ?? '还没有播放歌曲',
                                    style: const TextStyle(
                                      fontSize: 24,
                                      fontWeight: FontWeight.w600,
                                      color: _ink,
                                    ),
                                  ),
                                  const SizedBox(height: 5),
                                  Text(
                                    _song?.artist ?? '点击右上角「列表」搜索',
                                    style: const TextStyle(
                                      color: Color(0xFF9F9291),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            _Cover(song: _song, compact: keyboardOpen),
                          ],
                        ),
                        Slider(
                          value: _duration.inMilliseconds == 0
                              ? 0
                              : (_position.inMilliseconds /
                                        _duration.inMilliseconds)
                                    .clamp(0, 1),
                          activeColor: _pink,
                          onChanged: (v) => _player.seek(
                            Duration(
                              milliseconds: (_duration.inMilliseconds * v)
                                  .round(),
                            ),
                          ),
                        ),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                          children: [
                            IconButton(
                              onPressed: _savingSong ? null : _addToPlaylist,
                              icon: Icon(
                                _savedSongIds.contains(_song?.id)
                                    ? Icons.favorite
                                    : Icons.favorite_border,
                                color: _savedSongIds.contains(_song?.id)
                                    ? _pink
                                    : null,
                              ),
                            ),
                            IconButton(
                              onPressed: () => _skip(-1),
                              icon: const Icon(Icons.skip_previous_rounded),
                            ),
                            CircleAvatar(
                              radius: keyboardOpen ? 20 : 25,
                              backgroundColor: _pink,
                              child: IconButton(
                                onPressed: () => _playing
                                    ? _player.pause()
                                    : _player.resume(),
                                icon: Icon(
                                  _playing ? Icons.pause : Icons.play_arrow,
                                  color: Colors.white,
                                ),
                              ),
                            ),
                            IconButton(
                              onPressed: () => _skip(1),
                              icon: const Icon(Icons.skip_next_rounded),
                            ),
                            IconButton(
                              onPressed: _openList,
                              icon: const Icon(Icons.queue_music),
                            ),
                          ],
                        ),
                        SizedBox(height: keyboardOpen ? 2 : 8),
                        Expanded(
                          child: ListView.builder(
                            controller: _lyricsScroll,
                            itemCount: _lyrics.isEmpty ? 1 : _lyrics.length,
                            itemBuilder: (_, i) {
                              final line = _lyrics.isEmpty
                                  ? current
                                  : _lyrics[i];
                              final active = line == current;
                              final selected = line == _selectedLyric;
                              return GestureDetector(
                                onTap: () => setState(
                                  () => _selectedLyric = selected ? null : line,
                                ),
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 7,
                                    horizontal: 8,
                                  ),
                                  decoration: selected
                                      ? BoxDecoration(
                                          color: _pink.withValues(alpha: .13),
                                          borderRadius: BorderRadius.circular(
                                            12,
                                          ),
                                        )
                                      : null,
                                  child: Text(
                                    line.text,
                                    textAlign: TextAlign.center,
                                    style: TextStyle(
                                      color: active
                                          ? _ink
                                          : const Color(0xFFB9AAAA),
                                      fontSize: active ? 18 : 15,
                                      fontWeight: active
                                          ? FontWeight.w600
                                          : FontWeight.normal,
                                    ),
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                Expanded(
                  flex: 4,
                  child: Container(
                    margin: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: .78),
                      borderRadius: BorderRadius.circular(28),
                      border: Border.all(
                        color: Colors.white.withValues(alpha: .9),
                      ),
                      boxShadow: [
                        BoxShadow(
                          color: _pink.withValues(alpha: .12),
                          blurRadius: 22,
                          offset: const Offset(0, 8),
                        ),
                      ],
                    ),
                    child: Column(
                      children: [
                        if (_selectedLyric != null)
                          Row(
                            children: [
                              const Icon(
                                Icons.format_quote,
                                size: 18,
                                color: _pink,
                              ),
                              const SizedBox(width: 5),
                              Expanded(
                                child: Text(
                                  '带歌词聊：${_selectedLyric!.text}',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(color: _pink),
                                ),
                              ),
                              IconButton(
                                onPressed: () =>
                                    setState(() => _selectedLyric = null),
                                icon: const Icon(Icons.close, size: 17),
                              ),
                            ],
                          )
                        else
                          const Row(
                            children: [
                              CircleAvatar(
                                radius: 15,
                                backgroundColor: Color(0xFFFFE3E0),
                                child: Icon(
                                  Icons.forum_rounded,
                                  size: 16,
                                  color: _pink,
                                ),
                              ),
                              SizedBox(width: 9),
                              Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '一起聊音乐',
                                    style: TextStyle(
                                      color: _ink,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                  Text(
                                    '今天在音乐室说过的话会留在这里',
                                    style: TextStyle(
                                      color: Color(0xFF9B8B89),
                                      fontSize: 11,
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        const SizedBox(height: 8),
                        Expanded(
                          child: ListView.builder(
                            controller: _chatScroll,
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            itemCount: _chat.length,
                            itemBuilder: (_, i) {
                              final m = _chat[i];
                              final user = m.role == 'user';
                              return Align(
                                alignment: user
                                    ? Alignment.centerRight
                                    : Alignment.centerLeft,
                                child: Container(
                                  margin: const EdgeInsets.symmetric(
                                    vertical: 4,
                                  ),
                                  constraints: BoxConstraints(
                                    maxWidth:
                                        MediaQuery.sizeOf(context).width * .7,
                                  ),
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 14,
                                    vertical: 10,
                                  ),
                                  decoration: BoxDecoration(
                                    color: user
                                        ? const Color(0xFFFFDCD8)
                                        : const Color(0xFFFFFAF9),
                                    borderRadius: BorderRadius.only(
                                      topLeft: const Radius.circular(18),
                                      topRight: const Radius.circular(18),
                                      bottomLeft: Radius.circular(
                                        user ? 18 : 5,
                                      ),
                                      bottomRight: Radius.circular(
                                        user ? 5 : 18,
                                      ),
                                    ),
                                    border: Border.all(
                                      color: user
                                          ? _pink.withValues(alpha: .12)
                                          : const Color(0xFFF2E3E1),
                                    ),
                                  ),
                                  child: Text(
                                    m.content,
                                    style: const TextStyle(
                                      color: _ink,
                                      height: 1.35,
                                    ),
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
                        Row(
                          children: [
                            Expanded(
                              child: TextField(
                                controller: _input,
                                onSubmitted: (_) => _send(),
                                decoration: InputDecoration(
                                  hintText: _selectedLyric == null
                                      ? '纯聊天…'
                                      : '和这句歌词聊聊…',
                                  filled: true,
                                  fillColor: Colors.white.withValues(
                                    alpha: .82,
                                  ),
                                  contentPadding: const EdgeInsets.symmetric(
                                    horizontal: 16,
                                    vertical: 11,
                                  ),
                                  border: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(24),
                                    borderSide: BorderSide(
                                      color: _pink.withValues(alpha: .16),
                                    ),
                                  ),
                                  enabledBorder: OutlineInputBorder(
                                    borderRadius: BorderRadius.circular(24),
                                    borderSide: BorderSide(
                                      color: _pink.withValues(alpha: .16),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            CircleAvatar(
                              backgroundColor: _pink,
                              child: IconButton(
                                onPressed: _sending ? null : _send,
                                icon: _sending
                                    ? const SizedBox(
                                        width: 17,
                                        height: 17,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                          color: Colors.white,
                                        ),
                                      )
                                    : const Icon(
                                        Icons.arrow_upward,
                                        color: Colors.white,
                                      ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _topAction(String text, VoidCallback action) => Padding(
    padding: const EdgeInsets.only(left: 3),
    child: Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        onTap: action,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 7),
          child: Text(
            text,
            style: const TextStyle(
              fontSize: 11,
              color: _ink,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ),
    ),
  );

  void _skip(int delta) {
    if (_song == null || _queue.isEmpty) return;
    final index = _queue.indexWhere((s) => s.id == _song!.id);
    _play(_queue[(index + delta + _queue.length) % _queue.length]);
  }
}

class _MusicRoomBackdrop extends StatelessWidget {
  const _MusicRoomBackdrop();

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: Stack(
      children: [
        Positioned(
          top: 78,
          right: -72,
          child: Container(
            width: 220,
            height: 220,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white.withValues(alpha: .5),
            ),
          ),
        ),
        Positioned(
          left: -86,
          bottom: 110,
          child: Container(
            width: 240,
            height: 240,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: _pink.withValues(alpha: .08),
            ),
          ),
        ),
        const Positioned(
          top: 118,
          left: 26,
          child: Icon(
            Icons.music_note_rounded,
            color: Color(0x22E77E82),
            size: 42,
          ),
        ),
      ],
    ),
  );
}

class _MusicSearchSheet extends StatefulWidget {
  const _MusicSearchSheet({required this.search});

  final Future<List<_Song>> Function(String query) search;

  @override
  State<_MusicSearchSheet> createState() => _MusicSearchSheetState();
}

class _MusicSearchSheetState extends State<_MusicSearchSheet> {
  final _controller = TextEditingController();
  List<_Song> _results = const [];
  bool _loading = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _runSearch() async {
    final query = _controller.text.trim();
    if (query.isEmpty || _loading) return;
    setState(() => _loading = true);
    try {
      final results = await widget.search(query);
      if (mounted) setState(() => _results = results);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('搜索失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.fromLTRB(
      20,
      18,
      20,
      MediaQuery.viewInsetsOf(context).bottom + 20,
    ),
    child: SizedBox(
      height: MediaQuery.sizeOf(context).height * .62,
      child: Column(
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '搜索歌曲',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                ),
              ),
              IconButton(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
          TextField(
            controller: _controller,
            onSubmitted: (_) => _runSearch(),
            decoration: InputDecoration(
              hintText: '搜索歌曲或歌手',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: IconButton(
                onPressed: _runSearch,
                icon: const Icon(Icons.arrow_upward),
              ),
              filled: true,
              fillColor: Colors.white,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(22),
                borderSide: BorderSide.none,
              ),
            ),
          ),
          if (_loading) const LinearProgressIndicator(color: _pink),
          Expanded(child: ListView(children: [..._results.map(_songTile)])),
        ],
      ),
    ),
  );

  Widget _songTile(_Song song) => ListTile(
    leading: ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: song.pic.isEmpty
          ? const SizedBox(
              width: 48,
              height: 48,
              child: Icon(Icons.music_note, color: _pink),
            )
          : Image.network(
              song.pic.replaceFirst('http://', 'https://'),
              width: 48,
              height: 48,
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => const SizedBox(
                width: 48,
                height: 48,
                child: Icon(Icons.music_note, color: _pink),
              ),
            ),
    ),
    title: Text(song.name),
    subtitle: Text(song.artist),
    trailing: const Icon(Icons.play_arrow_rounded, color: _pink),
    onTap: () => Navigator.of(context).pop(song),
  );
}

class _MusicQueueSheet extends StatefulWidget {
  const _MusicQueueSheet({
    required this.queue,
    required this.currentSongId,
    required this.onPlay,
    required this.onRemove,
  });

  final List<_Song> queue;
  final int? currentSongId;
  final Future<void> Function(_Song song) onPlay;
  final ValueChanged<_Song> onRemove;

  @override
  State<_MusicQueueSheet> createState() => _MusicQueueSheetState();
}

class _MusicQueueSheetState extends State<_MusicQueueSheet> {
  late final List<_Song> _songs = List<_Song>.of(widget.queue);

  void _remove(_Song song) {
    setState(() => _songs.removeWhere((item) => item.id == song.id));
    widget.onRemove(song);
  }

  @override
  Widget build(BuildContext context) => SafeArea(
    child: SizedBox(
      height: MediaQuery.sizeOf(context).height * .62,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 12, 8),
            child: Row(
              children: [
                const Expanded(
                  child: Text(
                    '播放列表',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                  ),
                ),
                IconButton(
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
          ),
          Expanded(
            child: _songs.isEmpty
                ? const Center(
                    child: Text(
                      '还没有加入歌曲',
                      style: TextStyle(color: Color(0xFF9F9291)),
                    ),
                  )
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
                    itemCount: _songs.length,
                    separatorBuilder: (_, _) => const Divider(height: 1),
                    itemBuilder: (_, index) {
                      final song = _songs[index];
                      final current = song.id == widget.currentSongId;
                      return ListTile(
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 4,
                        ),
                        leading: _SongArtwork(song: song),
                        title: Text(
                          song.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          song.artist,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (current)
                              const Icon(Icons.equalizer_rounded, color: _pink),
                            IconButton(
                              tooltip: '移出列表',
                              onPressed: () => _remove(song),
                              icon: const Icon(
                                Icons.remove_circle_outline,
                                color: _pink,
                              ),
                            ),
                          ],
                        ),
                        onTap: () => widget.onPlay(song),
                      );
                    },
                  ),
          ),
        ],
      ),
    ),
  );
}

class _SongArtwork extends StatelessWidget {
  const _SongArtwork({required this.song});
  final _Song song;

  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(8),
    child: song.pic.isEmpty
        ? const SizedBox(
            width: 48,
            height: 48,
            child: Icon(Icons.music_note, color: _pink),
          )
        : Image.network(
            song.pic.replaceFirst('http://', 'https://'),
            width: 48,
            height: 48,
            fit: BoxFit.cover,
            errorBuilder: (_, _, _) => const SizedBox(
              width: 48,
              height: 48,
              child: Icon(Icons.music_note, color: _pink),
            ),
          ),
  );
}

class _Cover extends StatelessWidget {
  const _Cover({required this.song, this.compact = false});
  final _Song? song;
  final bool compact;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: compact ? 88 : 116,
    height: compact ? 66 : 92,
    child: Stack(
      alignment: Alignment.centerRight,
      children: [
        Container(
          width: compact ? 56 : 76,
          height: compact ? 56 : 76,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            color: Color(0xFF2E2728),
          ),
        ),
        Positioned(
          left: 0,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(18),
            child: song?.pic.isNotEmpty == true
                ? Image.network(
                    song!.pic.replaceFirst('http://', 'https://'),
                    width: compact ? 64 : 88,
                    height: compact ? 64 : 88,
                    fit: BoxFit.cover,
                    errorBuilder: (_, _, _) => Container(
                      width: compact ? 64 : 88,
                      height: compact ? 64 : 88,
                      color: const Color(0xFFFFDFDF),
                      child: const Icon(
                        Icons.music_note,
                        color: _pink,
                        size: 38,
                      ),
                    ),
                  )
                : Container(
                    width: compact ? 64 : 88,
                    height: compact ? 64 : 88,
                    color: const Color(0xFFFFDFDF),
                    child: const Icon(Icons.music_note, color: _pink, size: 38),
                  ),
          ),
        ),
      ],
    ),
  );
}

class _Song {
  const _Song(
    this.id,
    this.name,
    this.artist,
    this.pic,
    this.playUrl, {
    this.playable = true,
    this.unavailableReason = '',
  });
  final int id;
  final String name, artist, pic, playUrl;
  final bool playable;
  final String unavailableReason;
  factory _Song.fromJson(Map<String, dynamic> j) => _Song(
    (j['id'] as num).toInt(),
    '${j['name'] ?? ''}',
    '${j['artist'] ?? ''}',
    '${j['pic'] ?? ''}',
    '${j['play_url'] ?? ''}',
    playable: j['playable'] != false,
    unavailableReason: '${j['unavailable_reason'] ?? ''}',
  );
}

class _Lyric {
  const _Lyric(this.at, this.text);
  final Duration at;
  final String text;
}

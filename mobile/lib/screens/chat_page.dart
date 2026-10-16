import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:record/record.dart';
import 'package:path_provider/path_provider.dart';
import 'package:audioplayers/audioplayers.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config/api_config.dart';
import '../models/chat_message.dart';
import '../services/libra_api.dart';
import '../services/chat_sync_gate.dart';
import '../services/chat_message_merge.dart';
import '../services/push_service.dart';
import '../services/display_names.dart';
import 'call_page.dart';
import 'chat_records_page.dart';

const _background = Color(0xD9FFFAF9);
const _header = Color(0xFFF7E3E1);
const _navigation = Color(0xE6FFD6D1);
const _userBubble = Color(0xE8FFD5D0);
const _accent = Color(0xFFDE776C);
const _inactive = Color(0xFF9DAAAD);

enum _ReplyMode { auto, voice, text }

extension on _ReplyMode {
  String get label => switch (this) {
    _ReplyMode.auto => '自行决定',
    _ReplyMode.voice => '语音回复',
    _ReplyMode.text => '文字回复',
  };

  IconData get icon => switch (this) {
    _ReplyMode.auto => Icons.auto_awesome_rounded,
    _ReplyMode.voice => Icons.graphic_eq_rounded,
    _ReplyMode.text => Icons.chat_bubble_outline_rounded,
  };
}

class ChatPage extends StatefulWidget {
  const ChatPage({
    super.key,
    required this.deviceContextEnabled,
    required this.onAssistantMessagesReceived,
    required this.refreshToken,
    required this.libraStatus,
    this.libraAvatarPath,
    this.userAvatarPath,
    this.api,
  });

  final bool deviceContextEnabled;
  final ValueChanged<int> onAssistantMessagesReceived;
  final int refreshToken;
  final String libraStatus;
  final String? libraAvatarPath;
  final String? userAvatarPath;
  final LibraApi? api;

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> with WidgetsBindingObserver {
  late final _api = widget.api ?? LibraApi();
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final _imagePicker = ImagePicker();
  final _audioRecorder = AudioRecorder();
  final List<ChatMessage> _messages = [];
  bool _loadingHistory = true;
  final _syncGate = ChatSyncGate();
  bool _sending = false;
  bool _serverReplyPending = false;
  bool _checkingReplyStatus = false;
  String? _activeSendRequestId;
  String? _sendErrorRequestId;
  ChatMessage? _unconfirmedMessage;
  bool _deliveryConfirmed = false;
  String? _sendImagePath;
  static const _sendErrorText = '暂未确认发送结果，正在自动同步，请检查网络连接。';
  bool get _replyPending => _sending || _serverReplyPending;
  String? _pendingImagePath;
  ChatMessage? _pendingImageMessage;
  XhsCardData? _pendingXhsCard;
  String? _pendingXhsUrl;
  bool _loadingXhsPreview = false;
  String? _xhsPreviewError;
  Timer? _xhsPreviewDebounce;
  bool _changingComposerForXhs = false;
  String _lastComposerText = '';
  String _xhsComposerBeforePaste = '';
  String _xhsDetectedComposerText = '';
  bool _showMoreActions = false;
  bool _showStickerPanel = false;
  bool _loadingStickers = false;
  List<StickerCatalogItem> _stickers = const [];
  String? _error;
  String? _historyError;
  Timer? _updateTimer;
  int _lastMessageId = 0;
  bool _voiceMode = false;
  _ReplyMode _replyMode = _ReplyMode.auto;
  bool _recording = false;
  bool _startingRecording = false;
  DateTime? _recordingStartedAt;
  Timer? _recordingTimer;
  int _recordingSeconds = 0;
  bool _sleeping = false;
  bool _changingSleepState = false;
  bool _appActive = true;
  bool _updatesInProgress = false;
  bool _showUpdateProgress = false;
  int _updatesGeneration = 0;
  bool _updatesRequested = false;
  bool _pendingForceScroll = false;
  DateTime _loadedMessageDay = DateUtils.dateOnly(DateTime.now());

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    PushService.instance.chatMessageReceived.addListener(_onPushMessage);
    _controller.addListener(_handleComposerChanged);
    _loadMessages();
    _refreshReplyStatus();
    _refreshSleepStatus();
    _updateTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (!_appActive) return;
      _refreshReplyStatus();
      final today = DateUtils.dateOnly(DateTime.now());
      if (today != _loadedMessageDay) {
        _loadedMessageDay = today;
        _loadMessages();
      } else {
        _loadProactiveUpdates();
      }
    });
  }

  void _onPushMessage() {
    _loadProactiveUpdates(forceScroll: true);
  }

  @override
  void didUpdateWidget(covariant ChatPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken) {
      _loadProactiveUpdates(forceScroll: true);
      _scrollToBottom(retryAfterLayout: true);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final wasActive = _appActive;
    _appActive = state == AppLifecycleState.resumed;
    if (_appActive && !wasActive) {
      // A request suspended in the background must not block a fresh fetch.
      // Its late response/finally block no longer owns the current sync.
      _updatesGeneration++;
      _updatesInProgress = false;
      _updatesRequested = false;
      _pendingForceScroll = false;
      _refreshReplyStatus();
      _loadProactiveUpdates(forceScroll: true);
    }
  }

  @override
  void didChangeMetrics() {
    _scrollToBottom();
  }

  void _handleInputTap() {
    if (_showMoreActions || _showStickerPanel) {
      setState(() {
        _showMoreActions = false;
        _showStickerPanel = false;
      });
    }
    _scrollToBottom();
    Future<void>.delayed(const Duration(milliseconds: 320), () {
      if (mounted) _scrollToBottom();
    });
  }

  void _handleComposerChanged() {
    final currentText = _controller.text;
    final previousText = _lastComposerText;
    _lastComposerText = currentText;
    if (_changingComposerForXhs || _sending) return;
    final match = RegExp(
      r'''https?://(?:www\.)?(?:xiaohongshu\.com|xhslink\.com|xhslink\.cn)/[^\s<>\]\["'，。！？、；：]+''',
      caseSensitive: false,
    ).firstMatch(currentText);
    if (match == null) {
      if (_pendingXhsCard == null && _loadingXhsPreview) {
        _xhsPreviewDebounce?.cancel();
        setState(() {
          _loadingXhsPreview = false;
          _pendingXhsUrl = null;
        });
      }
      return;
    }
    final url = match.group(0)!;
    if (url == _pendingXhsUrl) return;
    _xhsPreviewDebounce?.cancel();
    setState(() {
      _xhsComposerBeforePaste = previousText;
      _xhsDetectedComposerText = currentText;
      _pendingXhsUrl = url;
      _pendingXhsCard = null;
      _loadingXhsPreview = true;
      _xhsPreviewError = null;
    });
    _xhsPreviewDebounce = Timer(const Duration(milliseconds: 450), () {
      _loadXhsPreview(url);
    });
  }

  Future<void> _loadXhsPreview(String url) async {
    try {
      final preview = await _api.getXhsPreview(url);
      if (!mounted || _pendingXhsUrl != url) return;
      final current = _controller.text;
      final remaining = current.startsWith(_xhsDetectedComposerText)
          ? '$_xhsComposerBeforePaste${current.substring(_xhsDetectedComposerText.length)}'
                .trim()
          : current.replaceFirst(url, '').trim();
      _changingComposerForXhs = true;
      _controller.value = TextEditingValue(
        text: remaining,
        selection: TextSelection.collapsed(offset: remaining.length),
      );
      _lastComposerText = remaining;
      _changingComposerForXhs = false;
      setState(() {
        _pendingXhsCard = preview;
        _loadingXhsPreview = false;
        _xhsPreviewError = null;
      });
    } catch (_) {
      if (!mounted || _pendingXhsUrl != url) return;
      setState(() {
        _loadingXhsPreview = false;
        _xhsPreviewError = '暂时无法读取这篇小红书笔记';
      });
    }
  }

  void _clearXhsPreview() {
    _xhsPreviewDebounce?.cancel();
    setState(() {
      _pendingXhsCard = null;
      _pendingXhsUrl = null;
      _loadingXhsPreview = false;
      _xhsPreviewError = null;
      _xhsComposerBeforePaste = '';
      _xhsDetectedComposerText = '';
    });
  }

  Future<void> _loadMessages() async {
    if (!mounted || !_syncGate.beginHistory(DateTime.now())) return;
    var succeeded = false;
    setState(() {
      _loadingHistory = true;
      _historyError = null;
    });
    try {
      final messages = await _api.getMessagesForDate(DateTime.now());
      final newestFetched = messages.fold<int>(
        0,
        (last, message) => (message.id ?? 0) > last ? message.id! : last,
      );
      // Preserve messages sent while the history request was in flight.
      messages.addAll(
        _messages.where(
          (message) =>
              (message.id == null &&
                  !messages.any(message.matchesPendingUserCopy)) ||
              (message.id != null && message.id! > newestFetched),
        ),
      );
      messages.sort(_compareMessages);
      if (!mounted) return;
      setState(
        () => _messages
          ..clear()
          ..addAll(messages),
      );
      // Only a history/update fetch proves all earlier IDs have been read.
      _lastMessageId = newestFetched;
      succeeded = true;
      _historyError = null;
      _reconcileSendConfirmation();
    } catch (_) {
      if (!mounted) return;
      setState(() => _historyError = '聊天记录加载失败，将自动重试');
    } finally {
      _syncGate.finishHistory(success: succeeded, now: DateTime.now());
      if (mounted) {
        setState(() => _loadingHistory = false);
        _scrollToBottom(retryAfterLayout: true);
      }
    }
  }

  Future<void> _send() async {
    final text = _controller.text.trim();
    final pendingXhsCard = _pendingXhsCard;
    if ((text.isEmpty && pendingXhsCard == null) || _replyPending) return;
    final pendingImagePath = _pendingImagePath;
    final pendingImageMessage = _pendingImageMessage;
    final optimisticType = pendingXhsCard == null ? 'text' : 'xhs_card';
    String? retryRequestId;
    for (final message in _messages.reversed) {
      final createdAt = message.createdAt;
      if (message.isUser &&
          message.id == null &&
          message.content == text &&
          message.messageType == optimisticType &&
          message.xhsCard?.url == pendingXhsCard?.url &&
          message.requestId != null &&
          (createdAt == null ||
              DateTime.now().difference(createdAt).abs() <
                  const Duration(minutes: 10))) {
        retryRequestId = message.requestId;
        break;
      }
    }
    final requestId =
        retryRequestId ?? 'chat_${DateTime.now().microsecondsSinceEpoch}';
    _sendErrorRequestId = null;
    final optimisticText = pendingXhsCard == null
        ? ChatMessage(
            role: 'user',
            content: text,
            createdAt: DateTime.now(),
            requestId: requestId,
          )
        : ChatMessage(
            role: 'user',
            content: text,
            messageType: 'xhs_card',
            xhsCard: pendingXhsCard.withComment(text),
            createdAt: DateTime.now(),
            requestId: requestId,
          );
    _controller.clear();
    _unconfirmedMessage = optimisticText;
    _deliveryConfirmed = false;
    _sendImagePath = pendingImagePath;
    setState(() {
      _sending = true;
      _activeSendRequestId = requestId;
      _error = null;
      _pendingXhsCard = null;
      _pendingXhsUrl = null;
      _xhsPreviewError = null;
      // A request may have reached the backend even when the previous HTTP
      // connection timed out. Retrying the same text must not leave another
      // unpersisted bubble beside the server copy.
      _messages.removeWhere((message) {
        if (!message.isUser || message.id != null) return false;
        if (message.content != optimisticText.content ||
            message.messageType != optimisticText.messageType ||
            message.xhsCard?.url != optimisticText.xhsCard?.url) {
          return false;
        }
        final createdAt = message.createdAt;
        return createdAt == null ||
            DateTime.now().difference(createdAt).abs() <
                const Duration(minutes: 10);
      });
      _messages.add(optimisticText);
    });
    _scrollToBottom();
    try {
      late final List<ChatMessage> replies;
      if (pendingImagePath != null && pendingImageMessage != null) {
        final result = await _api.sendImageWithCaption(
          pendingImagePath,
          text,
          requestId: requestId,
          deviceContextEnabled: widget.deviceContextEnabled,
          replyMode: _replyMode.name,
        );
        replies = result.replies;
        if (!mounted) return;
        setState(() {
          mergeUploadedMessage(_messages, pendingImageMessage, result.message);
          _pendingImagePath = null;
          _pendingImageMessage = null;
          if (!result.replySuccess) {
            _error = '图片已发送，但暂时未能回复，请稍后再聊。';
          }
        });
      } else {
        replies = await _api.sendMessage(
          text,
          requestId: requestId,
          deviceContextEnabled: widget.deviceContextEnabled,
          replyMode: _replyMode.name,
          xhsAttachment: pendingXhsCard,
        );
      }
      if (!mounted || _activeSendRequestId != requestId) return;
      _unconfirmedMessage = null;
      _deliveryConfirmed = true;
      for (var index = 0; index < replies.length; index++) {
        if (index > 0) {
          await Future<void>.delayed(const Duration(milliseconds: 650));
        }
        if (!mounted || _activeSendRequestId != requestId) return;
        if (replies[index].id != null &&
            _messages.any((message) => message.id == replies[index].id)) {
          continue;
        }
        setState(() => _messages.add(replies[index]));
        widget.onAssistantMessagesReceived(1);
        _scrollToBottom();
      }
      if (text.contains('晚安') || text.toLowerCase().contains('good night')) {
        await _refreshSleepStatus();
      }
    } catch (error) {
      if (!mounted || _activeSendRequestId != requestId) return;
      // A broken mobile connection does not cancel the accepted backend turn.
      try {
        final status = await _api.getChatStatus(requestId: requestId);
        if (!mounted || _activeSendRequestId != requestId) return;
        final completed =
            status['reply_messages'] is List &&
            (status['reply_messages'] as List).isNotEmpty;
        setState(() => _serverReplyPending = status['pending'] == true);
        if (status['accepted'] == true || completed) {
          _confirmSendDelivery();
          if (error is ChatReplyException && !completed) {
            setState(() => _error = '消息已发送，但暂时未能回复，请稍后再聊。');
          }
          await _loadProactiveUpdates(forceScroll: true);
          return;
        }
      } catch (_) {
        // Status polling resumes with the app/network; do not resend here.
      }
      if (!mounted) return;
      // Polling can confirm delivery before the original HTTP request fails.
      if (_reconcileSendConfirmation()) {
        if (error is ChatReplyException) {
          setState(() => _error = '消息已发送，但暂时未能回复，请稍后再聊。');
        }
        return;
      }
      setState(() {
        _sendErrorRequestId = requestId;
        _error = _sendErrorText;
      });
    } finally {
      if (mounted && _activeSendRequestId == requestId) {
        setState(() => _sending = false);
        _scrollToBottom();
      }
    }
  }

  Future<void> _startRecording() async {
    if (_replyPending || _recording || _startingRecording || _sleeping) return;
    _startingRecording = true;
    try {
      if (!await _audioRecorder.hasPermission()) {
        if (mounted) setState(() => _error = '请允许麦克风权限后再发送语音');
        return;
      }
      final directory = await getTemporaryDirectory();
      final path =
          '${directory.path}/libra_${DateTime.now().millisecondsSinceEpoch}.wav';
      await _audioRecorder.start(
        const RecordConfig(
          encoder: AudioEncoder.wav,
          sampleRate: 16000,
          numChannels: 1,
        ),
        path: path,
      );
      if (!mounted) return;
      setState(() {
        _recording = true;
        _recordingStartedAt = DateTime.now();
        _recordingSeconds = 0;
        _error = null;
      });
      HapticFeedback.mediumImpact();
      _recordingTimer?.cancel();
      _xhsPreviewDebounce?.cancel();
      _recordingTimer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() => _recordingSeconds++);
      });
    } catch (_) {
      if (mounted) setState(() => _error = '无法开始录音，请检查麦克风权限后重试。');
    } finally {
      _startingRecording = false;
    }
  }

  Future<void> _stopAndSendRecording() async {
    if (!_recording) return;
    setState(() => _recording = false);
    HapticFeedback.lightImpact();
    _recordingTimer?.cancel();
    final String? path;
    try {
      path = await _audioRecorder.stop();
    } catch (_) {
      if (mounted) setState(() => _error = '录音保存失败，请重新录制。');
      return;
    }
    final elapsed = DateTime.now().difference(_recordingStartedAt!).inSeconds;
    final duration = elapsed.clamp(1, 300);
    if (!mounted) return;
    setState(() => _recording = false);
    if (path == null) return;
    final optimistic = ChatMessage(
      role: 'user',
      content: '[语音]（分析中）',
      createdAt: DateTime.now(),
      messageType: 'voice',
      localFilePath: path,
      durationSeconds: duration,
    );
    setState(() {
      _sending = true;
      _activeSendRequestId = null;
      _error = null;
      _messages.add(optimistic);
    });
    _scrollToBottom();
    try {
      final result = await _api.uploadVoice(
        path,
        duration,
        deviceContextEnabled: widget.deviceContextEnabled,
        replyMode: _replyMode.name,
      );
      if (!mounted) return;
      setState(() {
        mergeUploadedMessage(_messages, optimistic, result.message);
        if (!result.replySuccess) {
          _error = '语音已发送，但暂时未能回复，请稍后再聊。';
        }
      });
      for (final reply in result.replies) {
        await Future<void>.delayed(const Duration(milliseconds: 650));
        if (!mounted) return;
        if (reply.id != null && _messages.any((m) => m.id == reply.id)) {
          continue;
        }
        setState(() => _messages.add(reply));
        widget.onAssistantMessagesReceived(1);
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _messages.remove(optimistic);
          _error = '暂未确认语音发送结果，请先同步消息后再决定是否重发。';
        });
        await _loadProactiveUpdates(forceScroll: true);
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _scrollToBottom({bool retryAfterLayout = false}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
    });
    if (retryAfterLayout) {
      Future<void>.delayed(const Duration(milliseconds: 120), () {
        if (!mounted || !_scrollController.hasClients) return;
        _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
      });
    }
  }

  bool _reconcileSendConfirmation([List<ChatMessage> updates = const []]) {
    final pending = _unconfirmedMessage;
    if (pending == null) return _deliveryConfirmed;
    final confirmed = [..._messages, ...updates].any(
      (message) =>
          message.confirmsDeliveryOf(pending.requestId) ||
          pending.matchesPendingUserCopy(message),
    );
    if (!confirmed) return _deliveryConfirmed;
    _confirmSendDelivery();
    return true;
  }

  void _confirmSendDelivery() {
    setState(() {
      _deliveryConfirmed = true;
      _unconfirmedMessage = null;
      _sendErrorRequestId = null;
      if (_error == _sendErrorText) _error = null;
      // The caption is accepted only after its image has been saved.
      if (_sendImagePath != null && _pendingImagePath == _sendImagePath) {
        _pendingImagePath = null;
        _pendingImageMessage = null;
      }
    });
  }

  Future<void> _loadProactiveUpdates({bool forceScroll = false}) async {
    if (!mounted) return;
    if (!_syncGate.ready || _syncGate.loading) {
      // Never poll from the initial zero cursor after a failed/slow bootstrap.
      await _loadMessages();
      return;
    }
    // The uploaded copy can become visible to polling just before the upload
    // request returns. Keep the optimistic local image stable until it can be
    // replaced with that persisted message.
    if (_updatesInProgress) {
      // Timer ticks are redundant while a fetch is in flight. Queuing every
      // tick makes slow requests run back-to-back indefinitely.
      if (!forceScroll) return;
      setState(() => _showUpdateProgress = true);
      _updatesRequested = true;
      _pendingForceScroll = _pendingForceScroll || forceScroll;
      return;
    }
    setState(() {
      _updatesInProgress = true;
      _showUpdateProgress = forceScroll;
    });
    final generation = _updatesGeneration;
    try {
      var shouldForceScroll = forceScroll;
      do {
        _updatesRequested = false;
        shouldForceScroll = shouldForceScroll || _pendingForceScroll;
        _pendingForceScroll = false;
        final revision = _syncGate.revision;
        if (shouldForceScroll) unawaited(_refreshSleepStatus());
        if (!_syncGate.acceptsUpdates(revision)) break;
        final updates = await _api.getMessageUpdates(_lastMessageId);
        if (!mounted || generation != _updatesGeneration) return;
        if (!_syncGate.acceptsUpdates(revision)) break;
        // The visible refresh is complete once its messages have arrived.
        // Any follow-up polling should not keep the header spinning.
        setState(() => _showUpdateProgress = false);

        // Delivery confirmation does not depend on the reply-status endpoint.
        // Check even duplicate updates: the bubble may already be reconciled.
        _reconcileSendConfirmation(updates);

        final newMessages = <ChatMessage>[];
        var replacedOptimisticMessage = false;
        for (final message in updates) {
          if (message.id != null && message.id! > _lastMessageId) {
            _lastMessageId = message.id!;
          }
          if (_messages.any((existing) => existing.id == message.id)) continue;
          if (message.isUser) {
            final optimisticIndexes = <int>[];
            for (var index = 0; index < _messages.length; index++) {
              if (_messages[index].matchesPendingUserCopy(message)) {
                optimisticIndexes.add(index);
              }
            }
            if (optimisticIndexes.isNotEmpty) {
              // Keep one position stable, remove any stale retry bubbles, and
              // perform the mutation inside setState below.
              final keepIndex = optimisticIndexes.last;
              for (final index in optimisticIndexes.reversed) {
                if (index != keepIndex) _messages.removeAt(index);
              }
              final adjustedIndex = keepIndex - (optimisticIndexes.length - 1);
              _messages[adjustedIndex] = message;
              replacedOptimisticMessage = true;
              continue;
            }
          }
          newMessages.add(message);
        }

        if (newMessages.isNotEmpty || replacedOptimisticMessage) {
          setState(() {
            _messages.addAll(newMessages);
            _messages.sort(_compareMessages);
          });
          final assistantCount = newMessages
              .where((message) => !message.isUser)
              .length;
          if (assistantCount > 0) {
            widget.onAssistantMessagesReceived(assistantCount);
          }
          _scrollToBottom(retryAfterLayout: true);
        } else if (shouldForceScroll) {
          _scrollToBottom(retryAfterLayout: true);
        }
        shouldForceScroll = false;
      } while (_updatesRequested && mounted);
    } catch (_) {
      // Proactive polling should not interrupt an active chat.
    } finally {
      if (mounted && generation == _updatesGeneration) {
        setState(() {
          _updatesInProgress = false;
          _showUpdateProgress = false;
        });
      }
    }
  }

  Future<void> _refreshReplyStatus() async {
    if (_checkingReplyStatus) return;
    _checkingReplyStatus = true;
    try {
      final failedRequestId = _sendErrorRequestId;
      final activeRequestId = _activeSendRequestId;
      final statusRequestId = activeRequestId ?? failedRequestId;
      final status = await _api.getChatStatus(requestId: statusRequestId);
      if (!mounted) return;
      if (activeRequestId != _activeSendRequestId) return;
      final completed =
          statusRequestId != null &&
          status['reply_messages'] is List &&
          (status['reply_messages'] as List).isNotEmpty;
      final completedActiveSend =
          completed && _sending && statusRequestId == _activeSendRequestId;
      final recovered =
          failedRequestId != null &&
          statusRequestId == failedRequestId &&
          failedRequestId == _sendErrorRequestId &&
          (status['accepted'] == true ||
              (status['reply_messages'] is List &&
                  (status['reply_messages'] as List).isNotEmpty));
      final wasPending = _serverReplyPending;
      setState(() {
        _serverReplyPending = !completed && status['pending'] == true;
        if (completed && statusRequestId == _activeSendRequestId) {
          _sending = false;
        }
        if (recovered && _error == _sendErrorText) {
          _error = null;
        }
      });
      if (recovered || completedActiveSend) _confirmSendDelivery();
      if (completedActiveSend ||
          recovered ||
          (wasPending && !_serverReplyPending)) {
        await _loadProactiveUpdates(forceScroll: true);
      }
    } catch (_) {
      // A transient disconnect must not turn a known active reply into idle.
    } finally {
      _checkingReplyStatus = false;
    }
  }

  Future<void> _refreshSleepStatus() async {
    try {
      final status = await _api.getSleepStatus();
      if (!mounted) return;
      setState(() {
        _sleeping = status.sleeping;
      });
    } catch (_) {
      // Message loading already reports connection failures when needed.
    }
  }

  static int _compareMessages(ChatMessage left, ChatMessage right) {
    final leftTime = left.createdAt;
    final rightTime = right.createdAt;
    if (leftTime != null && rightTime != null) {
      final byTime = leftTime.compareTo(rightTime);
      if (byTime != 0) return byTime;
    } else if (leftTime == null && rightTime != null) {
      return 1;
    } else if (leftTime != null && rightTime == null) {
      return -1;
    }
    return (left.id ?? 1 << 62).compareTo(right.id ?? 1 << 62);
  }

  Future<void> _wakeLibra() async {
    if (_changingSleepState) return;
    setState(() {
      _changingSleepState = true;
      _error = null;
    });
    try {
      final status = await _api.wakeLibra();
      if (!mounted) return;
      setState(() {
        _sleeping = status.sleeping;
      });
    } catch (_) {
      if (mounted) setState(() => _error = '暂时无法唤醒 Libra，请检查后端连接');
    } finally {
      if (mounted) setState(() => _changingSleepState = false);
    }
  }

  void _toggleSleepState() {
    if (_sleeping) {
      _wakeLibra();
    }
  }

  Future<void> _startCall() async {
    if (_sleeping) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _showMoreActions = false;
      _showStickerPanel = false;
    });
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) =>
            CallPage(deviceContextEnabled: widget.deviceContextEnabled),
      ),
    );
    if (mounted) await _loadMessages();
  }

  Future<void> _pickAndSendImage() async {
    if (_sending || _pendingImagePath != null || _sleeping) return;
    try {
      final image = await _imagePicker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 88,
        maxWidth: 2048,
      );
      if (image == null || !mounted) return;
      final optimisticMessage = ChatMessage(
        role: 'user',
        content: '[图片]',
        createdAt: DateTime.now(),
        messageType: 'image',
        localFilePath: image.path,
      );
      setState(() {
        _showMoreActions = false;
        _error = null;
        _pendingImagePath = image.path;
        _pendingImageMessage = optimisticMessage;
        _messages.add(optimisticMessage);
      });
      _scrollToBottom();
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = '图片发送失败，请稍后重试。';
        });
      }
    }
  }

  Future<void> _takeAndSendPhoto() async {
    if (_sending || _pendingImagePath != null || _sleeping) return;
    try {
      final image = await _imagePicker.pickImage(
        source: ImageSource.camera,
        imageQuality: 88,
        maxWidth: 2048,
      );
      if (image == null || !mounted) return;
      final optimisticMessage = ChatMessage(
        role: 'user',
        content: '[图片]',
        createdAt: DateTime.now(),
        messageType: 'image',
        localFilePath: image.path,
      );
      setState(() {
        _showMoreActions = false;
        _error = null;
        _pendingImagePath = image.path;
        _pendingImageMessage = optimisticMessage;
        _messages.add(optimisticMessage);
      });
      _scrollToBottom();
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = '照片发送失败，请检查相机权限后重试。';
        });
      }
    }
  }

  Future<void> _loadStickerCatalog() async {
    if (_loadingStickers) return;
    setState(() => _loadingStickers = true);
    try {
      final stickers = await _api.getStickerCatalog();
      if (mounted) setState(() => _stickers = stickers);
    } catch (_) {
      if (mounted) setState(() => _error = '表情包加载失败，请检查后端连接。');
    } finally {
      if (mounted) setState(() => _loadingStickers = false);
    }
  }

  Future<void> _sendSticker(StickerCatalogItem sticker) async {
    if (_replyPending || _sleeping) return;
    final optimisticMessage = ChatMessage(
      role: 'user',
      content: '[表情]',
      createdAt: DateTime.now(),
      messageType: 'sticker',
      mediaUrl: sticker.mediaUrl,
    );
    try {
      setState(() {
        _sending = true;
        _activeSendRequestId = null;
        _showMoreActions = false;
        _showStickerPanel = false;
        _error = null;
        _messages.add(optimisticMessage);
      });
      _scrollToBottom();
      final response = await http
          .get(Uri.parse('${ApiConfig.baseUrl}${sticker.mediaUrl}'))
          .timeout(const Duration(seconds: 20));
      if (response.statusCode != 200) {
        throw Exception('无法读取表情包');
      }
      final bytes = response.bodyBytes;
      final filename = Uri.decodeComponent(sticker.mediaUrl.split('/').last);
      final result = await _api.uploadSticker(
        bytes,
        filename,
        replyMode: _replyMode.name,
      );
      if (!mounted) return;
      setState(() {
        mergeUploadedMessage(_messages, optimisticMessage, result.message);
        if (!result.replySuccess) {
          _error = '表情已发送，但她暂时未能回复，请稍后再聊。';
        }
      });
      _scrollToBottom();
      for (final reply in result.replies) {
        await Future<void>.delayed(const Duration(milliseconds: 650));
        if (!mounted) return;
        if (reply.id != null && _messages.any((m) => m.id == reply.id)) {
          continue;
        }
        setState(() => _messages.add(reply));
        widget.onAssistantMessagesReceived(1);
        _scrollToBottom();
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _messages.remove(optimisticMessage);
          _error = '暂未确认表情发送结果，请先同步消息后再决定是否重发。';
        });
        await _loadProactiveUpdates(forceScroll: true);
      }
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _chooseFavorite(
    ChatMessage message,
    Offset globalPosition,
  ) async {
    final messageId = message.id;
    if (message.isUser || messageId == null) return;
    final overlay = Overlay.of(context).context.findRenderObject() as RenderBox;
    final favorite = await showMenu<bool>(
      context: context,
      color: const Color(0xFFFFFAF9),
      constraints: const BoxConstraints(minWidth: 86, maxWidth: 108),
      menuPadding: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
      position: RelativeRect.fromRect(
        Rect.fromLTWH(globalPosition.dx, globalPosition.dy, 1, 1),
        Offset.zero & overlay.size,
      ),
      items: [
        PopupMenuItem<bool>(
          value: !message.favorite,
          height: 42,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          child: Center(
            child: Text(
              message.favorite ? '取消收藏' : '收藏',
              maxLines: 1,
              style: const TextStyle(fontSize: 14, color: Color(0xFF795B57)),
            ),
          ),
        ),
      ],
    );
    if (favorite == null || !mounted) return;
    try {
      await _api.setMessageFavorite(messageId, favorite);
      if (!mounted) return;
      setState(() {
        final index = _messages.indexWhere((item) => item.id == messageId);
        if (index >= 0) {
          _messages[index] = _messages[index].copyWith(favorite: favorite);
        }
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(favorite ? '已收藏' : '已取消收藏')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('收藏操作失败，请稍后重试')));
    }
  }

  void _openSearch() {
    Navigator.of(
      context,
    ).push(MaterialPageRoute<void>(builder: (_) => const ChatSearchPage()));
  }

  void _openKeywordSearch() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const ChatKeywordSearchPage()),
    );
  }

  void _openFavorites() {
    Navigator.of(context).push(
      MaterialPageRoute<void>(builder: (_) => const FavoriteMessagesPage()),
    );
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    PushService.instance.chatMessageReceived.removeListener(_onPushMessage);
    _api.close();
    _updateTimer?.cancel();
    _recordingTimer?.cancel();
    _audioRecorder.dispose();
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return _buildChat();
  }

  Widget _buildChat() {
    final scale = (MediaQuery.sizeOf(context).width / 389).clamp(0.82, 1.0);
    return Stack(
      children: [
        Column(
          children: [
            _ChatHeader(
              scale: scale,
              sleeping: _sleeping,
              status: widget.libraStatus,
              syncing: _loadingHistory || _showUpdateProgress,
              changing: _changingSleepState,
              onToggleSleep: _toggleSleepState,
              onSearch: _openSearch,
              onKeywordSearch: _openKeywordSearch,
              onFavorites: _openFavorites,
            ),
            if (_historyError != null || _error != null)
              _ErrorBanner(
                message: _historyError ?? _error!,
                onRetry: _loadMessages,
              ),
            Expanded(
              child: ColoredBox(
                color: const Color(0xFFFFFAF9).withValues(alpha: .55),
                child: _buildMessages(scale),
              ),
            ),
            if (_replyPending)
              ColoredBox(
                color: const Color(0xFFFFFAF9).withValues(alpha: .55),
                child: Padding(
                  padding: EdgeInsets.only(left: 62 * scale, bottom: 4 * scale),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      '${DisplayNames.libra}正在回复…',
                      style: TextStyle(
                        color: Colors.black45,
                        fontSize: 14 * scale,
                      ),
                    ),
                  ),
                ),
              ),
            _buildComposer(scale),
          ],
        ),
        if (_recording)
          Positioned.fill(
            child: IgnorePointer(
              child: _RecordingOverlay(
                seconds: _recordingSeconds,
                scale: scale,
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildComposer(double scale) => _Composer(
    controller: _controller,
    enabled: !_replyPending,
    onSend: _send,
    onInputTap: _handleInputTap,
    replyMode: _replyMode,
    onReplyModeChanged: (mode) => setState(() => _replyMode = mode),
    voiceMode: _voiceMode,
    recording: _recording,
    recordingSeconds: _recordingSeconds,
    onToggleVoice: () {
      if (_sleeping) return;
      FocusScope.of(context).unfocus();
      setState(() {
        _voiceMode = !_voiceMode;
        _showMoreActions = false;
        _showStickerPanel = false;
      });
    },
    onRecordStart: _startRecording,
    onRecordEnd: _stopAndSendRecording,
    showMoreActions: _showMoreActions,
    onToggleMore: () {
      if (_sleeping) return;
      FocusScope.of(context).unfocus();
      final opening = !_showMoreActions;
      setState(() {
        _showMoreActions = opening;
        _showStickerPanel = false;
      });
      if (opening) {
        _scrollToBottom(retryAfterLayout: true);
        Future<void>.delayed(const Duration(milliseconds: 260), () {
          if (mounted) _scrollToBottom();
        });
      }
    },
    showStickerPanel: _showStickerPanel,
    onShowStickers: () {
      setState(() => _showStickerPanel = true);
      _loadStickerCatalog();
      _scrollToBottom(retryAfterLayout: true);
      Future<void>.delayed(const Duration(milliseconds: 260), () {
        if (mounted) _scrollToBottom();
      });
    },
    onSendSticker: _sendSticker,
    stickers: _stickers,
    loadingStickers: _loadingStickers,
    onPickImage: _pickAndSendImage,
    onTakePhoto: _takeAndSendPhoto,
    onStartCall: _startCall,
    xhsCard: _pendingXhsCard,
    loadingXhsPreview: _loadingXhsPreview,
    xhsPreviewError: _xhsPreviewError,
    onClearXhsPreview: _clearXhsPreview,
    scale: scale,
  );

  Widget _buildMessages(double scale) {
    if (_loadingHistory) {
      return const Center(child: CircularProgressIndicator(color: _accent));
    }
    if (_messages.isEmpty) {
      return Center(
        child: Text(
          '给${DisplayNames.libra}发一条消息吧',
          style: TextStyle(color: Colors.black45, fontSize: 14 * scale),
        ),
      );
    }
    return ListView.builder(
      controller: _scrollController,
      keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
      padding: EdgeInsets.fromLTRB(
        16 * scale,
        20 * scale,
        16 * scale,
        12 * scale,
      ),
      itemCount: _messages.length,
      itemBuilder: (context, index) {
        final message = _messages[index];
        final showTime = _shouldShowTime(index);
        return Column(
          children: [
            if (showTime && message.createdAt != null)
              _MessageTime(time: message.createdAt!, scale: scale),
            _MessageBubble(
              message: message,
              scale: scale,
              libraAvatarPath: widget.libraAvatarPath,
              userAvatarPath: widget.userAvatarPath,
              onTapUp: message.isUser
                  ? null
                  : (details) =>
                        _chooseFavorite(message, details.globalPosition),
            ),
          ],
        );
      },
    );
  }

  bool _shouldShowTime(int index) {
    final current = _messages[index].createdAt;
    if (current == null) return false;
    if (index == 0) return true;
    final previous = _messages[index - 1].createdAt;
    if (previous == null) return true;
    return current.difference(previous).abs() >= const Duration(minutes: 5);
  }
}

class _MessageTime extends StatelessWidget {
  const _MessageTime({required this.time, required this.scale});

  final DateTime time;
  final double scale;

  String _twoDigits(int value) => value.toString().padLeft(2, '0');

  String _format(BuildContext context) {
    final local = time.toLocal();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final date = DateTime(local.year, local.month, local.day);
    final days = today.difference(date).inDays;
    final clock = '${_twoDigits(local.hour)}:${_twoDigits(local.minute)}';
    if (days == 0) return clock;
    if (days == 1) return '昨天 $clock';
    if (local.year == now.year) {
      return '${local.month}月${local.day}日 $clock';
    }
    return '${local.year}年${local.month}月${local.day}日 $clock';
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(top: 2 * scale, bottom: 12 * scale),
      child: Text(
        _format(context),
        style: TextStyle(color: const Color(0xFF9D9998), fontSize: 12 * scale),
      ),
    );
  }
}

class _RecordingOverlay extends StatelessWidget {
  const _RecordingOverlay({required this.seconds, required this.scale});

  final int seconds;
  final double scale;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.black.withValues(alpha: 0.12),
      child: Center(
        child: Container(
          width: 178 * scale,
          padding: EdgeInsets.symmetric(
            horizontal: 22 * scale,
            vertical: 20 * scale,
          ),
          decoration: BoxDecoration(
            color: const Color(0xEFFFFFFF),
            borderRadius: BorderRadius.circular(22 * scale),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.14),
                blurRadius: 20 * scale,
                offset: Offset(0, 8 * scale),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 58 * scale,
                height: 58 * scale,
                decoration: const BoxDecoration(
                  color: _accent,
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  Icons.mic_rounded,
                  color: Colors.white,
                  size: 32 * scale,
                ),
              ),
              SizedBox(height: 12 * scale),
              Text(
                '正在听…  ${seconds}s',
                style: TextStyle(
                  fontSize: 17 * scale,
                  fontWeight: FontWeight.w600,
                ),
              ),
              SizedBox(height: 5 * scale),
              Text(
                '松开发送',
                style: TextStyle(
                  color: const Color(0xFF8C8583),
                  fontSize: 13 * scale,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ChatHeader extends StatelessWidget {
  const _ChatHeader({
    required this.scale,
    required this.sleeping,
    required this.status,
    required this.syncing,
    required this.changing,
    required this.onToggleSleep,
    required this.onSearch,
    required this.onKeywordSearch,
    required this.onFavorites,
  });

  final double scale;
  final bool sleeping;
  final String status;
  final bool syncing;
  final bool changing;
  final VoidCallback onToggleSleep;
  final VoidCallback onSearch;
  final VoidCallback onKeywordSearch;
  final VoidCallback onFavorites;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 68,
      width: double.infinity,
      color: Colors.transparent,
      alignment: Alignment.center,
      child: Stack(
        fit: StackFit.expand,
        alignment: Alignment.center,
        children: [
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                DisplayNames.libra,
                style: TextStyle(
                  color: const Color(0xFF443E3C),
                  fontSize: 20 * scale,
                  fontWeight: FontWeight.w600,
                  letterSpacing: .8 * scale,
                ),
              ),
              SizedBox(height: 4 * scale),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (syncing)
                    SizedBox(
                      width: 10 * scale,
                      height: 10 * scale,
                      child: const CircularProgressIndicator(
                        strokeWidth: 1.5,
                        color: _accent,
                      ),
                    )
                  else
                    Container(
                      width: 6 * scale,
                      height: 6 * scale,
                      decoration: BoxDecoration(
                        color: sleeping
                            ? const Color(0xFFA99BBD)
                            : const Color(0xFF8FB5A1),
                        shape: BoxShape.circle,
                      ),
                    ),
                  SizedBox(width: 5 * scale),
                  Text(
                    syncing ? '正在同步…' : status,
                    style: TextStyle(color: _inactive, fontSize: 11 * scale),
                  ),
                ],
              ),
            ],
          ),
          Positioned(
            left: 14 * scale,
            child: Tooltip(
              message: sleeping
                  ? '唤醒${DisplayNames.libra}'
                  : '让${DisplayNames.libra}离线',
              child: Material(
                color: Colors.transparent,
                child: InkWell(
                  onTap: changing || !sleeping ? null : onToggleSleep,
                  borderRadius: BorderRadius.circular(18 * scale),
                  child: Container(
                    height: 34 * scale,
                    padding: EdgeInsets.symmetric(horizontal: 10 * scale),
                    decoration: BoxDecoration(
                      color: sleeping
                          ? const Color(0xFFF0EAF3)
                          : const Color(0xFFFFEEEB),
                      borderRadius: BorderRadius.circular(18 * scale),
                      border: Border.all(
                        color: sleeping
                            ? const Color(0xFFD8CCE0)
                            : const Color(0xFFF0C9C4),
                      ),
                    ),
                    child: changing
                        ? Container(
                            width: 17 * scale,
                            height: 17 * scale,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              border: Border.all(color: _accent, width: 2),
                            ),
                            alignment: Alignment.center,
                            child: Container(
                              width: 4 * scale,
                              height: 4 * scale,
                              decoration: const BoxDecoration(
                                color: _accent,
                                shape: BoxShape.circle,
                              ),
                            ),
                          )
                        : Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                sleeping
                                    ? Icons.wb_sunny_outlined
                                    : Icons.power_settings_new_rounded,
                                size: 17 * scale,
                                color: sleeping
                                    ? const Color(0xFF8D789E)
                                    : _accent,
                              ),
                              SizedBox(width: 4 * scale),
                              Text(
                                sleeping ? '唤醒' : '在线',
                                style: TextStyle(
                                  fontSize: 11 * scale,
                                  color: sleeping
                                      ? const Color(0xFF806D90)
                                      : const Color(0xFF9C5C55),
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ],
                          ),
                  ),
                ),
              ),
            ),
          ),
          Positioned(
            right: 14 * scale,
            child: PopupMenuButton<String>(
              tooltip: '更多',
              color: const Color(0xFFFFFAF9),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16 * scale),
              ),
              onSelected: (value) {
                if (value == 'dateSearch') onSearch();
                if (value == 'keywordSearch') onKeywordSearch();
                if (value == 'favorites') onFavorites();
              },
              itemBuilder: (_) => const [
                PopupMenuItem(
                  value: 'keywordSearch',
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.search_rounded, color: _accent),
                    title: Text('搜索聊天记录'),
                  ),
                ),
                PopupMenuItem(
                  value: 'dateSearch',
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.calendar_month_rounded, color: _accent),
                    title: Text('按天查找'),
                  ),
                ),
                PopupMenuItem(
                  value: 'favorites',
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.favorite_rounded, color: _accent),
                    title: Text('收藏消息'),
                  ),
                ),
              ],
              child: Container(
                width: 38 * scale,
                height: 34 * scale,
                decoration: BoxDecoration(
                  color: const Color(0xFFFFEEEB),
                  borderRadius: BorderRadius.circular(18 * scale),
                  border: Border.all(color: const Color(0xFFF0C9C4)),
                ),
                child: Icon(
                  Icons.more_horiz_rounded,
                  color: _accent,
                  size: 23 * scale,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({
    required this.message,
    required this.scale,
    this.libraAvatarPath,
    this.userAvatarPath,
    this.onTapUp,
  });
  final ChatMessage message;
  final double scale;
  final String? libraAvatarPath;
  final String? userAvatarPath;
  final GestureTapUpCallback? onTapUp;

  @override
  Widget build(BuildContext context) {
    void triggerFavoriteFromText() {
      final box = context.findRenderObject();
      if (box is! RenderBox || !box.hasSize || onTapUp == null) return;
      final localPosition = box.size.center(Offset.zero);
      onTapUp!(
        TapUpDetails(
          kind: PointerDeviceKind.touch,
          localPosition: localPosition,
          globalPosition: box.localToGlobal(localPosition),
        ),
      );
    }

    if (message.isNudge) {
      final markerIndex = message.content.indexOf('拍了拍你');
      final displayContent = markerIndex >= 0
          ? '${DisplayNames.libra}${message.content.substring(markerIndex)}'
          : message.content;
      return Padding(
        padding: EdgeInsets.only(bottom: 18 * scale),
        child: Center(
          child: SelectableText(
            displayContent,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: const Color(0xFFA88E67),
              fontSize: 13 * scale,
              height: 1.4,
            ),
          ),
        ),
      );
    }
    final isUser = message.isUser;
    final avatar = _Avatar(
      asset: isUser ? 'assets/avatars/simple.png' : 'assets/avatars/libra.png',
      filePath: isUser ? userAvatarPath : libraAvatarPath,
      scale: scale,
    );
    final bubble = Flexible(
      child: message.isXhsCard
          ? _XhsMessageCard(
              card: message.xhsCard!,
              isUser: isUser,
              scale: scale,
            )
          : message.isVoice
          ? _VoiceBubble(
              message: message,
              scale: scale,
              onFavorite: onTapUp == null ? null : triggerFavoriteFromText,
            )
          : message.isImage
          ? ClipRRect(
              borderRadius: BorderRadius.circular(
                (message.isSticker ? 4 : 14) * scale,
              ),
              child: message.localFilePath != null
                  ? Image.file(
                      File(message.localFilePath!),
                      width: 210 * scale,
                      fit: BoxFit.cover,
                    )
                  : message.localAssetPath != null
                  ? Image.asset(
                      message.localAssetPath!,
                      width: 120 * scale,
                      height: 120 * scale,
                      fit: BoxFit.contain,
                    )
                  : Image.network(
                      '${ApiConfig.baseUrl}${message.mediaUrl}',
                      width: (message.isSticker ? 120 : 210) * scale,
                      height: message.isSticker ? 120 * scale : null,
                      fit: message.isSticker ? BoxFit.contain : BoxFit.cover,
                      errorBuilder: (_, _, _) => Container(
                        width: 180 * scale,
                        height: 120 * scale,
                        color: Colors.white,
                        alignment: Alignment.center,
                        child: const Icon(Icons.broken_image_outlined),
                      ),
                    ),
            )
          : Container(
              constraints: BoxConstraints(maxWidth: 300 * scale),
              padding: EdgeInsets.symmetric(
                horizontal: 16 * scale,
                vertical: 13 * scale,
              ),
              decoration: BoxDecoration(
                color: isUser
                    ? _userBubble
                    : Colors.white.withValues(alpha: .88),
                borderRadius: BorderRadius.only(
                  topLeft: Radius.circular(20 * scale),
                  topRight: Radius.circular(20 * scale),
                  bottomLeft: Radius.circular((isUser ? 20 : 6) * scale),
                  bottomRight: Radius.circular((isUser ? 6 : 20) * scale),
                ),
                border: Border.all(
                  color: isUser
                      ? const Color(0xFFFFC7C1)
                      : const Color(0xFFF2E8E6),
                ),
                boxShadow: [
                  BoxShadow(
                    color:
                        (isUser
                                ? const Color(0xFFCE766C)
                                : const Color(0xFF6F5551))
                            .withValues(alpha: isUser ? .15 : .11),
                    blurRadius: 16 * scale,
                    spreadRadius: .3 * scale,
                    offset: Offset(0, 5 * scale),
                  ),
                ],
              ),
              child: SelectableText(
                message.content,
                onTap: onTapUp == null ? null : triggerFavoriteFromText,
                style: TextStyle(fontSize: 16 * scale, height: 1.45),
              ),
            ),
    );
    return GestureDetector(
      behavior: HitTestBehavior.translucent,
      onTapUp: onTapUp,
      child: Padding(
        padding: EdgeInsets.only(bottom: 18 * scale),
        child: Row(
          mainAxisAlignment: isUser
              ? MainAxisAlignment.end
              : MainAxisAlignment.start,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: isUser
              ? [bubble, SizedBox(width: 8 * scale), avatar]
              : [avatar, SizedBox(width: 8 * scale), bubble],
        ),
      ),
    );
  }
}

class _XhsMessageCard extends StatelessWidget {
  const _XhsMessageCard({
    required this.card,
    required this.isUser,
    required this.scale,
  });

  final XhsCardData card;
  final bool isUser;
  final double scale;

  String get _displayTitle => card.title
      .replaceFirst(RegExp(r'\s*[-–—|]​?\s*小红书\s*$', caseSensitive: false), '')
      .trim();

  String _mediaUrl(String value) =>
      value.startsWith('/') ? '${ApiConfig.baseUrl}$value' : value;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      borderRadius: BorderRadius.circular(16 * scale),
      onTap: card.url.isEmpty
          ? null
          : () => launchUrl(
              Uri.parse(card.url),
              mode: LaunchMode.externalApplication,
            ),
      onLongPress: card.url.isEmpty
          ? null
          : () async {
              await Clipboard.setData(ClipboardData(text: card.url));
              if (!context.mounted) return;
              ScaffoldMessenger.of(context)
                ..hideCurrentSnackBar()
                ..showSnackBar(const SnackBar(content: Text('小红书链接已复制')));
            },
      child: Container(
        width: 250 * scale,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(
          color: isUser
              ? const Color(0xFFFFE0DC)
              : Colors.white.withValues(alpha: .94),
          borderRadius: BorderRadius.circular(16 * scale),
          border: Border.all(color: const Color(0xFFF0C7C2)),
          boxShadow: [
            BoxShadow(
              color: const Color(0xFF8D5E58).withValues(alpha: .12),
              blurRadius: 14 * scale,
              offset: Offset(0, 4 * scale),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (card.imageUrls.isNotEmpty || card.coverUrl.isNotEmpty)
              SizedBox(
                height: 128 * scale,
                child: PageView.builder(
                  itemCount: card.imageUrls.isNotEmpty
                      ? card.imageUrls.length
                      : 1,
                  itemBuilder: (context, index) {
                    final url = card.imageUrls.isNotEmpty
                        ? card.imageUrls[index]
                        : card.coverUrl;
                    return Stack(
                      fit: StackFit.expand,
                      children: [
                        Image.network(
                          _mediaUrl(url),
                          fit: BoxFit.cover,
                          headers: url.startsWith('/')
                              ? null
                              : const {
                                  'Referer': 'https://www.xiaohongshu.com/',
                                },
                          errorBuilder: (_, _, _) => _xhsImageFallback(scale),
                        ),
                        if (card.imageUrls.length > 1)
                          Positioned(
                            right: 8 * scale,
                            top: 8 * scale,
                            child: Container(
                              padding: EdgeInsets.symmetric(
                                horizontal: 7 * scale,
                                vertical: 3 * scale,
                              ),
                              decoration: BoxDecoration(
                                color: Colors.black54,
                                borderRadius: BorderRadius.circular(10 * scale),
                              ),
                              child: Text(
                                '${index + 1}/${card.imageUrls.length}',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 10 * scale,
                                ),
                              ),
                            ),
                          ),
                      ],
                    );
                  },
                ),
              )
            else
              _xhsImageFallback(scale),
            Padding(
              padding: EdgeInsets.fromLTRB(
                13 * scale,
                11 * scale,
                13 * scale,
                12 * scale,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: EdgeInsets.symmetric(
                          horizontal: 7 * scale,
                          vertical: 3 * scale,
                        ),
                        decoration: BoxDecoration(
                          color: const Color(0xFFFF5A5F),
                          borderRadius: BorderRadius.circular(8 * scale),
                        ),
                        child: Text(
                          '小红书',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 10 * scale,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ],
                  ),
                  SizedBox(height: 7 * scale),
                  Text(
                    _displayTitle.isEmpty ? '小红书笔记' : _displayTitle,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: const Color(0xFF3E302E),
                      fontSize: 15 * scale,
                      height: 1.3,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  if (card.comment.isNotEmpty) ...[
                    Padding(
                      padding: EdgeInsets.only(top: 9 * scale),
                      child: Container(
                        width: double.infinity,
                        padding: EdgeInsets.only(top: 8 * scale),
                        decoration: const BoxDecoration(
                          border: Border(
                            top: BorderSide(color: Color(0xFFF1D8D4)),
                          ),
                        ),
                        child: Text(
                          card.comment,
                          style: TextStyle(
                            color: const Color(0xFF493936),
                            fontSize: 14 * scale,
                            height: 1.4,
                          ),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _xhsImageFallback(double scale) => Container(
    width: double.infinity,
    height: 105 * scale,
    color: const Color(0xFFFFF0EE),
    alignment: Alignment.center,
    child: Icon(
      Icons.auto_awesome_rounded,
      color: const Color(0xFFE47E75),
      size: 34 * scale,
    ),
  );
}

class _Avatar extends StatelessWidget {
  const _Avatar({required this.asset, required this.scale, this.filePath});
  final String asset;
  final double scale;
  final String? filePath;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(2 * scale),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14 * scale),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: .07),
            blurRadius: 8 * scale,
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12 * scale),
        child: Image(
          image: filePath != null && File(filePath!).existsSync()
              ? FileImage(File(filePath!))
              : AssetImage(asset),
          width: 42 * scale,
          height: 42 * scale,
          fit: BoxFit.cover,
        ),
      ),
    );
  }
}

class _VoiceBubble extends StatefulWidget {
  const _VoiceBubble({
    required this.message,
    required this.scale,
    this.onFavorite,
  });

  final ChatMessage message;
  final double scale;
  final VoidCallback? onFavorite;

  @override
  State<_VoiceBubble> createState() => _VoiceBubbleState();
}

class _VoiceBubbleState extends State<_VoiceBubble> {
  final AudioPlayer _player = AudioPlayer();
  bool _playing = false;
  bool _showTranscript = false;

  @override
  void initState() {
    super.initState();
    _player.onPlayerComplete.listen((_) {
      if (mounted) setState(() => _playing = false);
    });
  }

  Future<void> _toggle() async {
    if (_playing) {
      await _player.stop();
      if (mounted) setState(() => _playing = false);
      return;
    }
    final source = widget.message.localFilePath != null
        ? DeviceFileSource(widget.message.localFilePath!)
        : UrlSource('${ApiConfig.baseUrl}${widget.message.mediaUrl}');
    await _player.play(source);
    if (mounted) setState(() => _playing = true);
  }

  @override
  void dispose() {
    _player.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final seconds = widget.message.durationSeconds ?? 1;
    return Semantics(
      label: _showTranscript
          ? '语音 $seconds 秒，识别文字：${widget.message.content}'
          : '语音 $seconds 秒，点击 A 查看识别文字',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            textDirection: widget.message.isUser
                ? TextDirection.ltr
                : TextDirection.rtl,
            children: [
              Semantics(
                label: _showTranscript ? '隐藏识别文字' : '语音转文字',
                button: true,
                child: InkWell(
                  onTap: () => setState(() {
                    _showTranscript = !_showTranscript;
                  }),
                  onLongPress: widget.onFavorite,
                  customBorder: const CircleBorder(),
                  child: Container(
                    width: 30 * widget.scale,
                    height: 30 * widget.scale,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: _showTranscript
                          ? const Color(0xFFFFE5E1)
                          : Colors.transparent,
                      border: Border.all(
                        color: const Color(0xFF7D7D7D),
                        width: 1.6 * widget.scale,
                      ),
                    ),
                    child: Text(
                      'A',
                      style: TextStyle(
                        color: const Color(0xFF737373),
                        fontSize: 18 * widget.scale,
                      ),
                    ),
                  ),
                ),
              ),
              SizedBox(width: 9 * widget.scale),
              InkWell(
                onTap: _toggle,
                onLongPress: widget.onFavorite,
                borderRadius: BorderRadius.circular(17 * widget.scale),
                child: Container(
                  width:
                      (92 + seconds.clamp(0, 30) * 3).toDouble() * widget.scale,
                  constraints: BoxConstraints(maxWidth: 210 * widget.scale),
                  padding: EdgeInsets.symmetric(
                    horizontal: 15 * widget.scale,
                    vertical: 12 * widget.scale,
                  ),
                  decoration: BoxDecoration(
                    color: widget.message.isUser ? _userBubble : Colors.white,
                    borderRadius: BorderRadius.circular(17 * widget.scale),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    textDirection: widget.message.isUser
                        ? TextDirection.rtl
                        : TextDirection.ltr,
                    children: [
                      Icon(
                        _playing
                            ? Icons.stop_rounded
                            : Icons.graphic_eq_rounded,
                        size: 25 * widget.scale,
                        color: const Color(0xFF7D625F),
                      ),
                      SizedBox(width: 9 * widget.scale),
                      Text(
                        '$seconds″',
                        style: TextStyle(
                          fontSize: 15 * widget.scale,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          if (_showTranscript) ...[
            SizedBox(height: 8 * widget.scale),
            Container(
              margin: EdgeInsets.only(
                left: widget.message.isUser ? 39 * widget.scale : 0,
                right: widget.message.isUser ? 0 : 39 * widget.scale,
              ),
              constraints: BoxConstraints(maxWidth: 210 * widget.scale),
              padding: EdgeInsets.symmetric(
                horizontal: 15 * widget.scale,
                vertical: 11 * widget.scale,
              ),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.92),
                borderRadius: BorderRadius.circular(13 * widget.scale),
              ),
              child: SelectableText(
                widget.message.content,
                style: TextStyle(fontSize: 15 * widget.scale, height: 1.4),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.enabled,
    required this.onSend,
    required this.onInputTap,
    required this.replyMode,
    required this.onReplyModeChanged,
    required this.voiceMode,
    required this.recording,
    required this.recordingSeconds,
    required this.onToggleVoice,
    required this.onRecordStart,
    required this.onRecordEnd,
    required this.showMoreActions,
    required this.onToggleMore,
    required this.showStickerPanel,
    required this.onShowStickers,
    required this.onSendSticker,
    required this.stickers,
    required this.loadingStickers,
    required this.onPickImage,
    required this.onTakePhoto,
    required this.onStartCall,
    required this.xhsCard,
    required this.loadingXhsPreview,
    required this.xhsPreviewError,
    required this.onClearXhsPreview,
    required this.scale,
  });
  final TextEditingController controller;
  final bool enabled;
  final VoidCallback onSend;
  final VoidCallback onInputTap;
  final _ReplyMode replyMode;
  final ValueChanged<_ReplyMode> onReplyModeChanged;
  final bool voiceMode;
  final bool recording;
  final int recordingSeconds;
  final VoidCallback onToggleVoice;
  final VoidCallback onRecordStart;
  final VoidCallback onRecordEnd;
  final bool showMoreActions;
  final VoidCallback onToggleMore;
  final bool showStickerPanel;
  final VoidCallback onShowStickers;
  final ValueChanged<StickerCatalogItem> onSendSticker;
  final List<StickerCatalogItem> stickers;
  final bool loadingStickers;
  final VoidCallback onPickImage;
  final VoidCallback onTakePhoto;
  final VoidCallback onStartCall;
  final XhsCardData? xhsCard;
  final bool loadingXhsPreview;
  final String? xhsPreviewError;
  final VoidCallback onClearXhsPreview;
  final double scale;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: showMoreActions ? const Color(0xCFFFF0ED) : Colors.transparent,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          ColoredBox(
            color: const Color(0xFFFFFAF9).withValues(alpha: .55),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Padding(
                padding: EdgeInsets.fromLTRB(16 * scale, 5 * scale, 0, 0),
                child: PopupMenuButton<_ReplyMode>(
                  tooltip: '选择${DisplayNames.libra}的回复方式',
                  initialValue: replyMode,
                  onSelected: onReplyModeChanged,
                  itemBuilder: (context) => _ReplyMode.values
                      .map(
                        (mode) => PopupMenuItem(
                          value: mode,
                          child: Row(
                            children: [
                              Icon(mode.icon, size: 20, color: _accent),
                              const SizedBox(width: 10),
                              Text(mode.label),
                              if (mode == replyMode) ...[
                                const Spacer(),
                                const Icon(
                                  Icons.check_rounded,
                                  size: 20,
                                  color: _accent,
                                ),
                              ],
                            ],
                          ),
                        ),
                      )
                      .toList(),
                  child: Container(
                    padding: EdgeInsets.symmetric(
                      horizontal: 11 * scale,
                      vertical: 6 * scale,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFFE4E0),
                      borderRadius: BorderRadius.circular(16 * scale),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(replyMode.icon, size: 16 * scale, color: _accent),
                        SizedBox(width: 5 * scale),
                        Text(
                          '${DisplayNames.libra}：${replyMode.label}',
                          style: TextStyle(
                            color: const Color(0xFF8B514B),
                            fontSize: 12 * scale,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        SizedBox(width: 2 * scale),
                        Icon(
                          Icons.arrow_drop_down_rounded,
                          size: 18 * scale,
                          color: _accent,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
          if (xhsCard != null || loadingXhsPreview || xhsPreviewError != null)
            _XhsComposerPreview(
              card: xhsCard,
              loading: loadingXhsPreview,
              error: xhsPreviewError,
              onClose: onClearXhsPreview,
              scale: scale,
            ),
          Padding(
            padding: EdgeInsets.fromLTRB(
              14 * scale,
              8 * scale,
              12 * scale,
              9 * scale,
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: voiceMode
                      ? GestureDetector(
                          behavior: HitTestBehavior.opaque,
                          onLongPressStart: enabled
                              ? (_) => onRecordStart()
                              : null,
                          onLongPressEnd: enabled ? (_) => onRecordEnd() : null,
                          child: Container(
                            height: 48 * scale,
                            decoration: BoxDecoration(
                              color: recording
                                  ? const Color(0xFFFFD9D5)
                                  : Colors.white,
                              borderRadius: BorderRadius.circular(22 * scale),
                            ),
                            child: Stack(
                              alignment: Alignment.center,
                              children: [
                                Text(
                                  recording
                                      ? '松开发送  ${recordingSeconds}s'
                                      : '按住说话',
                                  style: TextStyle(fontSize: 16 * scale),
                                ),
                                Positioned(
                                  right: 4 * scale,
                                  child: IconButton(
                                    tooltip: '切换键盘',
                                    onPressed: onToggleVoice,
                                    icon: Icon(
                                      Icons.keyboard_alt_outlined,
                                      color: const Color(0xFFA5A7A8),
                                      size: 26 * scale,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )
                      : TextField(
                          controller: controller,
                          enabled: enabled,
                          onTap: onInputTap,
                          onTapOutside: (_) =>
                              FocusManager.instance.primaryFocus?.unfocus(),
                          minLines: 1,
                          maxLines: 4,
                          textInputAction: TextInputAction.newline,
                          style: TextStyle(fontSize: 16 * scale),
                          decoration: InputDecoration(
                            hintText: '输入消息…',
                            hintStyle: TextStyle(fontSize: 16 * scale),
                            suffixIcon: IconButton(
                              onPressed: onToggleVoice,
                              icon: Icon(
                                Icons.mic_none_rounded,
                                color: const Color(0xFFA5A7A8),
                                size: 27 * scale,
                              ),
                            ),
                            filled: true,
                            fillColor: Colors.white,
                            border: OutlineInputBorder(
                              borderRadius: BorderRadius.all(
                                Radius.circular(22 * scale),
                              ),
                              borderSide: const BorderSide(
                                color: Color(0xFFF0E4E2),
                              ),
                            ),
                            enabledBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.all(
                                Radius.circular(22 * scale),
                              ),
                              borderSide: const BorderSide(
                                color: Color(0xFFF0E4E2),
                              ),
                            ),
                            focusedBorder: OutlineInputBorder(
                              borderRadius: BorderRadius.all(
                                Radius.circular(22 * scale),
                              ),
                              borderSide: const BorderSide(
                                color: _accent,
                                width: 1.2,
                              ),
                            ),
                            contentPadding: EdgeInsets.symmetric(
                              horizontal: 16 * scale,
                              vertical: 12 * scale,
                            ),
                          ),
                        ),
                ),
                SizedBox(width: 8 * scale),
                _ComposerCircleButton(
                  icon: Icons.arrow_upward_rounded,
                  onPressed: enabled ? onSend : null,
                  scale: scale,
                ),
                SizedBox(width: 8 * scale),
                _ComposerCircleButton(
                  icon: showMoreActions ? Icons.close : Icons.add,
                  onPressed: onToggleMore,
                  scale: scale,
                ),
              ],
            ),
          ),
          if (showMoreActions)
            showStickerPanel
                ? _StickerPanel(
                    scale: scale,
                    stickers: stickers,
                    loading: loadingStickers,
                    onSelected: onSendSticker,
                  )
                : _MoreActionsPanel(
                    scale: scale,
                    onShowStickers: onShowStickers,
                    onPickImage: onPickImage,
                    onTakePhoto: onTakePhoto,
                    onStartCall: onStartCall,
                  ),
        ],
      ),
    );
  }
}

class _XhsComposerPreview extends StatelessWidget {
  const _XhsComposerPreview({
    required this.card,
    required this.loading,
    required this.error,
    required this.onClose,
    required this.scale,
  });

  final XhsCardData? card;
  final bool loading;
  final String? error;
  final VoidCallback onClose;
  final double scale;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(14 * scale, 8 * scale, 14 * scale, 0),
      child: Container(
        height: 76 * scale,
        padding: EdgeInsets.all(8 * scale),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: .92),
          borderRadius: BorderRadius.circular(14 * scale),
          border: Border.all(color: const Color(0xFFF0C9C4)),
        ),
        child: Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(9 * scale),
              child: SizedBox(
                width: 58 * scale,
                height: 58 * scale,
                child: loading
                    ? const ColoredBox(
                        color: Color(0xFFFFEFED),
                        child: Center(
                          child: SizedBox.square(
                            dimension: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: _accent,
                            ),
                          ),
                        ),
                      )
                    : card?.coverUrl.isNotEmpty == true
                    ? Image.network(
                        card!.coverUrl.startsWith('/')
                            ? '${ApiConfig.baseUrl}${card!.coverUrl}'
                            : card!.coverUrl,
                        fit: BoxFit.cover,
                        loadingBuilder: (context, child, progress) =>
                            progress == null
                            ? child
                            : const Center(
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: _accent,
                                ),
                              ),
                        headers: const {
                          'Referer': 'https://www.xiaohongshu.com/',
                        },
                        errorBuilder: (_, _, _) => const ColoredBox(
                          color: Color(0xFFFFEFED),
                          child: Icon(Icons.auto_awesome, color: _accent),
                        ),
                      )
                    : const ColoredBox(
                        color: Color(0xFFFFEFED),
                        child: Icon(Icons.auto_awesome, color: _accent),
                      ),
              ),
            ),
            SizedBox(width: 10 * scale),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    loading ? '正在读取小红书笔记…' : error ?? card?.title ?? '小红书笔记',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: error == null
                          ? const Color(0xFF493936)
                          : const Color(0xFFC15F57),
                      fontSize: 13 * scale,
                      height: 1.25,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: '取消分享',
              onPressed: onClose,
              visualDensity: VisualDensity.compact,
              icon: Icon(
                Icons.close_rounded,
                color: const Color(0xFFA89591),
                size: 20 * scale,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ComposerCircleButton extends StatelessWidget {
  const _ComposerCircleButton({
    required this.icon,
    required this.onPressed,
    required this.scale,
  });

  final IconData icon;
  final VoidCallback? onPressed;
  final double scale;

  @override
  Widget build(BuildContext context) {
    return SizedBox.square(
      dimension: 42 * scale,
      child: IconButton.filled(
        style: IconButton.styleFrom(backgroundColor: _accent),
        onPressed: onPressed,
        icon: Icon(icon, color: Colors.white, size: 24 * scale),
      ),
    );
  }
}

class _MoreActionsPanel extends StatelessWidget {
  const _MoreActionsPanel({
    required this.scale,
    required this.onShowStickers,
    required this.onPickImage,
    required this.onTakePhoto,
    required this.onStartCall,
  });

  final double scale;
  final VoidCallback onShowStickers;
  final VoidCallback onPickImage;
  final VoidCallback onTakePhoto;
  final VoidCallback onStartCall;

  @override
  Widget build(BuildContext context) {
    const actions = [
      (Icons.sentiment_satisfied_alt_outlined, '表情'),
      (Icons.photo_library_outlined, '相册'),
      (Icons.photo_camera_outlined, '相机'),
      (Icons.videocam_outlined, '视频'),
    ];
    return SizedBox(
      height: 190 * scale,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: actions.map((action) {
          return Padding(
            padding: EdgeInsets.only(top: 28 * scale),
            child: Tooltip(
              message: action.$2,
              child: InkWell(
                borderRadius: BorderRadius.circular(11 * scale),
                onTap: switch (action.$2) {
                  '表情' => onShowStickers,
                  '相册' => onPickImage,
                  '相机' => onTakePhoto,
                  '视频' => onStartCall,
                  _ => null,
                },
                child: Container(
                  width: 58 * scale,
                  height: 58 * scale,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.82),
                    borderRadius: BorderRadius.circular(11 * scale),
                  ),
                  alignment: Alignment.center,
                  child: Icon(
                    action.$1,
                    size: 36 * scale,
                    color: const Color(0xFF626262),
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

class _StickerPanel extends StatelessWidget {
  const _StickerPanel({
    required this.scale,
    required this.stickers,
    required this.loading,
    required this.onSelected,
  });

  final double scale;
  final List<StickerCatalogItem> stickers;
  final bool loading;
  final ValueChanged<StickerCatalogItem> onSelected;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 230 * scale,
      child: loading && stickers.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : stickers.isEmpty
          ? const Center(child: Text('还没有表情包'))
          : GridView.builder(
              padding: EdgeInsets.fromLTRB(
                18 * scale,
                14 * scale,
                18 * scale,
                18 * scale,
              ),
              gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 4,
                mainAxisSpacing: 12 * scale,
                crossAxisSpacing: 12 * scale,
              ),
              itemCount: stickers.length,
              itemBuilder: (context, index) {
                final sticker = stickers[index];
                return InkWell(
                  borderRadius: BorderRadius.circular(12 * scale),
                  onTap: () => onSelected(sticker),
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.72),
                      borderRadius: BorderRadius.circular(12 * scale),
                    ),
                    child: Padding(
                      padding: EdgeInsets.fromLTRB(
                        5 * scale,
                        5 * scale,
                        5 * scale,
                        3 * scale,
                      ),
                      child: Column(
                        children: [
                          Expanded(
                            child: Image.network(
                              '${ApiConfig.baseUrl}${sticker.mediaUrl}',
                              fit: BoxFit.contain,
                            ),
                          ),
                          Text(
                            sticker.meaning,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              color: const Color(0xFF765F5C),
                              fontSize: 11 * scale,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                );
              },
            ),
    );
  }
}

// ignore: unused_element
class _HomePage extends StatelessWidget {
  const _HomePage({required this.note});

  final String note;

  int get _daysTogether {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    return today.difference(DateTime(2022, 8, 22)).inDays;
  }

  @override
  Widget build(BuildContext context) {
    // The reference artwork is 595 px wide. Convert its measurements to the
    // phone's logical width so the composition keeps the same proportions.
    final scale = (MediaQuery.sizeOf(context).width / 595).clamp(0.55, 0.80);
    double d(double value) => value * scale;

    return ColoredBox(
      color: _header,
      child: SingleChildScrollView(
        padding: EdgeInsets.fromLTRB(d(34), d(18), d(24), d(30)),
        child: Column(
          children: [
            Stack(
              alignment: Alignment.center,
              children: [
                Padding(
                  padding: EdgeInsets.symmetric(vertical: d(8)),
                  child: Text(
                    'W E L C O M E    H O M E',
                    style: TextStyle(
                      color: _accent,
                      fontSize: d(16),
                      fontWeight: FontWeight.w700,
                      letterSpacing: d(1.8),
                    ),
                  ),
                ),
                Align(
                  alignment: Alignment.centerRight,
                  child: Icon(
                    Icons.settings_outlined,
                    size: d(40),
                    color: _inactive,
                  ),
                ),
              ],
            ),
            SizedBox(height: d(50)),
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text.rich(
                const TextSpan(
                  children: [
                    TextSpan(text: 'Libra '),
                    TextSpan(
                      text: '&',
                      style: TextStyle(color: Color(0xFFD85042)),
                    ),
                    TextSpan(text: ' Simple'),
                  ],
                ),
                maxLines: 1,
                style: TextStyle(
                  fontSize: d(64),
                  fontStyle: FontStyle.italic,
                  fontFamily: 'serif',
                  letterSpacing: d(3),
                  color: const Color(0xFF393534),
                ),
              ),
            ),
            SizedBox(height: d(44)),
            Wrap(
              alignment: WrapAlignment.center,
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: d(12),
              children: [
                Text(
                  '$_daysTogether',
                  style: TextStyle(
                    color: const Color(0xFFD85042),
                    fontSize: d(30),
                    fontStyle: FontStyle.italic,
                    fontWeight: FontWeight.w600,
                    letterSpacing: d(3),
                  ),
                ),
                Text(
                  'days together',
                  style: TextStyle(fontSize: d(17), letterSpacing: d(3)),
                ),
              ],
            ),
            SizedBox(height: d(6)),
            Text(
              'Since August 22, 2022',
              style: TextStyle(fontSize: d(17), letterSpacing: d(3)),
            ),
            SizedBox(height: d(28)),
            _HomeCard(
              height: d(154),
              padding: d(22),
              radius: d(10),
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                child: Text(
                  note.isEmpty ? '…' : note,
                  key: ValueKey(note),
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: d(19),
                    height: 1.7,
                    letterSpacing: d(1.5),
                    color: const Color(0xFF55504F),
                  ),
                ),
              ),
            ),
            SizedBox(height: d(24)),
            Row(
              children: [
                Expanded(
                  child: _HomeCard(
                    height: d(174),
                    padding: d(22),
                    radius: d(10),
                  ),
                ),
                SizedBox(width: d(30)),
                Expanded(
                  child: _HomeCard(
                    height: d(174),
                    padding: d(22),
                    radius: d(10),
                  ),
                ),
              ],
            ),
            SizedBox(height: d(28)),
            _HomeCard(height: d(380), padding: d(22), radius: 0),
          ],
        ),
      ),
    );
  }
}

class _HomeCard extends StatelessWidget {
  const _HomeCard({
    required this.height,
    required this.padding,
    required this.radius,
    this.child,
  });

  final double height;
  final double padding;
  final double radius;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: height,
      width: double.infinity,
      padding: EdgeInsets.all(padding),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: _background,
        borderRadius: BorderRadius.circular(radius),
      ),
      child: child,
    );
  }
}

// ignore: unused_element
class _BottomNavigation extends StatelessWidget {
  const _BottomNavigation({
    required this.selectedIndex,
    required this.onSelected,
  });
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  static const icons = [
    Icons.home_outlined,
    Icons.forum_outlined,
    Icons.favorite_border_rounded,
    Icons.calendar_month_outlined,
    Icons.camera_outlined,
  ];

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.paddingOf(context).bottom;
    return Container(
      height: 52 + bottomInset,
      padding: EdgeInsets.only(bottom: bottomInset),
      color: _navigation,
      child: Row(
        children: List.generate(icons.length, (index) {
          final selected = selectedIndex == index;
          return Expanded(
            child: IconButton(
              onPressed: () => onSelected(index),
              iconSize: 27,
              color: selected ? _accent : _inactive,
              icon: Icon(icons[index]),
            ),
          );
        }),
      ),
    );
  }
}

// ignore: unused_element
class _PlaceholderPage extends StatelessWidget {
  const _PlaceholderPage({required this.index});
  final int index;
  static const labels = ['主页', '聊天', '羁绊', '日历', '动态'];

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          height: 88,
          width: double.infinity,
          color: _header,
          alignment: Alignment.center,
          child: Text(
            labels[index],
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
          ),
        ),
        Expanded(
          child: Center(
            child: Text(
              '${labels[index]}功能正在准备中',
              style: const TextStyle(color: Colors.black45),
            ),
          ),
        ),
      ],
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: const Color(0xFFFFD9D5),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        child: Row(
          children: [
            Expanded(child: Text(message)),
            TextButton(onPressed: onRetry, child: const Text('同步消息')),
          ],
        ),
      ),
    );
  }
}

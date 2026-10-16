import 'package:flutter/material.dart';
import '../services/libra_api.dart';

class CompanionEndButton extends StatefulWidget {
  const CompanionEndButton({
    super.key,
    required this.sessionId,
    required this.onEnded,
    this.compact = false,
    this.iconOnly = false,
  });
  final bool compact;
  final bool iconOnly;
  final String sessionId;
  final VoidCallback onEnded;

  @override
  State<CompanionEndButton> createState() => _CompanionEndButtonState();
}

class _CompanionEndButtonState extends State<CompanionEndButton> {
  bool _busy = false;
  final _api = LibraApi();

  @override
  void dispose() {
    _api.close();
    super.dispose();
  }

  Future<void> _end() async {
    setState(() => _busy = true);
    try {
      await _api.endCompanion(widget.sessionId);
      if (mounted) widget.onEnded();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('结束陪伴失败：$error')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => widget.iconOnly
      ? IconButton(
          tooltip: _busy ? '正在结束…' : '结束陪伴',
          onPressed: _busy ? null : _end,
          style: IconButton.styleFrom(
            backgroundColor: const Color(0xFFFFEEEB),
            foregroundColor: const Color(0xFFDE776C),
            minimumSize: const Size(40, 40),
          ),
          icon: const Icon(Icons.stop_circle_outlined, size: 20),
        )
      : TextButton.icon(
          style: widget.compact
              ? TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(horizontal: 2),
                  textStyle: Theme.of(
                    context,
                  ).textTheme.labelLarge?.copyWith(fontSize: 11),
                  foregroundColor: const Color(0xFFDE776C),
                  minimumSize: const Size(0, 40),
                )
              : null,
          onPressed: _busy ? null : _end,
          icon: Icon(
            Icons.stop_circle_outlined,
            size: widget.compact ? 14 : 18,
          ),
          label: Text(_busy ? '正在结束…' : '结束陪伴'),
        );
}

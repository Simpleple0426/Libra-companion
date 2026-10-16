import 'package:flutter/material.dart';

/// Full-screen cream and blush artwork, scaled to the viewport.
class ReadingRoomBackground extends StatelessWidget {
  const ReadingRoomBackground({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: const BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color(0xFFFFFAF7), Color(0xFFFFF0ED), Color(0xFFFBE5E1)],
        stops: [0, .45, 1],
      ),
    ),
    child: CustomPaint(painter: const _ReadingRoomArtwork(), child: child),
  );
}

class _ReadingRoomArtwork extends CustomPainter {
  const _ReadingRoomArtwork();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.clipRect(Offset.zero & size);
    final width = size.width;
    final height = size.height;

    // Broad, quiet circles echo the study-room reference without competing
    // with text. Drawing them directly avoids image loading and decoding.
    final upper = Rect.fromCircle(
      center: Offset(width * .96, height * .25),
      radius: width * .48,
    );
    canvas.drawOval(
      upper,
      Paint()
        ..shader = const RadialGradient(
          colors: [Color(0x70FFFFFF), Color(0x30FFFFFF), Color(0x00FFFFFF)],
          stops: [0, .84, 1],
        ).createShader(upper),
    );
    final lower = Rect.fromCircle(
      center: Offset(width * .09, height * .73),
      radius: width * .34,
    );
    canvas.drawOval(
      lower,
      Paint()
        ..shader = const RadialGradient(
          colors: [Color(0x30EFBEB8), Color(0x25EFBEB8), Color(0x00EFBEB8)],
          stops: [0, .92, 1],
        ).createShader(lower),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_ReadingRoomArtwork oldDelegate) => false;
}

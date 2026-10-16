import 'package:flutter/material.dart';

import 'home_page.dart';

const _card = Color(0xCCFFFFFF);
const _text = Color(0xFF3F3A39);
const _muted = Color(0xFFA6AEAC);
const _line = Color(0xFFE9B8B3);

class RoomPage extends StatelessWidget {
  const RoomPage({super.key, required this.onRoomSelected});

  final ValueChanged<String> onRoomSelected;

  static const _rooms = [
    _RoomData(
      name: '自习室',
      caption: '一起安静专注',
      icon: Icons.auto_stories_outlined,
    ),
    _RoomData(name: '书房', caption: '收藏想读的故事', icon: Icons.menu_book_rounded),
    _RoomData(name: '音乐室', caption: '一起听喜欢的歌', icon: Icons.headphones_rounded),
    _RoomData(name: '电影室', caption: '留一段时间看电影', icon: Icons.movie_outlined),
  ];

  @override
  Widget build(BuildContext context) => ColoredBox(
    color: Colors.transparent,
    child: Column(
      children: [
        const _RoomHeader(),
        Expanded(
          child: CustomScrollView(
            physics: const ClampingScrollPhysics(),
            slivers: [
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 14, 16, 28),
                sliver: SliverList.separated(
                  itemCount: _rooms.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 14),
                  itemBuilder: (context, index) => _RoomTile(
                    room: _rooms[index],
                    index: index,
                    onTap: () => onRoomSelected(_rooms[index].name),
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

class _RoomHeader extends StatelessWidget {
  const _RoomHeader();

  @override
  Widget build(BuildContext context) => Container(
    height: 68,
    padding: const EdgeInsets.symmetric(horizontal: 18),
    color: Colors.transparent,
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        const Text(
          'R O O M S',
          style: TextStyle(
            color: homeAccent,
            fontSize: 17,
            fontWeight: FontWeight.w700,
            letterSpacing: 3,
          ),
        ),
        const SizedBox(width: 10),
        const Icon(Icons.home_work_outlined, color: homeAccent, size: 22),
      ],
    ),
  );
}

class _RoomTile extends StatelessWidget {
  const _RoomTile({
    required this.room,
    required this.index,
    required this.onTap,
  });
  final _RoomData room;
  final int index;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final imageOnRight = index.isOdd;
    return Material(
      color: _card,
      borderRadius: BorderRadius.circular(24),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Container(
          height: 106,
          decoration: BoxDecoration(
            color: _card,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: Colors.white.withValues(alpha: .72)),
            boxShadow: [
              BoxShadow(
                color: homeAccent.withValues(alpha: .09),
                blurRadius: 18,
                offset: const Offset(0, 6),
              ),
            ],
          ),
          child: Row(
            textDirection: imageOnRight ? TextDirection.rtl : TextDirection.ltr,
            children: [
              SizedBox(width: 126, child: _RoomVisual(room: room)),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 15),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    crossAxisAlignment: imageOnRight
                        ? CrossAxisAlignment.end
                        : CrossAxisAlignment.start,
                    children: [
                      Text(
                        room.name,
                        textDirection: TextDirection.ltr,
                        style: const TextStyle(
                          color: _text,
                          fontSize: 19,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        room.caption,
                        textDirection: TextDirection.ltr,
                        textAlign: imageOnRight
                            ? TextAlign.right
                            : TextAlign.left,
                        style: const TextStyle(
                          color: _muted,
                          fontSize: 12,
                          height: 1.35,
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Row(
                        mainAxisSize: MainAxisSize.min,
                        textDirection: TextDirection.ltr,
                        children: [
                          Text(
                            '进入',
                            style: TextStyle(
                              color: homeAccent,
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          SizedBox(width: 2),
                          Icon(
                            Icons.chevron_right,
                            color: homeAccent,
                            size: 15,
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
      ),
    );
  }
}

class _RoomVisual extends StatelessWidget {
  const _RoomVisual({required this.room});
  final _RoomData room;

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          Colors.white.withValues(alpha: .34),
          const Color(0xFFF8DCD8).withValues(alpha: .72),
        ],
      ),
    ),
    child: Stack(
      alignment: Alignment.center,
      children: [
        Positioned(
          width: 70,
          height: 70,
          child: DecoratedBox(
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white.withValues(alpha: .45),
            ),
          ),
        ),
        Icon(room.icon, color: homeAccent, size: 35),
        Positioned(
          left: 17,
          bottom: 18,
          child: Container(
            width: 22,
            height: 3,
            decoration: BoxDecoration(
              color: _line,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ),
      ],
    ),
  );
}

class _RoomData {
  const _RoomData({
    required this.name,
    required this.caption,
    required this.icon,
  });
  final String name;
  final String caption;
  final IconData icon;
}

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/libra_api.dart';
import 'home_page.dart';
import 'backend_connection_page.dart';

class PersonalizationSettingsPage extends StatefulWidget {
  const PersonalizationSettingsPage({
    super.key,
    required this.proactiveEnabled,
    required this.libraNickname,
    required this.onProactiveChanged,
    required this.onCalendarPermission,
    required this.onSaved,
  });

  final bool proactiveEnabled;
  final String libraNickname;
  final ValueChanged<bool> onProactiveChanged;
  final Future<void> Function() onCalendarPermission;
  final Future<void> Function() onSaved;

  @override
  State<PersonalizationSettingsPage> createState() =>
      _PersonalizationSettingsPageState();
}

class _PersonalizationSettingsPageState
    extends State<PersonalizationSettingsPage> {
  final _api = LibraApi();
  final _libraName = TextEditingController(text: '左然');
  final _userName = TextEditingController(text: '我');
  final _libraNickname = TextEditingController(text: '左然');
  final _userNickname = TextEditingController(text: '我');
  static const _defaultUserAddress = '夫人、老婆、宝宝、亲爱的';
  final _userAddress = TextEditingController(text: _defaultUserAddress);
  final _dietLikes = TextEditingController();
  final _dietAvoid = TextEditingController();
  final _dietTaste = TextEditingController();
  final _dietNotes = TextEditingController();
  DateTime _metAt = DateTime(2026, 4, 26);
  int _minimumMinutes = 10;
  int _maximumMinutes = 20;
  bool _weatherReminderEnabled = true;
  bool _stateUpdateEnabled = true;
  String? _libraAvatar;
  String? _userAvatar;
  bool _saving = false;
  bool _loading = true;
  late bool _proactiveEnabled;

  @override
  void initState() {
    super.initState();
    _proactiveEnabled = widget.proactiveEnabled;
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    try {
      final remote = await _api.getPersonalizationSettings();
      Future<void> cacheString(String remoteKey, String localKey) async {
        final value = remote[remoteKey];
        if (value != null) await prefs.setString(localKey, '$value');
      }

      await cacheString('libra_name', 'profile_libra_name');
      await cacheString('user_name', 'profile_user_name');
      await cacheString('libra_nickname', 'profile_libra_nickname');
      await cacheString('user_nickname', 'profile_user_nickname');
      await cacheString('user_address', 'profile_user_address');
      await cacheString('met_at', 'profile_met_at');
      if (remote['user_diet_preferences'] is Map) {
        await prefs.setString(
          'profile_user_diet_preferences',
          jsonEncode(remote['user_diet_preferences']),
        );
      }
      for (final entry in const {
        'checkin_min_minutes': 'profile_checkin_min_minutes',
        'checkin_max_minutes': 'profile_checkin_max_minutes',
      }.entries) {
        final value = remote[entry.key];
        if (value is num) await prefs.setInt(entry.value, value.toInt());
      }
      for (final entry in const {
        'weather_reminder_enabled': 'profile_weather_reminder_enabled',
        'state_update_enabled': 'profile_state_update_enabled',
      }.entries) {
        final value = remote[entry.key];
        if (value is bool) await prefs.setBool(entry.value, value);
      }
    } catch (_) {
      // Use the last complete local cache while offline.
    }
    await _restoreAvatar('libra_avatar', 'libra_avatar.jpg', prefs);
    await _restoreAvatar('user_avatar', 'user_avatar.jpg', prefs);
    if (!mounted) return;
    setState(() {
      _libraName.text = prefs.getString('profile_libra_name') ?? '左然';
      _userName.text = prefs.getString('profile_user_name') ?? '我';
      final diet =
          jsonDecode(prefs.getString('profile_user_diet_preferences') ?? '{}')
              as Map;
      _dietLikes.text = '${diet['likes'] ?? ''}';
      _dietAvoid.text = '${diet['avoid'] ?? ''}';
      _dietTaste.text = '${diet['taste'] ?? ''}';
      _dietNotes.text = '${diet['notes'] ?? ''}';
      _libraNickname.text =
          prefs.getString('profile_libra_nickname') ??
          prefs.getString('profile_libra_address') ??
          '左然';
      _userNickname.text = prefs.getString('profile_user_nickname') ?? '我';
      final savedAddress = prefs.getString('profile_user_address');
      _userAddress.text = savedAddress == null || savedAddress == '你'
          ? _defaultUserAddress
          : savedAddress;
      _libraAvatar = prefs.getString('profile_libra_avatar');
      _userAvatar = prefs.getString('profile_user_avatar');
      _minimumMinutes = prefs.getInt('profile_checkin_min_minutes') ?? 10;
      _maximumMinutes = prefs.getInt('profile_checkin_max_minutes') ?? 20;
      _weatherReminderEnabled =
          prefs.getBool('profile_weather_reminder_enabled') ?? true;
      _stateUpdateEnabled =
          prefs.getBool('profile_state_update_enabled') ?? true;
      _metAt =
          DateTime.tryParse(prefs.getString('profile_met_at') ?? '') ??
          DateTime(2026, 4, 26);
      _loading = false;
    });
  }

  Future<void> _restoreAvatar(
    String stateKey,
    String filename,
    SharedPreferences prefs,
  ) async {
    try {
      final encoded = await _api.getMobileState(stateKey);
      if (encoded is! String || encoded.isEmpty) return;
      final directory = await getApplicationDocumentsDirectory();
      final file = File('${directory.path}/$filename');
      await file.writeAsBytes(base64Decode(encoded), flush: true);
      await prefs.setString(
        'profile_${stateKey.replaceFirst('_avatar', '')}_avatar',
        file.path,
      );
    } catch (_) {
      // Keep the local display cache while offline.
    }
  }

  Future<void> _saveAvatar(String stateKey, String? path) async {
    if (path == null) return;
    final file = File(path);
    if (!await file.exists()) return;
    await _api.setMobileState(stateKey, base64Encode(await file.readAsBytes()));
  }

  Future<void> _pickAvatar(bool libra) async {
    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      imageQuality: 88,
      maxWidth: 1200,
    );
    if (picked == null) return;
    final directory = await getApplicationDocumentsDirectory();
    final target = File(
      '${directory.path}/${libra ? 'libra' : 'user'}_avatar.jpg',
    );
    await File(picked.path).copy(target.path);
    if (!mounted) return;
    setState(
      () => libra ? _libraAvatar = target.path : _userAvatar = target.path,
    );
  }

  Future<void> _pickDate() async {
    final result = await showDatePicker(
      context: context,
      initialDate: _metAt,
      firstDate: DateTime(1990),
      lastDate: DateTime.now(),
      helpText: '选择相遇日期',
      cancelText: '取消',
      confirmText: '确定',
    );
    if (result != null) setState(() => _metAt = result);
  }

  Future<void> _save() async {
    if ([
      _libraName,
      _userName,
      _libraNickname,
      _userNickname,
      _userAddress,
    ].any((c) => c.text.trim().isEmpty)) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('显示名称不能为空')));
      return;
    }
    setState(() => _saving = true);
    final diet = {
      'likes': _dietLikes.text.trim(),
      'avoid': _dietAvoid.text.trim(),
      'taste': _dietTaste.text.trim(),
      'notes': _dietNotes.text.trim(),
    };
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('profile_user_diet_preferences', jsonEncode(diet));
    await prefs.setString('profile_libra_name', _libraName.text.trim());
    await prefs.setString('profile_user_name', _userName.text.trim());
    await prefs.setString('profile_libra_nickname', _libraNickname.text.trim());
    await prefs.setString('profile_user_nickname', _userNickname.text.trim());
    await prefs.setString('profile_user_address', _userAddress.text.trim());
    await prefs.setString('profile_met_at', _metAt.toIso8601String());
    await prefs.setInt('profile_checkin_min_minutes', _minimumMinutes);
    await prefs.setInt('profile_checkin_max_minutes', _maximumMinutes);
    await prefs.setBool(
      'profile_weather_reminder_enabled',
      _weatherReminderEnabled,
    );
    await prefs.setBool('profile_state_update_enabled', _stateUpdateEnabled);
    if (_libraAvatar != null) {
      await prefs.setString('profile_libra_avatar', _libraAvatar!);
    }
    if (_userAvatar != null) {
      await prefs.setString('profile_user_avatar', _userAvatar!);
    }
    var synced = true;
    try {
      await _api.setPersonalizationSettings(
        libraName: _libraName.text.trim(),
        userName: _userName.text.trim(),
        libraNickname: _libraNickname.text.trim(),
        userNickname: _userNickname.text.trim(),
        userAddress: _userAddress.text.trim(),
        metAt: _metAt,
        checkinMinMinutes: _minimumMinutes,
        checkinMaxMinutes: _maximumMinutes,
        weatherReminderEnabled: _weatherReminderEnabled,
        stateUpdateEnabled: _stateUpdateEnabled,
        userDietPreferences: diet,
      );
      await _saveAvatar('libra_avatar', _libraAvatar);
      await _saveAvatar('user_avatar', _userAvatar);
    } catch (_) {
      synced = false;
    }
    if (!mounted) return;
    setState(() => _saving = false);
    await widget.onSaved();
    if (!mounted) return;
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(synced ? '已保存' : '已保存在手机，后端暂时未同步'),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 2),
        margin: const EdgeInsets.fromLTRB(72, 0, 72, 24),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      ),
    );
  }

  ImageProvider _avatar(String? path, String fallback) =>
      path != null && File(path).existsSync()
      ? FileImage(File(path))
      : AssetImage(fallback);

  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: homeBackground,
    appBar: AppBar(
      backgroundColor: Colors.transparent,
      title: const Text('个性化设置'),
      centerTitle: true,
      actions: [
        TextButton(
          onPressed: _saving || _loading ? null : _save,
          child: Text(_loading ? '读取中' : (_saving ? '保存中' : '保存')),
        ),
      ],
    ),
    body: ListView(
      padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
      children: [
        ListTile(
          leading: const Icon(Icons.dns_outlined),
          title: const Text('服务器连接'),
          subtitle: const Text('修改后端地址'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push<void>(
            MaterialPageRoute<void>(
              builder: (_) => const BackendConnectionPage(),
            ),
          ),
        ),
        _section('头像', [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _avatarEditor(
                '左然的头像',
                _avatar(_libraAvatar, 'assets/avatars/libra.png'),
                () => _pickAvatar(true),
              ),
              _avatarEditor(
                '我的头像',
                _avatar(_userAvatar, 'assets/avatars/simple.png'),
                () => _pickAvatar(false),
              ),
            ],
          ),
        ]),
        _section('显示名称', [
          _compactField('首页 · 左然', _libraName),
          _compactField('首页 · 我', _userName),
          const Divider(height: 22),
          _compactField('左然的昵称', _libraNickname),
          _compactField('我的昵称', _userNickname),
          const Padding(
            padding: EdgeInsets.fromLTRB(2, 2, 2, 8),
            child: Text(
              '昵称只用于界面显示，不会改变聊天中的称呼。左然昵称用于首页以外的页面，我的昵称用于动态等共同展示区域。',
              style: TextStyle(
                fontSize: 12,
                height: 1.45,
                color: Colors.black45,
              ),
            ),
          ),
          ListTile(
            contentPadding: const EdgeInsets.symmetric(horizontal: 2),
            title: const Text('相遇时间'),
            subtitle: Text('${_metAt.year}.${_metAt.month}.${_metAt.day}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: _pickDate,
          ),
        ]),
        _section('左然对我的称呼', [
          _addressField(_userAddress),
          const Padding(
            padding: EdgeInsets.fromLTRB(2, 2, 2, 0),
            child: Text(
              '这个称呼会用于聊天和主动联系；左然会在自然需要时使用，不会每句话重复。',
              style: TextStyle(
                fontSize: 12,
                height: 1.45,
                color: Colors.black45,
              ),
            ),
          ),
        ]),
        _section('我的饮食偏好', [
          _dietField('喜欢吃什么', _dietLikes, '例如：面食、鱼、芝士蛋糕'),
          _dietField('忌口或过敏', _dietAvoid, '例如：不吃香菜、花生过敏'),
          _dietField('口味偏好', _dietTaste, '例如：少辣、少糖、清淡一点'),
          _dietField('其他习惯', _dietNotes, '例如：晚饭不想吃得太油腻'),
          const Text(
            '左然做饭或点餐时会参考这里的内容。可以随时修改，留空表示尚未填写。',
            style: TextStyle(fontSize: 12, height: 1.45, color: Colors.black45),
          ),
        ]),
        _section('主动联系', [
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            activeThumbColor: homeAccent,
            title: Text(
              '允许${_libraNickname.text.trim().isEmpty ? widget.libraNickname : _libraNickname.text.trim()}主动发消息',
            ),
            value: _proactiveEnabled,
            onChanged: (value) {
              setState(() => _proactiveEnabled = value);
              widget.onProactiveChanged(value);
            },
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('check-in 联系间隔'),
            subtitle: Text('每 $_minimumMinutes—$_maximumMinutes 分钟检查一次是否适合联系'),
            trailing: const Icon(Icons.chevron_right),
            onTap: _chooseInterval,
          ),
          const Divider(height: 24),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            activeThumbColor: homeAccent,
            title: const Text('天气变化提醒'),
            subtitle: const Text('降温、降雨等明显变化时，由左然判断是否提醒'),
            value: _weatherReminderEnabled,
            onChanged: _proactiveEnabled
                ? (value) => setState(() => _weatherReminderEnabled = value)
                : null,
          ),
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            activeThumbColor: homeAccent,
            title: const Text('动态变化报备'),
            subtitle: const Text('地点、通勤、工作或休息状态改变时，允许他自然分享'),
            value: _stateUpdateEnabled,
            onChanged: _proactiveEnabled
                ? (value) => setState(() => _stateUpdateEnabled = value)
                : null,
          ),
        ]),
        _section('权限设置', [
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: const Icon(
              Icons.calendar_month_outlined,
              color: homeAccent,
            ),
            title: const Text('系统日历权限'),
            subtitle: const Text('读取手机日程，用于日历和生活安排'),
            trailing: const Icon(Icons.chevron_right),
            onTap: widget.onCalendarPermission,
          ),
        ]),
      ],
    ),
  );

  Widget _dietField(
    String label,
    TextEditingController controller,
    String hint,
  ) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: controller,
      minLines: 1,
      maxLines: 3,
      maxLength: 500,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        counterText: '',
      ),
    ),
  );

  @override
  void dispose() {
    for (final controller in [
      _libraName,
      _userName,
      _libraNickname,
      _userNickname,
      _userAddress,
      _dietLikes,
      _dietAvoid,
      _dietTaste,
      _dietNotes,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  Widget _section(String title, List<Widget> children) => Container(
    margin: const EdgeInsets.only(bottom: 14),
    padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .78),
      borderRadius: BorderRadius.circular(20),
      border: Border.all(color: Colors.white),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            fontSize: 17,
            fontWeight: FontWeight.w600,
            color: homeAccent,
          ),
        ),
        const SizedBox(height: 8),
        ...children,
      ],
    ),
  );

  Widget _compactField(String label, TextEditingController controller) =>
      Container(
        height: 52,
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.symmetric(horizontal: 14),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF8F8),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0xFFF4E7E6)),
        ),
        child: Row(
          children: [
            SizedBox(
              width: 102,
              child: Text(
                label,
                style: const TextStyle(fontSize: 14, color: Color(0xFF756E6C)),
              ),
            ),
            Expanded(
              child: TextField(
                controller: controller,
                maxLength: 20,
                textAlign: TextAlign.end,
                decoration: const InputDecoration(
                  counterText: '',
                  border: InputBorder.none,
                  isDense: true,
                ),
              ),
            ),
          ],
        ),
      );

  Widget _addressField(TextEditingController controller) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: 8),
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
    decoration: BoxDecoration(
      color: const Color(0xFFFFF8F8),
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFF4E7E6)),
    ),
    child: TextField(
      controller: controller,
      maxLength: 100,
      minLines: 1,
      maxLines: 3,
      decoration: const InputDecoration(
        hintText: '夫人、老婆、宝宝、亲爱的',
        counterText: '',
        border: InputBorder.none,
        isDense: true,
      ),
    ),
  );

  Widget _avatarEditor(String label, ImageProvider image, VoidCallback onTap) =>
      InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Column(
            children: [
              CircleAvatar(radius: 38, backgroundImage: image),
              const SizedBox(height: 8),
              Text(label),
              const SizedBox(height: 2),
              const Text(
                '点击更换',
                style: TextStyle(fontSize: 12, color: homeAccent),
              ),
            ],
          ),
        ),
      );

  Future<void> _chooseInterval() async {
    const choices = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180];
    var minimum = choices.contains(_minimumMinutes) ? _minimumMinutes : 10;
    var maximum = choices.contains(_maximumMinutes) ? _maximumMinutes : 20;
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('联系间隔'),
          content: Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<int>(
                  initialValue: minimum,
                  decoration: const InputDecoration(labelText: '最短'),
                  items: choices
                      .map(
                        (value) => DropdownMenuItem(
                          value: value,
                          child: Text('$value 分钟'),
                        ),
                      )
                      .toList(),
                  onChanged: (v) => setDialogState(() {
                    minimum = v!;
                    if (maximum < minimum) maximum = minimum;
                  }),
                ),
              ),
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 10),
                child: Text('至'),
              ),
              Expanded(
                child: DropdownButtonFormField<int>(
                  initialValue: maximum,
                  decoration: const InputDecoration(labelText: '最长'),
                  items: choices
                      .where((value) => value >= minimum)
                      .map(
                        (value) => DropdownMenuItem(
                          value: value,
                          child: Text('$value 分钟'),
                        ),
                      )
                      .toList(),
                  onChanged: (v) => setDialogState(() => maximum = v!),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确定'),
            ),
          ],
        ),
      ),
    );
    if (accepted == true) {
      setState(() {
        _minimumMinutes = minimum;
        _maximumMinutes = maximum;
      });
    }
  }
}

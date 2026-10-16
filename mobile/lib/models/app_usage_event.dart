class AppUsageEvent {
  const AppUsageEvent({
    required this.timestamp,
    required this.action,
    required this.appName,
    this.customDescription,
  });

  final DateTime timestamp;
  final String action;
  final String appName;
  final String? customDescription;

  String get description =>
      customDescription ?? '${action == 'opened' ? '打开了' : '关闭了'}$appName';

  factory AppUsageEvent.fromMap(Map<Object?, Object?> map) {
    return AppUsageEvent(
      timestamp: DateTime.fromMillisecondsSinceEpoch(map['timestamp'] as int),
      action: map['action'] as String,
      appName: map['appName'] as String,
      customDescription: map['description'] as String?,
    );
  }

  factory AppUsageEvent.fromJson(Map<String, dynamic> json) => AppUsageEvent(
    timestamp: DateTime.parse(json['timestamp'] as String),
    action: json['action'] as String,
    appName: json['appName'] as String,
    customDescription: json['description'] as String?,
  );

  Map<String, dynamic> toJson() => {
    'timestamp': timestamp.toIso8601String(),
    'action': action,
    'appName': appName,
    'description': customDescription,
  };
}

import 'libra_api.dart';
import 'display_names.dart';

String movieProgressLabel(LifeActivityStatus activity) {
  String stamp(num seconds) {
    final value = seconds.toInt();
    return '${(value ~/ 3600).toString().padLeft(2, '0')}:'
        '${(value ~/ 60 % 60).toString().padLeft(2, '0')}:'
        '${(value % 60).toString().padLeft(2, '0')}';
  }

  final total = activity.total;
  if (total == null || total <= 0) return '正在观看《${activity.targetName}》';
  return '正在观看《${activity.targetName}》\n'
      '已看 ${stamp(activity.progress.clamp(0, total))} / ${stamp(total)}';
}

String coarseLifeStatusLabel(LifeSystemStatus status) {
  if (status.companionSessionId != null) return '陪伴中';
  if (status.sleepStatus == 'sleeping') return '睡觉中';
  return switch (status.coarseActivity?.kind) {
    'user_time' => DisplayNames.companionText(status.coarseActivity!.title),
    'working' || 'work' => '工作中',
    'commuting' || 'moving' || 'commute' => '通勤中',
    'eating' || 'meal' => '用餐中',
    'exercising' || 'exercise' => '运动中',
    'resting' || 'rest' => '休息中',
    'free' || 'leisure' => '放松中',
    _ => '空闲中',
  };
}

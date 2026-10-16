/// The companion's day is 04:00–04:00 in China Standard Time.
DateTime libraScheduleDay([DateTime? at]) {
  final local = (at ?? DateTime.now())
      .toUtc()
      .add(const Duration(hours: 8))
      .subtract(const Duration(hours: 4));
  return DateTime(local.year, local.month, local.day);
}

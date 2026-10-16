class WeatherSummary {
  const WeatherSummary({
    required this.city,
    required this.district,
    required this.latitude,
    required this.longitude,
    required this.temperature,
    required this.currentWeather,
    required this.tomorrowWeather,
    required this.tomorrowMin,
    required this.tomorrowMax,
    required this.reminder,
    required this.sunrise,
    required this.sunset,
    required this.isDaytime,
  });

  final String city;
  final String district;
  final double latitude;
  final double longitude;
  final int temperature;
  final String currentWeather;
  final String tomorrowWeather;
  final int tomorrowMin;
  final int tomorrowMax;
  final String reminder;
  final DateTime? sunrise;
  final DateTime? sunset;
  final bool isDaytime;

  factory WeatherSummary.fromJson(Map<String, dynamic> json) {
    int number(String key) => int.tryParse('${json[key]}') ?? 0;
    return WeatherSummary(
      city: '${json['city'] ?? ''}',
      district: '${json['district'] ?? ''}',
      latitude: double.tryParse('${json['latitude']}') ?? 0,
      longitude: double.tryParse('${json['longitude']}') ?? 0,
      temperature: number('temperature'),
      currentWeather: '${json['current_weather'] ?? ''}',
      tomorrowWeather: '${json['tomorrow_weather'] ?? ''}',
      tomorrowMin: number('tomorrow_min'),
      tomorrowMax: number('tomorrow_max'),
      reminder: '${json['reminder'] ?? ''}',
      sunrise: DateTime.tryParse('${json['sunrise'] ?? ''}'),
      sunset: DateTime.tryParse('${json['sunset'] ?? ''}'),
      isDaytime: json['is_daytime'] == true,
    );
  }
}

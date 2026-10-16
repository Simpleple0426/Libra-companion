import '../models/calendar_entry.dart';
import 'libra_api.dart';

class ImportantDatesStore {
  ImportantDatesStore(this._api);

  final LibraApi _api;
  static const _key = 'important_dates';

  Future<List<ImportantDate>> load() async {
    final value = await _api.getMobileState(_key);
    if (value is! List) return const [];
    final items = value
        .whereType<Map<String, dynamic>>()
        .map(
          (row) => ImportantDate(
            id: (row['id'] as num).toInt(),
            title: '${row['title']}',
            date: DateTime.parse('${row['date']}'),
            type: ImportantDateType.values.firstWhere(
              (type) => type.name == row['dateType'],
              orElse: () => ImportantDateType.yearly,
            ),
          ),
        )
        .toList();
    items.sort((a, b) => a.date.compareTo(b.date));
    return items;
  }

  Future<ImportantDate> save(ImportantDate item) async {
    final items = List<ImportantDate>.of(await load());
    final id =
        item.id ??
        items.fold<int>(
              0,
              (largest, value) => value.id! > largest ? value.id! : largest,
            ) +
            1;
    final saved = ImportantDate(
      id: id,
      title: item.title.trim(),
      date: item.date,
      type: item.type,
    );
    final index = items.indexWhere((value) => value.id == id);
    index < 0 ? items.add(saved) : items[index] = saved;
    await _write(items);
    return saved;
  }

  Future<void> delete(int id) async {
    final items = List<ImportantDate>.of(await load())
      ..removeWhere((item) => item.id == id);
    await _write(items);
  }

  Future<void> _write(List<ImportantDate> items) => _api.setMobileState(
    _key,
    items
        .map(
          (item) => {
            'id': item.id,
            'title': item.title,
            'date': item.date.toIso8601String(),
            'dateType': item.type.name,
          },
        )
        .toList(),
  );
}

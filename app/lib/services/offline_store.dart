import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../api/models.dart';

/// Device-local result cache. It stores provider responses, never invented
/// prices, and is deliberately independent from the configured server URL.
class OfflineStore {
  OfflineStore._(this._file);

  final File _file;

  static Future<OfflineStore> open({Directory? directory}) async {
    final root = directory ?? await getApplicationSupportDirectory();
    await root.create(recursive: true);
    return OfflineStore._(File('${root.path}/offer-cache-v1.json'));
  }

  Future<Map<String, dynamic>> _read() async {
    if (!await _file.exists()) return <String, dynamic>{};
    try {
      final decoded = jsonDecode(await _file.readAsString());
      return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    } on FormatException {
      return <String, dynamic>{};
    }
  }

  String key({
    required String postalCode,
    required String filterText,
    required String retailer,
    required String category,
    required int page,
    required String view,
    required List<String> loyalty,
    required String sort,
  }) => [
    postalCode,
    filterText,
    retailer,
    category,
    page,
    view,
    loyalty.join(','),
    sort,
  ].map((item) => Uri.encodeComponent('$item')).join('|');

  Future<void> save(String key, ResultPage page) async {
    final data = await _read();
    data[key] = {
      'saved_at': DateTime.now().toUtc().toIso8601String(),
      'page': page.toJson(),
    };
    final temporary = File('${_file.path}.tmp');
    await temporary.writeAsString(jsonEncode(data), flush: true);
    await temporary.rename(_file.path);
  }

  Future<ResultPage?> load(String key) async {
    final entry = (await _read())[key];
    if (entry is! Map || entry['page'] is! Map) return null;
    return ResultPage.fromJson(Map<String, dynamic>.from(entry['page'] as Map));
  }

  Future<bool> hasPostalCode(String postalCode) async {
    final prefix = '${Uri.encodeComponent(postalCode)}|';
    return (await _read()).keys.any((item) => item.startsWith(prefix));
  }
}

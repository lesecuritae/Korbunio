import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../api/models.dart';

class LocalShoppingListStore {
  LocalShoppingListStore._(this._file);
  final File _file;

  static Future<LocalShoppingListStore> open({Directory? directory}) async {
    final root = directory ?? await getApplicationSupportDirectory();
    await root.create(recursive: true);
    return LocalShoppingListStore._(File('${root.path}/shopping-list-v1.json'));
  }

  Future<List<Offer>> load() async {
    if (!await _file.exists()) return [];
    try {
      final decoded = jsonDecode(await _file.readAsString());
      if (decoded is! List) return [];
      return decoded
          .whereType<Map>()
          .map((item) => Offer.fromJson(Map<String, dynamic>.from(item)))
          .toList();
    } on FormatException {
      return [];
    }
  }

  Future<void> _write(List<Offer> offers) async {
    final temporary = File('${_file.path}.tmp');
    await temporary.writeAsString(
      jsonEncode(offers.map((offer) => offer.toJson()).toList()),
      flush: true,
    );
    await temporary.rename(_file.path);
  }

  Future<void> add(Offer offer) async {
    final offers = await load();
    if (offers.any((item) => item.key == offer.key)) return;
    offers.add(offer);
    await _write(offers);
  }

  Future<void> remove(String key) async {
    final offers = (await load())..removeWhere((offer) => offer.key == key);
    await _write(offers);
  }
}

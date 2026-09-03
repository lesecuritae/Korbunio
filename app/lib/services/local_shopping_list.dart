import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import '../api/models.dart';

class LocalShoppingListEntry {
  const LocalShoppingListEntry({required this.offer, required this.quantity});

  final Offer offer;
  final int quantity;

  double? get goodsTotal {
    final price = offer.effectivePrice ?? offer.regularPrice;
    return price == null ? null : price * quantity;
  }

  double get depositTotal => (offer.deposit ?? 0) * quantity;

  double? get lineTotal {
    final goods = goodsTotal;
    return goods == null ? null : goods + depositTotal;
  }
}

class LocalShoppingListStore {
  LocalShoppingListStore._(this._file);
  final File _file;

  static Future<LocalShoppingListStore> open({Directory? directory}) async {
    final root = directory ?? await getApplicationSupportDirectory();
    await root.create(recursive: true);
    return LocalShoppingListStore._(File('${root.path}/shopping-list-v1.json'));
  }

  Future<List<Offer>> load() async {
    return (await loadEntries()).map((entry) => entry.offer).toList();
  }

  Future<List<LocalShoppingListEntry>> loadEntries() async {
    if (!await _file.exists()) return [];
    try {
      final decoded = jsonDecode(await _file.readAsString());
      if (decoded is! List) return [];
      return decoded.whereType<Map>().map((item) {
        final values = Map<String, dynamic>.from(item);
        final rawQuantity = values['_quantity'];
        final quantity = rawQuantity is num ? rawQuantity.toInt() : 1;
        return LocalShoppingListEntry(
          offer: Offer.fromJson(values),
          quantity: quantity.clamp(1, 99),
        );
      }).toList();
    } on FormatException {
      return [];
    }
  }

  Future<void> _write(List<LocalShoppingListEntry> entries) async {
    final temporary = File('${_file.path}.tmp');
    await temporary.writeAsString(
      jsonEncode(
        entries
            .map(
              (entry) => {...entry.offer.toJson(), '_quantity': entry.quantity},
            )
            .toList(),
      ),
      flush: true,
    );
    await temporary.rename(_file.path);
  }

  Future<void> add(Offer offer) async {
    final entries = await loadEntries();
    if (entries.any((item) => item.offer.key == offer.key)) return;
    entries.add(LocalShoppingListEntry(offer: offer, quantity: 1));
    await _write(entries);
  }

  Future<void> setQuantity(String key, int quantity) async {
    final entries = await loadEntries();
    final index = entries.indexWhere((entry) => entry.offer.key == key);
    if (index < 0) return;
    entries[index] = LocalShoppingListEntry(
      offer: entries[index].offer,
      quantity: quantity.clamp(1, 99),
    );
    await _write(entries);
  }

  Future<void> remove(String key) async {
    final entries = (await loadEntries())
      ..removeWhere((entry) => entry.offer.key == key);
    await _write(entries);
  }
}

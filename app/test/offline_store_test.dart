import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/api/models.dart';
import 'package:korbklar_app/services/offline_store.dart';
import 'package:korbklar_app/services/local_shopping_list.dart';

void main() {
  test(
    'stores and restores provider results without changing prices',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'korbklar-offline-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final store = await OfflineStore.open(directory: directory);
      final key = store.key(
        postalCode: '26188',
        filterText: '',
        retailer: '',
        category: '',
        page: 1,
        view: 'best_only',
        loyalty: const [],
        sort: 'price',
      );
      final page = ResultPage.fromJson({
        'search_id': 'result-1',
        'postal_code': '26188',
        'page': 1,
        'page_count': 1,
        'offers': [
          {
            'retailer': 'Combi',
            'product': 'Butter',
            'regular_price': 1.99,
            'regular_price_text': '1,99 €',
          },
        ],
      });
      await store.save(key, page);
      final restored = await store.load(key);
      expect(restored, isNotNull);
      expect(restored!.postalCode, '26188');
      expect(restored.offers.single.product, 'Butter');
      expect(restored.offers.single.regularPrice, 1.99);
      expect(await store.hasPostalCode('26188'), isTrue);
    },
  );

  test(
    'local shopping list survives restart and preserves offer data',
    () async {
      final directory = await Directory.systemTemp.createTemp('korbklar-list-');
      addTearDown(() => directory.delete(recursive: true));
      final store = await LocalShoppingListStore.open(directory: directory);
      final offer = Offer.fromJson({
        'retailer': 'REWE',
        'product': 'Butter',
        'regular_price': 1.99,
        'regular_price_text': '1,99 €',
        'deposit': 0.25,
        'deposit_text': '0,25 €',
        'deposit_note': 'zzgl. 0,25 € Pfand',
      });
      await store.add(offer);
      await store.setQuantity(offer.key, 3);
      final reopened = await LocalShoppingListStore.open(directory: directory);
      expect((await reopened.load()).single.regularPrice, 1.99);
      final entry = (await reopened.loadEntries()).single;
      expect(entry.quantity, 3);
      expect(entry.goodsTotal, closeTo(5.97, 0.001));
      expect(entry.depositTotal, closeTo(0.75, 0.001));
      expect(entry.lineTotal, closeTo(6.72, 0.001));
      await reopened.remove(offer.key);
      expect(await reopened.load(), isEmpty);
    },
  );
}

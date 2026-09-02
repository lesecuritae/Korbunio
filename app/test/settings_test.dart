import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/services/settings.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('selected retailers persist locally', () async {
    SharedPreferences.setMockInitialValues({});
    final settings = await Settings.load();
    expect(settings.hasSelectedRetailers, isFalse);

    await settings.setSelectedRetailers(['REWE', 'dm']);

    final reloaded = await Settings.load();
    expect(reloaded.selectedRetailers, ['REWE', 'dm']);
    expect(reloaded.hasSelectedRetailers, isTrue);
  });

  test('starting straight into the results is the default', () async {
    SharedPreferences.setMockInitialValues({});
    final settings = await Settings.load();
    expect(settings.autoStart, isTrue);
    await settings.setAutoStart(false);
    expect((await Settings.load()).autoStart, isFalse);
  });

  test(
    'the last search survives a restart and knows what it covered',
    () async {
      SharedPreferences.setMockInitialValues({});
      final settings = await Settings.load();
      expect(settings.lastSearch, isNull);

      final searchedAt = DateTime(2026, 9, 1, 9, 30);
      await settings.setLastSearch(
        LastSearch(
          postalCode: '26188',
          retailers: const ['REWE', 'Lidl'],
          searchId: 'search-1',
          token: 'signed',
          searchedAt: searchedAt,
        ),
      );

      final last = (await Settings.load()).lastSearch;
      expect(last, isNotNull);
      expect(last!.handle.searchId, 'search-1');
      expect(last.handle.token, 'signed');
      expect(last.searchedAt, searchedAt);
      expect(last.matches('26188', const ['REWE', 'Lidl']), isTrue);
      // A different postal code or retailer selection is a different search.
      expect(last.matches('26123', const ['REWE', 'Lidl']), isFalse);
      expect(last.matches('26188', const []), isFalse);

      await settings.clearLastSearch();
      expect((await Settings.load()).lastSearch, isNull);
    },
  );

  test('an incomplete stored search is ignored rather than opened', () async {
    SharedPreferences.setMockInitialValues({'last_search_id': 'search-1'});
    expect((await Settings.load()).lastSearch, isNull);
  });
}

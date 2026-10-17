import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korbunio_app/api/models.dart';
import 'package:korbunio_app/screens/local_shopping_list_screen.dart';
import 'package:korbunio_app/services/local_shopping_list.dart';

/// Tests render with a placeholder font in which every character is a square,
/// so text is far wider than on a phone. Load Roboto from the Flutter SDK so
/// that layout results match a real device.
Future<void> _loadRealFonts() async {
  final root = Platform.environment['FLUTTER_ROOT'] ?? '/opt/flutter';
  final dir = Directory('$root/bin/cache/artifacts/material_fonts');
  for (final entry in {
    'Roboto': ['Roboto-Regular.ttf', 'Roboto-Medium.ttf', 'Roboto-Bold.ttf'],
    'MaterialIcons': ['MaterialIcons-Regular.otf'],
  }.entries) {
    final loader = FontLoader(entry.key);
    for (final name in entry.value) {
      final file = File('${dir.path}/$name');
      if (file.existsSync()) {
        loader.addFont(
          file.readAsBytes().then((bytes) => ByteData.view(bytes.buffer)),
        );
      }
    }
    await loader.load();
  }
}

Offer _offer(String retailer, String product, String price) => Offer.fromJson({
  'retailer': retailer,
  'retailer_label': retailer,
  'product': product,
  'regular_price': double.parse(price.replaceAll(',', '.')),
  'regular_price_text': '$price €',
  'effective_price': double.parse(price.replaceAll(',', '.')),
  'effective_price_text': '$price €',
  'pack': '500 g',
});

Future<LocalShoppingListStore> _store(WidgetTester tester) async {
  late Directory root;
  late LocalShoppingListStore store;
  await tester.runAsync(() async {
    root = await Directory.systemTemp.createTemp('korbunio-list-screen-');
    store = await LocalShoppingListStore.open(directory: root);
    await store.add(_offer('REWE', 'Nutella Nuss-Nougat-Creme', '3,49'));
    await store.add(_offer('Lidl', 'Vollmilch 1,5 % Fett frische', '1,19'));
  });
  addTearDown(() => root.delete(recursive: true));
  return store;
}

/// File access completes on the real event loop while widgets run on fake
/// time, so alternate the two until the screen has finished loading.
Future<void> _settle(WidgetTester tester) async {
  for (var round = 0; round < 30; round++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 20)),
    );
    await tester.pump();
  }
  await tester.pumpAndSettle();
}

Future<void> _pump(
  WidgetTester tester,
  LocalShoppingListStore store, {
  Size size = const Size(360, 740),
  double textScale = 1.0,
}) async {
  tester.view.physicalSize = size * 2;
  tester.view.devicePixelRatio = 2;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      theme: ThemeData(fontFamily: 'Roboto'),
      home: MediaQuery(
        data: MediaQueryData(
          size: size,
          devicePixelRatio: 2,
          textScaler: TextScaler.linear(textScale),
        ),
        child: LocalShoppingListScreen(store: store),
      ),
    ),
  );
  await _settle(tester);
}

// Tooltips can temporarily outlive a removed row in an overlay (e.g. after a
// synthetic touch/hover on small displays). Assert and tap the actual controls;
// the persistent-store assertions below still verify that removal succeeded.
Finder get _removeButtons => find.byWidgetPredicate(
  (widget) => widget is IconButton && widget.tooltip == 'Entfernen',
  description: 'shopping-list remove IconButton',
);

void main() {
  setUpAll(_loadRealFonts);

  for (final scenario in [
    (name: '360dp', size: const Size(360, 740), scale: 1.0),
    (name: '320dp, Schrift 1,5x', size: const Size(320, 640), scale: 1.5),
  ]) {
    testWidgets('list shows retailer and stays operable at ${scenario.name}', (
      tester,
    ) async {
      final store = await _store(tester);
      await _pump(
        tester,
        store,
        size: scenario.size,
        textScale: scenario.scale,
      );

      // No layout overflow.
      expect(tester.takeException(), isNull);
      // Each entry names its retailer as its own visible text.
      expect(find.text('REWE'), findsWidgets);
      expect(find.text('Lidl'), findsWidgets);
      // Every entry has a reachable delete control.
      expect(_removeButtons, findsNWidgets(2));
    });

    testWidgets('an entry can be deleted at ${scenario.name}', (tester) async {
      final store = await _store(tester);
      await _pump(
        tester,
        store,
        size: scenario.size,
        textScale: scenario.scale,
      );

      await tester.ensureVisible(_removeButtons.first);
      await tester.tap(_removeButtons.first);
      await _settle(tester);

      expect(tester.takeException(), isNull);
      expect(_removeButtons, findsOneWidget);
      final remaining = await tester.runAsync(store.loadEntries);
      expect(remaining, hasLength(1));
    });
  }

  testWidgets('the whole list can be cleared after confirming', (tester) async {
    final store = await _store(tester);
    await _pump(tester, store);

    await tester.tap(find.byTooltip('Liste leeren'));
    await tester.pumpAndSettle();
    expect(find.text('Liste leeren?'), findsOneWidget);
    await tester.tap(find.text('Leeren'));
    await _settle(tester);

    expect(find.text('Die lokale Einkaufsliste ist leer.'), findsOneWidget);
    expect(await tester.runAsync(store.loadEntries), isEmpty);
  });

  testWidgets('a removed entry can be restored with undo', (tester) async {
    final store = await _store(tester);
    await _pump(tester, store);

    await tester.tap(_removeButtons.first);
    await _settle(tester);
    expect(find.text('Rückgängig'), findsOneWidget);

    await tester.tap(find.text('Rückgängig'));
    await _settle(tester);

    expect(_removeButtons, findsNWidgets(2));
    expect(await tester.runAsync(store.loadEntries), hasLength(2));
  });
}

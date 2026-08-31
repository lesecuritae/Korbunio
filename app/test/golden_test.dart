@Tags(['golden'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:korbklar_app/api/client.dart';
import 'package:korbklar_app/screens/results_screen.dart';
import 'package:korbklar_app/services/offline_store.dart';
import 'package:korbklar_app/services/local_shopping_list.dart';
import 'package:korbklar_app/theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:korbklar_app/services/settings.dart';

/// Renders the result list headlessly so its layout and palette can be
/// reviewed without a device.
///
/// ```bash
/// flutter test --tags golden --update-goldens
/// ```
/// Golden images render with a placeholder font unless a real face is loaded,
/// which would make the result impossible to review. Roboto ships with the
/// Flutter SDK, so it is loaded here when available.
Future<void> _loadRealFonts() async {
  final root = Platform.environment['FLUTTER_ROOT'];
  if (root == null) return;
  final dir = Directory('$root/bin/cache/artifacts/material_fonts');
  if (!dir.existsSync()) return;

  for (final entry in {
    'Roboto': ['roboto-regular.ttf', 'roboto-medium.ttf', 'roboto-bold.ttf'],
    // Without this the goldens show every icon as an empty box.
    'MaterialIcons': ['materialicons-regular.otf'],
  }.entries) {
    final loader = FontLoader(entry.key);
    var loaded = false;
    for (final name in entry.value) {
      final file = File('${dir.path}/$name');
      if (!file.existsSync()) continue;
      loader.addFont(
        file.readAsBytes().then((bytes) => ByteData.view(bytes.buffer)),
      );
      loaded = true;
    }
    if (loaded) await loader.load();
  }
}

void main() {
  const page = {
    'search_id': 'demo',
    'postal_code': '26188',
    'cache_age_seconds': 120,
    'source_offer_count': 1926,
    'filtered_offer_count': 1926,
    'hidden_count': 412,
    'page': 1,
    'page_count': 20,
    'has_next': false,
    'retailer': '',
    'view': 'best_only',
    'retailer_counts': {
      'Combi': 216,
      'famila Nordwest': 289,
      'REWE': 209,
      'Lidl': 193,
    },
    'category_counts': {'Butter': 12},
    'selected_loyalty_programs': <String>[],
    'available_loyalty_programs': [
      {
        'id': 'rewe_bonus',
        'label': 'REWE Bonus',
        'note': 'Nur konkrete Euro-Vorteile.',
      },
    ],
    'loyalty_note':
        'Es werden nur öffentlich ausgewiesene Direktpreise verrechnet.',
    'warnings': ['Kaufland offiziell: keine Filialseite'],
    'offers': [
      {
        'retailer': 'Combi',
        'retailers': ['Combi', 'famila Nordwest'],
        'retailer_label': 'Combi · famila Nordwest',
        'category': 'Molkereiprodukte',
        'product': 'Kerrygold Original Irische Butter',
        'description': 'mild gesalzen oder original',
        'regular_price': 2.29,
        'regular_price_text': '2,29 €',
        'regular_comparison': 'günstigster Treffer',
        'regular_comparison_state': 'best',
        'checkout_price_text': '1,59 €',
        'effective_price': 1.59,
        'effective_price_text': '1,59 €',
        'selected_comparison': '0,70 € unter dem nächsten Angebot',
        'selected_comparison_state': 'best',
        'loyalty_savings': 0.70,
        'loyalty_savings_text': '0,70 €',
        'loyalty_benefit': 'REWE Bonus: 1,59 €',
        'pack': '250 g',
        'unit_price': '6,36 €/kg',
        'selected_unit_price': '',
        'validity': '24.08.–29.08.2026',
        'image_url': '',
        'source_url': 'https://www.marktguru.de/r/famila-nordwest',
      },
      {
        'retailer': 'Combi',
        'retailers': ['Combi'],
        'retailer_label': 'Combi',
        'category': 'Obst & Gemüse',
        'product': 'Deutsche Erdbeeren',
        'description': 'Klasse I, Schale',
        'regular_price': 1.99,
        'regular_price_text': '1,99 €',
        'regular_comparison': '',
        'regular_comparison_state': 'none',
        'checkout_price_text': '1,99 €',
        'effective_price': 1.99,
        'effective_price_text': '1,99 €',
        'selected_comparison': '',
        'selected_comparison_state': 'none',
        'loyalty_savings': 0.0,
        'loyalty_savings_text': '',
        'loyalty_benefit': '',
        'pack': '500 g',
        'unit_price': '3,98 €/kg',
        'selected_unit_price': '',
        'validity': '24.08.–26.08.2026',
        'image_url': '',
        'source_url': 'https://www.marktguru.de/r/combi',
      },
      {
        'retailer': 'REWE',
        'category': 'Getränke',
        'product': 'Coca-Cola versch. Sorten',
        'description': '1,25 l Flasche zzgl. Pfand',
        'regular_price': 1.29,
        'regular_price_text': '1,29 €',
        'regular_comparison': '',
        'regular_comparison_state': 'none',
        'checkout_price_text': '1,29 €',
        'effective_price': 1.29,
        'effective_price_text': '1,29 €',
        'selected_comparison': '',
        'selected_comparison_state': 'none',
        'loyalty_savings': 0.0,
        'loyalty_savings_text': '',
        'loyalty_benefit': '',
        'pack': '1.25l',
        'unit_price': '1,03 €/l',
        'selected_unit_price': '',
        'validity': '24.08.–30.08.2026',
        'image_url': '',
        'source_url': 'https://www.rewe.de/marktsuche',
      },
    ],
  };

  setUpAll(_loadRealFonts);

  Future<void> pumpResults(WidgetTester tester, Brightness brightness) async {
    SharedPreferences.setMockInitialValues({});
    final settings = await Settings.load();
    final offlineStore = await OfflineStore.open(
      directory: await Directory.systemTemp.createTemp('korbklar-golden-'),
    );
    final localShoppingList = await LocalShoppingListStore.open(
      directory: await Directory.systemTemp.createTemp('korbklar-list-golden-'),
    );
    final client = KorbKlarClient(
      baseUrl: 'http://korb.example',
      httpClient: _StubClient(page),
    );
    await tester.pumpWidget(
      MaterialApp(
        theme:
            (brightness == Brightness.dark ? korbDarkTheme() : korbLightTheme())
                .copyWith(
                  textTheme: ThemeData(
                    brightness: brightness,
                  ).textTheme.apply(fontFamily: 'Roboto'),
                ),
        home: ResultsScreen(
          client: client,
          handle: const ResultHandle(searchId: 'demo', token: 'token'),
          settings: settings,
          offlineStore: offlineStore,
          localShoppingList: localShoppingList,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('results screen, light', (tester) async {
    tester.view.physicalSize = const Size(375 * 3, 812 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await pumpResults(tester, Brightness.light);
    await expectLater(
      find.byType(ResultsScreen),
      matchesGoldenFile('goldens/results_light.png'),
    );
  });

  testWidgets('results screen, dark', (tester) async {
    tester.view.physicalSize = const Size(375 * 3, 812 * 3);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.reset);
    await pumpResults(tester, Brightness.dark);
    await expectLater(
      find.byType(ResultsScreen),
      matchesGoldenFile('goldens/results_dark.png'),
    );
  });
}

/// Answers every request with the same fixed page.
class _StubClient extends http.BaseClient {
  _StubClient(this.page);

  final Map<String, Object?> page;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final body = request.url.path.contains('shopping-list')
        ? {
            'configured': true,
            'targets': [
              {'entity_id': '4', 'label': 'Einkauf'},
            ],
            'default_entity': '4',
          }
        : page;
    return http.StreamedResponse(
      Stream.value(utf8.encode(jsonEncode(body))),
      200,
    );
  }
}

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:korbunio_app/api/client.dart';
import 'package:korbunio_app/screens/results_screen.dart';
import 'package:korbunio_app/services/local_shopping_list.dart';
import 'package:korbunio_app/services/offline_store.dart';
import 'package:korbunio_app/services/settings.dart';
import 'package:korbunio_app/theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, Object?> _offer(String category, String product, double price) => {
  'retailer': 'REWE',
  'retailers': ['REWE'],
  'retailer_label': 'REWE',
  'category': category,
  'product': product,
  'description': '',
  'regular_price': price,
  'regular_price_text': '$price €',
  'regular_comparison': '',
  'regular_comparison_state': 'none',
  'checkout_price_text': '$price €',
  'effective_price': price,
  'effective_price_text': '$price €',
  'selected_comparison': '',
  'selected_comparison_state': 'none',
  'loyalty_savings': 0.0,
  'loyalty_savings_text': '',
  'loyalty_benefit': '',
  'pack': '',
  'unit_price': '',
  'selected_unit_price': '',
  'validity': '14.09.–20.09.2026',
  'image_url': '',
  'source_url': 'https://www.rewe.de/',
};

/// Answers every request with the same result page and remembers the paths.
class _Stub extends http.BaseClient {
  _Stub(this.page);

  final Map<String, Object?> page;
  final requests = <http.BaseRequest>[];

  /// The last request for the result page (the app also asks for shopping-list targets).
  String get lastResults => requests
      .lastWhere((r) => !r.url.path.contains('shopping-list'))
      .url
      .toString();

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests.add(request);
    return http.StreamedResponse(
      Stream.value(utf8.encode(jsonEncode(page))),
      200,
    );
  }
}

void main() {
  final page = <String, Object?>{
    'search_id': 'demo',
    'postal_code': '45127',
    'cache_age_seconds': 60,
    'source_offer_count': 3,
    'filtered_offer_count': 3,
    'hidden_count': 0,
    'page': 1,
    'page_count': 1,
    'has_next': false,
    'retailer': '',
    'view': 'best_only',
    'retailer_counts': {'REWE': 3},
    'category_counts': {'Getränke': 1, 'Obst & Gemüse': 2},
    'selected_loyalty_programs': <String>[],
    'available_loyalty_programs': <Object>[],
    'loyalty_note': '',
    'warnings': <String>[],
    'offers': [
      _offer('Obst & Gemüse', 'Feigen', 0.29),
      _offer('Obst & Gemüse', 'Kohlrabi', 0.49),
      _offer('Getränke', 'Apfelsaft', 0.99),
    ],
  };

  // The screen writes every page to the offline store, which is real file
  // access; it only finishes on the real event loop. So real time passes
  // between the frames instead of waiting for a settle that could hang.
  Future<void> settle(WidgetTester tester) async {
    for (var i = 0; i < 20; i++) {
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 40)),
      );
      await tester.pump(const Duration(milliseconds: 50));
    }
  }

  Future<_Stub> pump(
    WidgetTester tester, {
    Size size = const Size(900, 1600),
    double bottomInset = 0,
  }) async {
    tester.view.physicalSize = size * 2;
    tester.view.devicePixelRatio = 2;
    tester.view.padding = FakeViewPadding(bottom: bottomInset * 2);
    tester.view.viewPadding = FakeViewPadding(bottom: bottomInset * 2);
    addTearDown(tester.view.reset);
    SharedPreferences.setMockInitialValues({});
    final stub = _Stub(page);
    // Real file access needs the real event loop, not the test's fake one.
    final deps = (await tester.runAsync(() async {
      return (
        await Settings.load(),
        await OfflineStore.open(
          directory: await Directory.systemTemp.createTemp('korbuino-groups-'),
        ),
        await LocalShoppingListStore.open(
          directory: await Directory.systemTemp.createTemp('korbuino-list-'),
        ),
      );
    }))!;
    await tester.pumpWidget(
      MaterialApp(
        theme: korbLightTheme(),
        home: ResultsScreen(
          client: KorbunioClient(
            baseUrl: 'http://korb.example',
            httpClient: stub,
          ),
          handle: const ResultHandle(searchId: 'demo', token: 'token'),
          settings: deps.$1,
          offlineStore: deps.$2,
          localShoppingList: deps.$3,
        ),
      ),
    );
    await settle(tester);
    return stub;
  }

  testWidgets('the product groups are tabs in the shop order', (tester) async {
    await pump(tester);

    expect(find.text('Alle Warengruppen · 3'), findsOneWidget);
    expect(find.text('Obst & Gemüse · 2'), findsOneWidget);
    expect(find.text('Getränke · 1'), findsOneWidget);
    // Produce comes before drinks, whatever order the server listed them in.
    expect(
      tester.getTopLeft(find.text('Obst & Gemüse · 2')).dx,
      lessThan(tester.getTopLeft(find.text('Getränke · 1')).dx),
    );
  });

  testWidgets('picking a group asks the server for just that group', (
    tester,
  ) async {
    final stub = await pump(tester);

    await tester.tap(find.text('Getränke · 1'));
    await settle(tester);

    expect(
      stub.lastResults.contains('category=Getr'),
      isTrue,
      reason: stub.lastResults,
    );
  });

  testWidgets('sorted by product group the list shows collapsible sections', (
    tester,
  ) async {
    final stub = await pump(tester);

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await settle(tester);
    await tester.tap(find.text('Warengruppe (Abschnitte)').last);
    await settle(tester);

    expect(stub.lastResults, contains('sort=category'));
    // One heading per group, and the offers below them.
    expect(find.text('Obst & Gemüse · 2'), findsNWidgets(2));
    expect(find.text('Feigen'), findsOneWidget);

    // Tapping the heading (the one below the tab bar) hides its offers.
    await tester.tap(find.text('Obst & Gemüse · 2').last);
    await settle(tester);
    expect(find.text('Feigen'), findsNothing);
    expect(find.text('Kohlrabi'), findsNothing);
    expect(find.text('Apfelsaft'), findsOneWidget);
  });

  testWidgets('the last offer scrolls clear of the system navigation bar', (
    tester,
  ) async {
    const navBar = 48.0; // three-button navigation
    const height = 420.0;
    await pump(tester, size: const Size(360, height), bottomInset: navBar);

    await tester.drag(find.byType(Scrollable).last, const Offset(0, -3000));
    await settle(tester);

    // Everything in the list, the footer line included, not just the cards.
    final lowest = find
        .descendant(
          of: find.byType(Scrollable).last,
          matching: find.byType(Text),
        )
        .evaluate()
        .map((e) => tester.getBottomLeft(find.byWidget(e.widget)).dy)
        .reduce((a, b) => a > b ? a : b);
    expect(
      lowest,
      lessThanOrEqualTo(height - navBar + 0.5),
      reason:
          'the last list entry ends at $lowest dp, under the ${navBar}dp nav bar',
    );
  });
}

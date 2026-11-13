import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korbunio_app/api/models.dart';
import 'package:korbunio_app/theme.dart';
import 'package:korbunio_app/widgets/offer_card.dart';

Offer _offer() => Offer.fromJson({
  'retailer': 'REWE',
  'retailer_label': 'REWE',
  'product': 'Nutella',
  'regular_price': 3.49,
  'regular_price_text': '3,49 €',
  'pack': '450 g',
});

Future<void> _pump(WidgetTester tester, {required bool onLocalList}) =>
    tester.pumpWidget(
      MaterialApp(
        theme: korbLightTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: OfferCard(
              offer: _offer(),
              imageUrl: null,
              imageHeaders: const {},
              showRetailer: true,
              filedIn: null,
              sending: false,
              onAddToList: () {},
              onOpenSource: () {},
              onLocalList: onLocalList,
            ),
          ),
        ),
      ),
    );

void main() {
  testWidgets('an offer not yet listed offers to add it', (tester) async {
    await _pump(tester, onLocalList: false);
    expect(find.text('Zur Einkaufsliste'), findsOneWidget);
    expect(find.text('Von Liste entfernen'), findsNothing);
  });

  testWidgets('an offer already on the local list offers to remove it', (
    tester,
  ) async {
    await _pump(tester, onLocalList: true);
    expect(find.text('Von Liste entfernen'), findsOneWidget);
    expect(find.text('Zur Einkaufsliste'), findsNothing);
  });

  group('KitchenOwl button', () {
    Future<void> pumpKitchen(
      WidgetTester tester, {
      String? filedIn,
      VoidCallback? onRemove,
      VoidCallback? onAdd,
    }) => tester.pumpWidget(
      MaterialApp(
        theme: korbLightTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: OfferCard(
              offer: _offer(),
              imageUrl: null,
              imageHeaders: const {},
              showRetailer: true,
              filedIn: filedIn,
              sending: false,
              onAddToList: () {},
              onOpenSource: () {},
              onAddToKitchenOwl: onAdd ?? () {},
              onRemoveFromKitchenOwl: onRemove,
            ),
          ),
        ),
      ),
    );

    testWidgets('a filed offer can be removed when the app may do so', (
      tester,
    ) async {
      var removed = false;
      await pumpKitchen(
        tester,
        filedIn: 'Nutella',
        onRemove: () => removed = true,
      );
      expect(find.text('Aus KitchenOwl entfernen'), findsOneWidget);
      await tester.tap(find.text('Aus KitchenOwl entfernen'));
      expect(removed, isTrue);
    });

    testWidgets('without that ability a filed offer stays a static mark', (
      tester,
    ) async {
      await pumpKitchen(tester, filedIn: 'Nutella');
      expect(find.text('in Nutella'), findsOneWidget);
      final button = tester.widget<TextButton>(
        find.ancestor(
          of: find.text('in Nutella'),
          matching: find.byType(TextButton),
        ),
      );
      expect(button.onPressed, isNull);
    });

    testWidgets('an unfiled offer offers to file it', (tester) async {
      await pumpKitchen(tester);
      expect(find.text('Auf KitchenOwl'), findsOneWidget);
    });
  });
}

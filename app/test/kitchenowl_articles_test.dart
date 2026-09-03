import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/api/models.dart';
import 'package:korbklar_app/services/kitchenowl_articles.dart';

Offer _offer({
  String product = '',
  String retailer = '',
  String price = '',
  String validity = '',
  String pack = '',
}) => Offer.fromJson({
  'product': product,
  'retailer': retailer,
  'effective_price_text': price,
  'validity': validity,
  'pack': pack,
  'unit_price': '9,99 €/kg',
});

void main() {
  const catalogue = [
    'Brötchen',
    'Butter',
    'Bio Butter',
    'Milch',
    'Joghurt',
    'Ei',
  ];

  group('matching the household catalogue', () {
    test('an offer lands on the article the household already keeps', () {
      // German puts the head noun last, so this is what Brötchen is.
      expect(
        matchExistingItem('GUT&GÜNSTIG Weizenbrötchen / Schrippen', catalogue),
        'Brötchen',
      );
      expect(
        matchExistingItem('Müller Joghurt mit der Ecke', catalogue),
        'Joghurt',
      );
    });

    test('the more specific article wins', () {
      expect(
        matchExistingItem('Kerrygold Bio Butter 250g', catalogue),
        'Bio Butter',
      );
    });

    test('a compound is not matched by its first half', () {
      // Buttermilch is milk, not butter; only the head noun may match.
      expect(matchExistingItem('Buttermilch 500g', catalogue), 'Milch');
    });

    test('a compound still beats its head noun', () {
      expect(
        matchExistingItem('ja! Buttermilch 1 l', ['Milch', 'Buttermilch']),
        'Buttermilch',
      );
    });

    test('very short articles never match', () {
      // "Ei" would otherwise swallow half a catalogue.
      expect(matchExistingItem('Eis am Stiel', catalogue), '');
    });

    test('an unknown product keeps its own name', () {
      expect(matchExistingItem('Nektarinen', catalogue), '');
    });

    test('an earlier headline in the catalogue does not win', () {
      // Being the longest match for the very offer that created it, it
      // would beat the household's own article every time.
      expect(
        matchExistingItem('GUT&GÜNSTIG Weizenbrötchen / Schrippen', [
          'Brötchen',
          'GUT&GÜNSTIG Weizenbrötchen / Schrippen',
        ]),
        'Brötchen',
      );
    });
  });

  group('shortening the leaflet wording', () {
    for (final (product, expected) in const [
      ('GUT&GÜNSTIG Weizenbrötchen / Schrippen', 'Weizenbrötchen'),
      ('JA! Weizenbrötchen 6 Stück', 'Weizenbrötchen'),
      ('REWE Beste Wahl Orangen 1,5 kg', 'Beste Wahl Orangen'),
      ('Bio Rinderhackfleisch aus der Region 400 g', 'Bio Rinderhackfleisch'),
      ('Joghurt mild versch. Sorten 500 g', 'Joghurt mild'),
      ('Coca-Cola 1,25 l', 'Coca-Cola'),
      // Two plain words are already an article name.
      ('Kerrygold Butter', 'Kerrygold Butter'),
      ('Eier', 'Eier'),
    ]) {
      test('"$product" becomes "$expected"', () {
        expect(shortenOfferName(product), expected);
      });
    }
  });

  group('article and note', () {
    test('a matched article keeps the offer wording in the note', () {
      final offer = _offer(
        product: 'JA! Weizenbrötchen 6 Stück',
        retailer: 'REWE',
        price: '0,99 €',
        validity: '01.09.–06.09.2026',
        pack: '6 Stück',
      );
      final article = articleFor(offer, catalogue);
      expect(article, 'Brötchen');
      expect(
        noteFor(offer, article),
        'JA! Weizenbrötchen 6 Stück · 0,99 € · 01.09.–06.09.2026',
      );
    });

    test('the note is offer, price and validity, nothing else', () {
      // Pack size and unit price are deliberately left out.
      final offer = _offer(
        product: 'Kerrygold Butter',
        retailer: 'REWE',
        price: '1,59 €',
        validity: 'bis 03.09.',
        pack: '250 g',
      );
      final article = articleFor(offer, const []);
      expect(article, 'Kerrygold Butter');
      expect(noteFor(offer, article), '1,59 € · bis 03.09.');
    });

    test('a nameless offer is still filed', () {
      expect(articleFor(_offer(retailer: 'Lidl'), const []), 'Angebot Lidl');
    });
  });

  group('retailer categories', () {
    test('known shops get their colour, others a basket', () {
      expect(retailerCategory('REWE'), '🔴 REWE');
      expect(retailerCategory('ALDI Nord'), '🔵 ALDI Nord');
      expect(retailerCategory('Netto schwarz'), '⚫ Netto schwarz');
      expect(retailerCategory('Bäcker Meier'), '🛒 Bäcker Meier');
    });

    test('no retailer, no category', () {
      expect(retailerCategory('  '), '');
    });
  });
}

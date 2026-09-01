import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:korbklar_app/api/client.dart';
import 'package:korbklar_app/api/kitchenowl_client.dart';
import 'package:korbklar_app/api/models.dart';
import 'package:korbklar_app/services/shopping_list.dart';

void main() {
  group('normalizeBaseUrl', () {
    test('accepts what a user actually types', () {
      expect(
        KorbKlarClient.normalizeBaseUrl('192.0.2.10:8000'),
        'http://192.0.2.10:8000',
      );
      expect(
        KorbKlarClient.normalizeBaseUrl('  http://host:8000/  '),
        'http://host:8000',
      );
      expect(
        KorbKlarClient.normalizeBaseUrl('https://korb.example/'),
        'https://korb.example',
      );
      expect(KorbKlarClient.normalizeBaseUrl(''), '');
    });
  });

  group('connection security', () {
    test('never sends a KorbKlar token over plain HTTP', () {
      expect(
        KorbKlarClient.connectionSecurityError('http://korb.example', 'secret'),
        isNotNull,
      );
      expect(
        KorbKlarClient.connectionSecurityError(
          'https://korb.example',
          'secret',
        ),
        isNull,
      );
      expect(
        KorbKlarClient.connectionSecurityError('http://192.168.1.2:8000', ''),
        isNull,
      );
    });

    test('exchanges an admin key for a separate app token', () async {
      late http.Request request;
      final client = KorbKlarClient(
        baseUrl: 'https://korb.example',
        apiKey: 'admin-secret',
        httpClient: MockClient((incoming) {
          request = incoming as http.Request;
          return http.Response(
            jsonEncode({'token': 'personal-app-token'}),
            200,
          );
        }),
      );
      expect(await client.createAppToken(), 'personal-app-token');
      expect(request.url.path, '/api/v1/access-tokens');
      expect(request.headers['Authorization'], 'Bearer admin-secret');
      expect(jsonDecode(request.body)['label'], 'KorbKlar Android');
    });
  });

  test('search sends the locally selected retailers to the server', () async {
    late http.Request request;
    final client = KorbKlarClient(
      baseUrl: 'https://korb.example',
      httpClient: MockClient((incoming) {
        request = incoming as http.Request;
        return http.Response(jsonEncode({'job_id': 'job-1'}), 200);
      }),
    );
    addTearDown(client.close);

    expect(
      await client.startSearch('06108', retailers: ['REWE', 'dm']),
      'job-1',
    );
    expect(request.url.path, '/api/v1/search/jobs');
    expect(jsonDecode(request.body)['retailers'], ['REWE', 'dm']);
  });

  group('direct KitchenOwl transfer', () {
    test('discovers lists and transfers the real offer fields', () async {
      final requests = <http.BaseRequest>[];
      final client = KitchenOwlClient(
        baseUrl: 'https://owl.example',
        token: 'long-lived',
        httpClient: MockClient((request) {
          requests.add(request);
          if (request.url.path == '/api/household') {
            return http.Response(
              jsonEncode([
                {'id': 7, 'name': 'Zuhause'},
              ]),
              200,
            );
          }
          if (request.url.path == '/api/household/7/shoppinglist') {
            return http.Response(
              jsonEncode([
                {'id': 12, 'name': 'Einkauf'},
              ]),
              200,
            );
          }
          if (request.url.path == '/api/shoppinglist/12/add-item-by-name') {
            return http.Response(jsonEncode({'id': 99}), 200);
          }
          return http.Response('{}', 404);
        }),
      );
      final targets = await client.targets();
      expect(targets.single.entityId, '12');
      expect(targets.single.label, 'Zuhause · Einkauf');
      final offer = Offer.fromJson({
        'product': 'Kerrygold Butter',
        'retailer': 'REWE',
        'effective_price_text': '1,59 €',
        'pack': '250 g',
        'validity': 'bis 03.09.',
      });
      expect(await client.addOffer('12', offer), 'Kerrygold Butter');
      final post = requests.last as http.Request;
      expect(post.headers['Authorization'], 'Bearer long-lived');
      final payload = jsonDecode(post.body) as Map<String, dynamic>;
      expect(payload['name'], 'Kerrygold Butter');
      expect(payload['description'], contains('REWE'));
      expect(payload['description'], contains('1,59 €'));
    });

    test('rejects direct KitchenOwl tokens over HTTP', () async {
      final client = KitchenOwlClient(
        baseUrl: 'http://owl.local',
        token: 'secret',
      );
      expect(client.targets(), throwsA(isA<KitchenOwlException>()));
    });
  });

  group('ResultHandle', () {
    test('reads search id and token from the server result path', () {
      final handle = ResultHandle.parse('/results/abc123?token=deadbeef');
      expect(handle, isNotNull);
      expect(handle!.searchId, 'abc123');
      expect(handle.token, 'deadbeef');
    });

    test('reads an absolute result url too', () {
      final handle = ResultHandle.parse(
        'https://korb.example/results/abc123?token=deadbeef&loyalty=payback',
      );
      expect(handle!.searchId, 'abc123');
      expect(handle.token, 'deadbeef');
    });

    test('rejects a path without a token, so no unsigned call is made', () {
      expect(ResultHandle.parse('/results/abc123'), isNull);
      expect(ResultHandle.parse(''), isNull);
      expect(ResultHandle.parse('/nope?token=x'), isNull);
    });
  });

  group('model parsing', () {
    test('reads an offer the way the server presents it', () {
      final offer = Offer.fromJson({
        'retailer': 'famila Nordwest',
        'product': 'Kerrygold Butter',
        'regular_price': 2.29,
        'regular_price_text': '2,29 €',
        'effective_price': 1.59,
        'effective_price_text': '1,59 €',
        'loyalty_savings': 0.7,
        'loyalty_savings_text': '0,70 €',
        'pack': '250 g',
        'unit_price': '6,36 €/kg',
        'validity': 'bis 29.08.',
        'image_url': '/image?src=x&sig=y',
      });
      expect(offer.retailer, 'famila Nordwest');
      expect(offer.effectivePriceText, '1,59 €');
      expect(offer.hasSaving, isTrue);
      expect(offer.key, 'famila Nordwest|Kerrygold Butter|2,29 €');
    });

    test('treats a sub-cent difference as no saving, like the web view', () {
      final offer = Offer.fromJson({'loyalty_savings': 0.001});
      expect(offer.hasSaving, isFalse);
    });

    test('survives missing and unexpected fields', () {
      final offer = Offer.fromJson({'product': 'Nur ein Name'});
      expect(offer.product, 'Nur ein Name');
      expect(offer.regularPrice, isNull);
      expect(offer.retailer, '');
    });

    test('reads a result page including facets', () {
      final page = ResultPage.fromJson({
        'search_id': 'abc',
        'postal_code': '26188',
        'retailer_counts': {'Combi': 216, 'famila Nordwest': 289},
        'has_next': true,
        'page': 1,
        'offers': [
          {'product': 'A'},
          {'product': 'B'},
        ],
        'available_loyalty_programs': [
          {'id': 'payback', 'label': 'PAYBACK', 'note': 'n'},
        ],
        'warnings': ['etwas ging schief'],
      });
      expect(page.postalCode, '26188');
      expect(page.retailerCounts['famila Nordwest'], 289);
      expect(page.offers, hasLength(2));
      expect(page.availableLoyaltyPrograms.single.id, 'payback');
      expect(page.warnings, ['etwas ging schief']);
      expect(page.hasNext, isTrue);
    });

    test('an older server without the shopping list reads as disabled', () {
      final info = ShoppingListInfo.fromJson({
        'configured': false,
        'targets': [],
        'default_entity': '',
      });
      expect(info.configured, isFalse);
      expect(info.targets, isEmpty);
    });
  });

  group('image urls', () {
    final client = KorbKlarClient(baseUrl: 'http://korb.example:8000');

    test('server-relative proxy paths become absolute', () {
      expect(
        client.imageUrl('/image?src=a&sig=b'),
        'http://korb.example:8000/image?src=a&sig=b',
      );
    });

    test('absolute urls and empty values are left alone', () {
      expect(
        client.imageUrl('https://cdn.example/a.jpg'),
        'https://cdn.example/a.jpg',
      );
      expect(client.imageUrl(''), isNull);
    });
  });

  group('shopping list text', () {
    test('joins only the values an offer actually carries', () {
      final full = Offer.fromJson({
        'product': 'Kerrygold Butter',
        'retailer': 'Combi',
        'effective_price_text': '1,59 €',
        'pack': '250 g',
      });
      expect(
        ShoppingListText.lineFor(full),
        'Kerrygold Butter · 250 g · Combi · 1,59 €',
      );

      final sparse = Offer.fromJson({'product': 'Brot'});
      expect(ShoppingListText.lineFor(sparse), 'Brot');
    });

    test('falls back to the regular price when no loyalty price applies', () {
      final offer = Offer.fromJson({
        'product': 'Brot',
        'regular_price_text': '0,99 €',
      });
      expect(ShoppingListText.lineFor(offer), 'Brot · 0,99 €');
    });
  });

  group('image requests', () {
    test('carry the bearer token, because the proxy is gated too', () {
      final client = KorbKlarClient(
        baseUrl: 'http://korb.example',
        apiKey: 'k',
      );
      expect(client.imageHeaders, {'Authorization': 'Bearer k'});
    });

    test('carry nothing when no key is configured', () {
      final client = KorbKlarClient(baseUrl: 'http://korb.example');
      expect(client.imageHeaders, isEmpty);
    });
  });

  group('shopping list payload', () {
    test('several offers become one line each', () {
      final offers = [
        Offer.fromJson({'product': 'Butter', 'effective_price_text': '1,59 €'}),
        Offer.fromJson({'product': 'Brot', 'effective_price_text': '0,99 €'}),
      ];
      expect(
        ShoppingListText.textFor(offers),
        'Butter · 1,59 €\nBrot · 0,99 €',
      );
    });

    test('a merged row names every retailer it stands for', () {
      final offer = Offer.fromJson({
        'product': 'Butter',
        'retailer': 'Combi',
        'retailers': ['Combi', 'famila Nordwest'],
        'retailer_label': 'Combi · famila Nordwest',
        'effective_price_text': '1,59 €',
      });
      expect(
        ShoppingListText.lineFor(offer),
        'Butter · Combi · famila Nordwest · 1,59 €',
      );
    });
  });

  group('watchSearch', () {
    test(
      'a dropped poll does not end a search the server is still running',
      () async {
        var calls = 0;
        final client = KorbKlarClient(
          baseUrl: 'http://korb.example',
          httpClient: MockClient((_) {
            calls++;
            // Two failures in the middle, as a phone changing network produces.
            if (calls == 2 || calls == 3) return http.Response('down', 502);
            return http.Response(
              jsonEncode({
                'job_id': 'j',
                'status': calls < 5 ? 'processing' : 'completed',
                'result_url': '/results/abc?token=deadbeef',
              }),
              200,
            );
          }),
        );
        final seen = await client
            .watchSearch('j', interval: Duration.zero)
            .toList();
        expect(seen.last.isDone, isTrue);
        expect(seen.any((progress) => progress.isFailed), isFalse);
      },
    );

    test('gives up once the server stays unreachable', () async {
      final client = KorbKlarClient(
        baseUrl: 'http://korb.example',
        httpClient: MockClient((_) => http.Response('down', 502)),
      );
      expect(
        client
            .watchSearch('j', interval: Duration.zero, pollFailureLimit: 3)
            .toList(),
        throwsA(isA<KorbKlarException>()),
      );
    });
  });

  group('error handling', () {
    test('reports the server detail message', () async {
      final client = KorbKlarClient(
        baseUrl: 'http://korb.example',
        httpClient: MockClient(
          (_) => http.Response(
            jsonEncode({'detail': 'Ungültiger Ergebnis-Schlüssel'}),
            403,
          ),
        ),
      );
      expect(
        () => client.results(const ResultHandle(searchId: 'a', token: 'b')),
        throwsA(
          isA<KorbKlarException>().having(
            (error) => error.message,
            'message',
            'Ungültiger Ergebnis-Schlüssel',
          ),
        ),
      );
    });

    test('decodes umlauts as UTF-8 rather than latin-1', () async {
      final body = utf8.encode(
        jsonEncode({
          'offers': [
            {'product': 'Müller Joghurt'},
          ],
        }),
      );
      final client = KorbKlarClient(
        baseUrl: 'http://korb.example',
        httpClient: MockClient((_) => http.Response.bytes(body, 200)),
      );
      final page = await client.results(
        const ResultHandle(searchId: 'a', token: 'b'),
      );
      expect(page.offers.single.product, 'Müller Joghurt');
    });
  });
}

/// Minimal stub so the client can be exercised without a server.
class MockClient extends http.BaseClient {
  MockClient(this.handler);

  final http.Response Function(http.BaseRequest request) handler;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final response = handler(request);
    return http.StreamedResponse(
      Stream.value(response.bodyBytes),
      response.statusCode,
      headers: response.headers,
    );
  }
}

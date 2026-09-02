@Tags(['live'])
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/api/client.dart';

/// Drives a real KorbKlar server, mirroring the opt-in live tests the Python
/// project uses. Runs only when a server address is supplied:
///
/// ```bash
/// flutter test --tags live --dart-define=KORBKLAR_URL=http://127.0.0.1:8000
/// ```
///
/// Add `--dart-define=KORBKLAR_KEY=...` for an instance that requires one.
///
/// Set `KORBKLAR_PLZ` to a postal code your instance can actually resolve.
void main() {
  const baseUrl = String.fromEnvironment('KORBKLAR_URL');
  const postalCode = String.fromEnvironment(
    'KORBKLAR_PLZ',
    defaultValue: '26188',
  );
  const apiKey = String.fromEnvironment('KORBKLAR_KEY');

  if (baseUrl.isEmpty) {
    test('skipped: pass --dart-define=KORBKLAR_URL to run', () {}, skip: true);
    return;
  }

  late KorbKlarClient client;

  setUpAll(() {
    // The test runner has no browser sandbox, so a self-hosted instance with
    // a self-signed certificate would otherwise be unreachable here.
    HttpOverrides.global = null;
    client = KorbKlarClient(baseUrl: baseUrl, apiKey: apiKey);
  });

  tearDownAll(() => client.close());

  test('server identifies itself and accepts this client', () async {
    expect(await client.check(), ServerCheck.ok);
  });

  test(
    'a search runs to completion and yields a signed result link',
    () async {
      final jobId = await client.startSearch(postalCode);
      expect(jobId, isNotEmpty);

      var last = await client.searchProgress(jobId);
      await for (final progress in client.watchSearch(jobId)) {
        last = progress;
      }
      expect(last.isFailed, isFalse, reason: last.error);
      expect(last.isDone, isTrue);

      final handle = ResultHandle.parse(last.resultPath);
      expect(handle, isNotNull);

      final page = await client.results(handle!, pageSize: 20);
      expect(page.postalCode, postalCode);
      expect(page.offers, isNotEmpty);
      expect(page.retailerCounts, isNotEmpty);

      // Every offer must arrive with a formatted price; the app never formats
      // or computes one itself.
      for (final offer in page.offers) {
        expect(offer.product, isNotEmpty);
        expect(offer.effectivePriceText, isNotEmpty);
      }

      // Image links come back as signed, server-relative proxy paths.
      final withImage = page.offers.where((offer) => offer.imageUrl.isNotEmpty);
      if (withImage.isNotEmpty) {
        expect(client.imageUrl(withImage.first.imageUrl), startsWith(baseUrl));
      }
    },
    timeout: const Timeout(Duration(minutes: 8)),
  );

  test(
    'an invalid result token is refused',
    () async {
      final jobId = await client.startSearch(postalCode);
      var last = await client.searchProgress(jobId);
      await for (final progress in client.watchSearch(jobId)) {
        last = progress;
      }
      final handle = ResultHandle.parse(last.resultPath)!;
      expect(
        () => client.results(
          ResultHandle(searchId: handle.searchId, token: 'wrong'),
        ),
        throwsA(isA<KorbKlarException>()),
      );
    },
    timeout: const Timeout(Duration(minutes: 8)),
  );
}

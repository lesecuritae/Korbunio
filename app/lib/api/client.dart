import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class KorbKlarException implements Exception {
  KorbKlarException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

/// A search that has completed, identified by its id and signed result token.
class ResultHandle {
  const ResultHandle({required this.searchId, required this.token});

  /// Parses `/results/<id>?token=<sig>` as returned by the job and compare
  /// endpoints. The token is an HMAC the server issues; the app only carries
  /// it through and never derives one.
  static ResultHandle? parse(String resultPath) {
    if (resultPath.isEmpty) return null;
    final uri = Uri.tryParse(resultPath);
    if (uri == null) return null;
    final segments = uri.pathSegments;
    final index = segments.indexOf('results');
    if (index < 0 || index + 1 >= segments.length) return null;
    final token = uri.queryParameters['token'] ?? '';
    if (token.isEmpty) return null;
    return ResultHandle(searchId: segments[index + 1], token: token);
  }

  final String searchId;
  final String token;
}

/// Talks to a KorbKlar server.
///
/// The app uses the authenticated API equivalents of the browser endpoints:
/// the comparison engine, normalisation and loyalty logic stay on the server,
/// exactly as the project intends. No price is computed here.
/// What a connection check found.
enum ServerCheck {
  /// A KorbKlar server that accepts this client.
  ok,

  /// A KorbKlar server that requires an API key the client did not supply,
  /// or supplied wrongly.
  needsApiKey,

  /// Nothing that identifies itself as KorbKlar.
  notKorbKlar,
}

class ServerDefaults {
  const ServerDefaults({this.postalCode = '', this.retailers = const []});
  final String postalCode;
  final List<String> retailers;
}

class MarketChoice {
  const MarketChoice({required this.id, required this.label});

  final String id;
  final String label;
}

class KorbKlarClient {
  KorbKlarClient({
    required String baseUrl,
    String apiKey = '',
    http.Client? httpClient,
  }) : baseUrl = normalizeBaseUrl(baseUrl),
       apiKey = apiKey.trim(),
       _http = httpClient ?? http.Client();

  final String baseUrl;

  /// Sent as a bearer token on every request. A server reachable only over
  /// VPN may leave this empty; a public one requires it.
  final String apiKey;

  final http.Client _http;

  static const _timeout = Duration(seconds: 30);

  static String? connectionSecurityError(String baseUrl, String apiKey) {
    final uri = Uri.tryParse(normalizeBaseUrl(baseUrl));
    if (apiKey.trim().isEmpty || uri == null || uri.scheme == 'https') {
      return null;
    }
    return 'Ein API-Token darf nur über HTTPS übertragen werden.';
  }

  Map<String, String> _headers([Map<String, String>? extra]) => {
    if (apiKey.isNotEmpty) 'Authorization': 'Bearer $apiKey',
    ...?extra,
  };

  /// Headers any image request must carry.
  ///
  /// The image proxy is gated like every other route, so a widget loading
  /// a product image needs the bearer token too; without it the server
  /// answers 401 and every picture silently falls back to a placeholder.
  Map<String, String> get imageHeaders => _headers();

  /// Accepts what a user actually types: bare host, host:port, or full URL.
  static String normalizeBaseUrl(String raw) {
    var value = raw.trim();
    if (value.isEmpty) return '';
    if (!value.contains('://')) value = 'http://$value';
    while (value.endsWith('/')) {
      value = value.substring(0, value.length - 1);
    }
    return value;
  }

  void close() => _http.close();

  Uri _uri(String path, [Map<String, String>? query]) => Uri.parse(
    '$baseUrl$path',
  ).replace(queryParameters: query == null || query.isEmpty ? null : query);

  Never _fail(http.Response response) {
    String detail;
    try {
      final body = jsonDecode(response.body);
      detail = body is Map && body['detail'] != null
          ? '${body['detail']}'
          : 'HTTP ${response.statusCode}';
    } catch (_) {
      detail = 'HTTP ${response.statusCode}';
    }
    throw KorbKlarException(detail, statusCode: response.statusCode);
  }

  Map<String, dynamic> _json(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      _fail(response);
    }
    // The server always answers UTF-8; http defaults to latin-1 without a
    // charset parameter, which would mangle product names such as "Müller".
    final decoded = jsonDecode(utf8.decode(response.bodyBytes));
    if (decoded is! Map<String, dynamic>) {
      throw KorbKlarException('Unerwartete Antwort vom Server.');
    }
    return decoded;
  }

  Future<T> _guard<T>(Future<T> Function() action) async {
    try {
      return await action();
    } on KorbKlarException {
      rethrow;
    } on TimeoutException {
      throw KorbKlarException('Zeitüberschreitung. Server erreichbar?');
    } catch (error) {
      throw KorbKlarException('Server nicht erreichbar: $error');
    }
  }

  /// Confirms the base URL points at a KorbKlar instance this client may use.
  ///
  /// ``/health`` stays reachable without authorisation but withholds its
  /// detail fields, which makes it a cheap and side-effect-free way to tell
  /// "wrong address" from "needs an API key".
  Future<ServerCheck> check() => _guard(() async {
    final securityError = connectionSecurityError(baseUrl, apiKey);
    if (securityError != null) throw KorbKlarException(securityError);
    final health = await _http.get(_uri('/health')).timeout(_timeout);
    final healthPayload = _json(health);
    if (healthPayload['service'] != 'korbklar') return ServerCheck.notKorbKlar;
    final response = await _http
        .get(_uri('/api/v1/client'), headers: _headers())
        .timeout(_timeout);
    if (response.statusCode == 401) return ServerCheck.needsApiKey;
    final payload = _json(response);
    return payload['service'] == 'korbklar'
        ? ServerCheck.ok
        : ServerCheck.notKorbKlar;
  });

  Future<ServerDefaults> defaults() => _guard(() async {
    final securityError = connectionSecurityError(baseUrl, apiKey);
    if (securityError != null) throw KorbKlarException(securityError);
    final response = await _http
        .get(_uri('/api/v1/client'), headers: _headers())
        .timeout(_timeout);
    final payload = _json(response);
    return ServerDefaults(
      postalCode: '${payload['default_postal_code'] ?? ''}'.trim(),
      retailers: (payload['default_retailers'] as List? ?? const [])
          .map((value) => '$value'.trim())
          .where((value) => value.isNotEmpty)
          .toList(growable: false),
    );
  });

  /// Exchanges the server's administrator key for a separate app token.
  /// The administrator key is only sent in this request and can then be
  /// replaced in encrypted storage by the returned client token.
  Future<String> createAppToken({String label = 'KorbKlar Android'}) =>
      _guard(() async {
        final securityError = connectionSecurityError(baseUrl, apiKey);
        if (securityError != null) throw KorbKlarException(securityError);
        if (apiKey.isEmpty) {
          throw KorbKlarException('Bitte zuerst den Admin-API-Key eingeben.');
        }
        final response = await _http
            .post(
              _uri('/api/v1/access-tokens'),
              headers: _headers({
                'Content-Type': 'application/json; charset=utf-8',
              }),
              body: jsonEncode({'label': label}),
            )
            .timeout(_timeout);
        final token = _json(response)['token'];
        if (token is! String || token.isEmpty) {
          throw KorbKlarException('Der Server lieferte keinen App-Token.');
        }
        return token;
      });

  /// Starts a background search and returns its job id.
  /// Starts a background search. ``refresh`` skips the server's snapshot
  /// cache and re-queries every source.
  Future<String> startSearch(
    String postalCode, {
    bool refresh = false,
    List<String> retailers = const [],
    String nettoMarketId = '',
    String nettoScottieMarketId = '',
  }) => _guard(() async {
    final securityError = connectionSecurityError(baseUrl, apiKey);
    if (securityError != null) throw KorbKlarException(securityError);
    final response = await _http
        .post(
          _uri('/api/v1/search/jobs'),
          headers: _headers({
            'Content-Type': 'application/json; charset=utf-8',
          }),
          body: jsonEncode({
            'postal_code': postalCode,
            'refresh': refresh,
            'retailers': retailers,
            if (nettoMarketId.isNotEmpty) 'netto_market_id': nettoMarketId,
            if (nettoScottieMarketId.isNotEmpty)
              'netto_scottie_market_id': nettoScottieMarketId,
          }),
        )
        .timeout(_timeout);
    final jobId = _json(response)['job_id'];
    if (jobId is! String || jobId.isEmpty) {
      throw KorbKlarException('Server lieferte keine Auftragsnummer.');
    }
    return jobId;
  });

  Future<List<MarketChoice>> nettoMarkets(String postalCode) =>
      _markets('/api/v1/netto/markets', postalCode);

  Future<List<MarketChoice>> nettoScottieMarkets(String postalCode) =>
      _markets('/api/v1/netto-scottie/markets', postalCode);

  Future<List<MarketChoice>> _markets(String path, String postalCode) =>
      _guard(() async {
        final response = await _http
            .get(_uri(path, {'postal_code': postalCode}), headers: _headers())
            .timeout(_timeout);
        final values = _json(response)['markets'];
        if (values is! List) return const [];
        final byId = <String, MarketChoice>{};
        for (final value in values) {
          if (value is! Map) continue;
          final id = '${value['market_id'] ?? ''}'.trim();
          final label = '${value['label'] ?? ''}'.trim();
          if (id.isNotEmpty && label.isNotEmpty) {
            byId.putIfAbsent(id, () => MarketChoice(id: id, label: label));
          }
        }
        return byId.values.toList(growable: false);
      });

  Future<SearchProgress> searchProgress(String jobId) => _guard(() async {
    final response = await _http
        .get(_uri('/api/v1/search/jobs/$jobId'), headers: _headers())
        .timeout(_timeout);
    return SearchProgress.fromJson(_json(response));
  });

  /// Polls a running search until it finishes, reporting progress as it goes.
  ///
  /// A search runs for minutes, and a phone drops connections in that time:
  /// the network changes, the screen locks, the radio sleeps. The search
  /// itself keeps running on the server, so a failed poll is not a failed
  /// search and must not end one. Only [pollFailureLimit] failures in a row
  /// count as the server being gone.
  Stream<SearchProgress> watchSearch(
    String jobId, {
    Duration interval = const Duration(milliseconds: 700),
    int pollFailureLimit = 8,
  }) async* {
    var failures = 0;
    while (true) {
      SearchProgress progress;
      try {
        progress = await searchProgress(jobId);
        failures = 0;
      } on KorbKlarException {
        failures++;
        if (failures >= pollFailureLimit) rethrow;
        // Back off further with each failure, so a sleeping radio gets time
        // to come back without the poll hammering it.
        await Future<void>.delayed(interval * failures);
        continue;
      }
      yield progress;
      if (progress.isDone || progress.isFailed) return;
      await Future<void>.delayed(interval);
    }
  }

  /// Loads one page of results for a completed search.
  ///
  /// This is the endpoint the browser uses, so it returns proxied image URLs
  /// and source links, which `POST /api/v1/compare` deliberately omits.
  Future<ResultPage> results(
    ResultHandle handle, {
    String filterText = '',
    String retailer = '',
    String category = '',
    int page = 1,
    int pageSize = 100,
    String view = 'best_only',
    List<String> loyaltyPrograms = const [],
    String sort = 'price',
  }) => _guard(() async {
    final response = await _http
        .get(
          _uri('/api/v1/results/${Uri.encodeComponent(handle.searchId)}', {
            'token': handle.token,
            'q': filterText,
            'retailer': retailer,
            'category': category,
            'page': '$page',
            'page_size': '$pageSize',
            'view': view,
            'loyalty': loyaltyPrograms.join(','),
            'sort': sort,
          }),
          headers: _headers(),
        )
        .timeout(_timeout);
    return ResultPage.fromJson(_json(response));
  });

  /// Absolute URL for a proxied product image.
  ///
  /// The server returns image links as server-relative paths that already
  /// carry their own signature.
  String? imageUrl(String relative) {
    if (relative.isEmpty) return null;
    if (relative.startsWith('http://') || relative.startsWith('https://')) {
      return relative;
    }
    return '$baseUrl$relative';
  }

  /// Reports whether this server has a shopping list configured.
  ///
  /// Older servers without the integration answer 404; that is reported as
  /// "not configured" rather than as an error, so the app stays usable
  /// against any KorbKlar instance.
  Future<ShoppingListInfo> shoppingListTargets(
    ResultHandle handle,
  ) => _guard(() async {
    final response = await _http
        .get(
          _uri(
            '/results/${Uri.encodeComponent(handle.searchId)}/shopping-list/targets',
            {'token': handle.token},
          ),
          headers: _headers(),
        )
        .timeout(_timeout);
    if (response.statusCode == 404) return ShoppingListInfo.disabled;
    return ShoppingListInfo.fromJson(_json(response));
  });

  /// Article names currently on the list.
  ///
  /// KitchenOwl removes an entry when it is checked off, so this is what
  /// tells the app that an offer it filed earlier is no longer pending.
  Future<Set<String>> listEntries(
    ResultHandle handle,
    String entityId,
  ) => _guard(() async {
    final response = await _http
        .get(
          _uri(
            '/results/${Uri.encodeComponent(handle.searchId)}/shopping-list/entries',
            {'token': handle.token, 'entity_id': entityId},
          ),
          headers: _headers(),
        )
        .timeout(_timeout);
    if (response.statusCode == 404) return <String>{};
    final payload = _json(response);
    return {
      for (final item in payload['items'] as List? ?? [])
        if (item is String && item.isNotEmpty) item,
    };
  });

  /// Writes offers to the KitchenOwl list behind the server.
  /// Returns the article names KitchenOwl stored.
  Future<List<String>> addToShoppingList(
    ResultHandle handle, {
    required String entityId,
    required List<Offer> offers,
  }) => _guard(() async {
    final response = await _http
        .post(
          _uri(
            '/results/${Uri.encodeComponent(handle.searchId)}/shopping-list/items',
            {'token': handle.token},
          ),
          headers: _headers({
            'Content-Type': 'application/json; charset=utf-8',
          }),
          body: jsonEncode({
            'entity_id': entityId,
            'items': [
              for (final offer in offers)
                {
                  'product': offer.product,
                  'retailer': offer.retailer,
                  'price_text': offer.effectivePriceText.isNotEmpty
                      ? offer.effectivePriceText
                      : offer.regularPriceText,
                  'validity': offer.validity,
                  'pack': offer.pack,
                },
            ],
          }),
        )
        .timeout(_timeout);
    final payload = _json(response);
    return [
      for (final name in payload['added'] as List? ?? [])
        if (name is String) name,
    ];
  });
}

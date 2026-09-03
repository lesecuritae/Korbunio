import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../services/kitchenowl_articles.dart';
import 'models.dart';

class KitchenOwlException implements Exception {
  KitchenOwlException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Direct optional connection to a user-owned KitchenOwl instance. The token
/// is supplied from Android's encrypted storage and never sent to KorbKlar.
///
/// Besides the list of targets, the client reads what the household already
/// keeps so an offer lands on the existing article ("Brötchen" with its icon)
/// rather than beside it, and files the article under a category named after
/// the retailer so the list sorts by shop.
class KitchenOwlClient {
  KitchenOwlClient({
    required String baseUrl,
    required this.token,
    http.Client? httpClient,
  }) : baseUrl = baseUrl.trim().replaceFirst(RegExp(r'/+$'), ''),
       _http = httpClient ?? http.Client();

  final String baseUrl;
  final String token;
  final http.Client _http;
  static const _timeout = Duration(seconds: 20);

  /// What the household keeps, per household id. Read once per screen; a
  /// stale entry costs a near duplicate at worst, never a lost offer.
  final _catalogues = <String, List<String>>{};
  final _categories = <String, Map<String, int>>{};

  bool get configured => baseUrl.isNotEmpty && token.isNotEmpty;
  bool get secure => Uri.tryParse(baseUrl)?.scheme == 'https';
  Map<String, String> get _headers => {
    'Authorization': 'Bearer $token',
    'Accept': 'application/json',
    'Content-Type': 'application/json; charset=utf-8',
  };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  void _requireSecure() {
    if (!secure) {
      throw KitchenOwlException(
        'KitchenOwl-Tokens dürfen nur über HTTPS übertragen werden.',
      );
    }
  }

  dynamic _decode(http.Response response) {
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw KitchenOwlException('KitchenOwl hat den Token abgelehnt.');
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw KitchenOwlException(
        'KitchenOwl antwortete mit HTTP ${response.statusCode}.',
      );
    }
    if (response.bodyBytes.isEmpty) return null;
    return jsonDecode(utf8.decode(response.bodyBytes));
  }

  Future<dynamic> _get(String path) async =>
      _decode(await _http.get(_uri(path), headers: _headers).timeout(_timeout));

  Future<dynamic> _post(String path, Map<String, Object?> payload) async =>
      _decode(
        await _http
            .post(_uri(path), headers: _headers, body: jsonEncode(payload))
            .timeout(_timeout),
      );

  Future<T> _call<T>(Future<T> Function() action) async {
    _requireSecure();
    try {
      return await action();
    } on KitchenOwlException {
      rethrow;
    } on Object catch (error) {
      throw KitchenOwlException('KitchenOwl ist nicht erreichbar: $error');
    }
  }

  static List<Map> _entries(Object? payload) =>
      payload is List ? payload.whereType<Map>().toList() : const [];

  static String _name(Map entry) => '${entry['name'] ?? ''}'.trim();

  /// Every shopping list the token can reach, labelled with its household.
  Future<List<ShoppingListTarget>> targets() async {
    if (!configured) return const [];
    return _call(() async {
      final result = <ShoppingListTarget>[];
      for (final household in _entries(await _get('/api/household'))) {
        if (household['id'] == null) continue;
        final householdId = '${household['id']}';
        final householdName = _name(household);
        final lists = await _get('/api/household/$householdId/shoppinglist');
        for (final list in _entries(lists)) {
          if (list['id'] == null) continue;
          final name = _name(list).isEmpty ? 'Einkauf' : _name(list);
          result.add(
            ShoppingListTarget(
              entityId: '${list['id']}',
              label: householdName.isEmpty ? name : '$householdName · $name',
              householdId: householdId,
            ),
          );
        }
      }
      return result;
    });
  }

  /// Article names the household already keeps.
  Future<List<String>> catalogue(String householdId) async {
    final cached = _catalogues[householdId];
    if (cached != null) return cached;
    final names = [
      for (final item in _entries(
        await _get('/api/household/$householdId/item'),
      ))
        if (_name(item).isNotEmpty) _name(item),
    ];
    _catalogues[householdId] = names;
    return names;
  }

  /// The category id for this name, created when the household lacks it.
  Future<int?> _categoryId(String householdId, String name) async {
    var known = _categories[householdId];
    if (known == null) {
      known = {
        for (final entry in _entries(
          await _get('/api/household/$householdId/category'),
        ))
          if (entry['id'] is int && _name(entry).isNotEmpty)
            _name(entry).toLowerCase(): entry['id'] as int,
      };
      _categories[householdId] = known;
    }
    final existing = known[name.toLowerCase()];
    if (existing != null) return existing;
    final created = await _post('/api/household/$householdId/category', {
      'name': name,
    });
    if (created is! Map || created['id'] is! int) return null;
    known[name.toLowerCase()] = created['id'] as int;
    return created['id'] as int;
  }

  /// Article names currently on the list.
  ///
  /// KitchenOwl removes an entry when it is checked off, so this is what
  /// tells the app that an offer it filed earlier is no longer pending.
  Future<Set<String>> entries(String listId) => _call(() async {
    final names = <String>{};
    for (final entry in _entries(
      await _get('/api/shoppinglist/$listId/items'),
    )) {
      var name = _name(entry);
      if (name.isEmpty && entry['item'] is Map) name = _name(entry['item']);
      if (name.isNotEmpty) names.add(name);
    }
    return names;
  });

  /// Files one offer and returns the article name KitchenOwl stored it under.
  ///
  /// With [householdId] the offer lands on a matching article the household
  /// already keeps and is filed under the retailer's category; without it
  /// the shortened offer name is used and no category is set.
  Future<String> addOffer(
    String listId,
    Offer offer, {
    String householdId = '',
  }) async {
    if (!RegExp(r'^\d+$').hasMatch(listId)) {
      throw KitchenOwlException('Ungültige KitchenOwl-Listen-ID.');
    }
    return _call(() async {
      final catalogue = householdId.isEmpty
          ? const <String>[]
          : await this.catalogue(householdId);
      final article = articleFor(offer, catalogue);
      final note = noteFor(offer, article);
      final created = await _post(
        '/api/shoppinglist/$listId/add-item-by-name',
        {'name': article, if (note.isNotEmpty) 'description': note},
      );
      if (!catalogue.contains(article)) _catalogues[householdId]?.add(article);

      final category = retailerCategory(offer.retailer);
      if (householdId.isNotEmpty &&
          category.isNotEmpty &&
          created is Map &&
          created['id'] != null) {
        try {
          final categoryId = await _categoryId(householdId, category);
          if (categoryId != null) {
            await _post('/api/item/${created['id']}', {
              'category': {'id': categoryId},
            });
          }
        } on Object {
          // The article is on the list; filing it under the shop is a nicety.
        }
      }
      return article;
    });
  }

  void close() => _http.close();
}

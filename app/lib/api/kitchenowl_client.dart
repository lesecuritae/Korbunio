import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class KitchenOwlException implements Exception {
  KitchenOwlException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Direct optional connection to a user-owned KitchenOwl instance. The token
/// is supplied from Android's encrypted storage and never sent to KorbKlar.
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

  bool get configured => baseUrl.isNotEmpty && token.isNotEmpty;
  bool get secure => Uri.tryParse(baseUrl)?.scheme == 'https';
  Map<String, String> get _headers => {
    'Authorization': 'Bearer $token',
    'Accept': 'application/json',
    'Content-Type': 'application/json; charset=utf-8',
  };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

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

  Future<List<ShoppingListTarget>> targets() async {
    if (!configured) return const [];
    if (!secure) {
      throw KitchenOwlException(
        'KitchenOwl-Tokens dürfen nur über HTTPS übertragen werden.',
      );
    }
    try {
      final households = _decode(
        await _http
            .get(_uri('/api/household'), headers: _headers)
            .timeout(_timeout),
      );
      final result = <ShoppingListTarget>[];
      for (final household in households is List ? households : const []) {
        if (household is! Map || household['id'] == null) continue;
        final householdName = '${household['name'] ?? ''}'.trim();
        final lists = _decode(
          await _http
              .get(
                _uri('/api/household/${household['id']}/shoppinglist'),
                headers: _headers,
              )
              .timeout(_timeout),
        );
        for (final list in lists is List ? lists : const []) {
          if (list is! Map || list['id'] == null) continue;
          final name = '${list['name'] ?? 'Einkauf'}'.trim();
          result.add(
            ShoppingListTarget(
              entityId: '${list['id']}',
              label: householdName.isEmpty ? name : '$householdName · $name',
            ),
          );
        }
      }
      return result;
    } on KitchenOwlException {
      rethrow;
    } on Object catch (error) {
      throw KitchenOwlException('KitchenOwl ist nicht erreichbar: $error');
    }
  }

  Future<String> addOffer(String listId, Offer offer) async {
    if (!RegExp(r'^\d+$').hasMatch(listId)) {
      throw KitchenOwlException('Ungültige KitchenOwl-Listen-ID.');
    }
    if (!secure) {
      throw KitchenOwlException(
        'KitchenOwl-Tokens dürfen nur über HTTPS übertragen werden.',
      );
    }
    final price = offer.effectivePriceText.isNotEmpty
        ? offer.effectivePriceText
        : offer.regularPriceText;
    final description = [
      offer.retailerText,
      price,
      offer.pack,
      offer.validity,
    ].where((item) => item.isNotEmpty).join(' · ');
    final payload = <String, String>{'name': offer.product};
    if (description.isNotEmpty) payload['description'] = description;
    try {
      _decode(
        await _http
            .post(
              _uri('/api/shoppinglist/$listId/add-item-by-name'),
              headers: _headers,
              body: jsonEncode(payload),
            )
            .timeout(_timeout),
      );
      return offer.product;
    } on KitchenOwlException {
      rethrow;
    } on Object catch (error) {
      throw KitchenOwlException('KitchenOwl ist nicht erreichbar: $error');
    }
  }

  void close() => _http.close();
}

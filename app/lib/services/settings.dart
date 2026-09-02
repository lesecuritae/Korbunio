import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api/client.dart';

/// The comparison the app showed last, so the next start can open it again
/// instead of asking for the postal code and waiting for every retailer.
///
/// The result token is the signed link the server issued; it is not a
/// credential, the same string sits in every result URL the browser shows.
class LastSearch {
  const LastSearch({
    required this.postalCode,
    required this.retailers,
    required this.searchId,
    required this.token,
    required this.searchedAt,
  });

  final String postalCode;
  final List<String> retailers;
  final String searchId;
  final String token;
  final DateTime searchedAt;

  ResultHandle get handle => ResultHandle(searchId: searchId, token: token);

  /// Whether this search covers the same postal code and retailer selection.
  bool matches(String postalCode, List<String> retailers) =>
      this.postalCode == postalCode &&
      this.retailers.join(',') == retailers.join(',');
}

/// Locally remembered preferences. Nothing here leaves the device except the
/// server address the user typed themselves.
class Settings {
  Settings._(this._prefs, this._secure, this._apiToken, this._kitchenOwlToken);

  static Future<Settings> load({FlutterSecureStorage? secureStorage}) async {
    final prefs = await SharedPreferences.getInstance();
    final secure =
        secureStorage ??
        const FlutterSecureStorage(
          aOptions: AndroidOptions(encryptedSharedPreferences: true),
        );
    // Migrate the fork's former plaintext token once, then remove it.
    final legacy = prefs.getString(_legacyApiKey) ?? '';
    String apiToken = '';
    String kitchenOwlToken = '';
    try {
      apiToken = await secure.read(key: _apiKey) ?? '';
      kitchenOwlToken = await secure.read(key: _kitchenOwlTokenKey) ?? '';
    } on MissingPluginException {
      // Pure Dart and widget tests do not provide an Android Keystore.
    }
    if (apiToken.isEmpty && legacy.isNotEmpty) {
      await secure.write(key: _apiKey, value: legacy);
      apiToken = legacy;
    }
    await prefs.remove(_legacyApiKey);
    return Settings._(prefs, secure, apiToken, kitchenOwlToken);
  }

  final SharedPreferences _prefs;
  final FlutterSecureStorage _secure;
  String _apiToken;
  String _kitchenOwlToken;

  static const _serverUrl = 'server_url';
  static const _postalCode = 'postal_code';
  static const _loyalty = 'loyalty_programs';
  static const _retailers = 'selected_retailers';
  static const _listEntity = 'shopping_list_entity';
  static const _legacyApiKey = 'api_key';
  static const _apiKey = 'korbklar_api_token';
  static const _kitchenOwlUrl = 'kitchenowl_url';
  static const _kitchenOwlTokenKey = 'kitchenowl_token';
  static const _themeMode = 'theme_mode';

  String get serverUrl => _prefs.getString(_serverUrl) ?? '';
  Future<void> setServerUrl(String value) =>
      _prefs.setString(_serverUrl, value);

  /// Bearer token for a publicly reachable instance. Empty when the server
  /// is only used over VPN.
  String get apiKey => _apiToken;
  Future<void> setApiKey(String value) async {
    _apiToken = value.trim();
    if (_apiToken.isEmpty) {
      await _secure.delete(key: _apiKey);
    } else {
      await _secure.write(key: _apiKey, value: _apiToken);
    }
  }

  String get kitchenOwlUrl => _prefs.getString(_kitchenOwlUrl) ?? '';
  Future<void> setKitchenOwlUrl(String value) =>
      _prefs.setString(_kitchenOwlUrl, value.trim());

  String get kitchenOwlToken => _kitchenOwlToken;
  Future<void> setKitchenOwlToken(String value) async {
    _kitchenOwlToken = value.trim();
    if (_kitchenOwlToken.isEmpty) {
      await _secure.delete(key: _kitchenOwlTokenKey);
    } else {
      await _secure.write(key: _kitchenOwlTokenKey, value: _kitchenOwlToken);
    }
  }

  String get postalCode => _prefs.getString(_postalCode) ?? '';
  bool get hasPostalCode => _prefs.containsKey(_postalCode);
  Future<void> setPostalCode(String value) =>
      _prefs.setString(_postalCode, value);

  List<String> get loyaltyPrograms =>
      _prefs.getStringList(_loyalty) ?? const [];
  Future<void> setLoyaltyPrograms(List<String> value) =>
      _prefs.setStringList(_loyalty, value);

  List<String> get selectedRetailers =>
      _prefs.getStringList(_retailers) ?? const [];
  bool get hasSelectedRetailers => _prefs.containsKey(_retailers);
  Future<void> setSelectedRetailers(List<String> value) =>
      _prefs.setStringList(_retailers, value);

  String get shoppingListEntity => _prefs.getString(_listEntity) ?? '';
  Future<void> setShoppingListEntity(String value) =>
      _prefs.setString(_listEntity, value);

  static const _autoStart = 'auto_start';
  static const _lastSearchPostalCode = 'last_search_postal_code';
  static const _lastSearchRetailers = 'last_search_retailers';
  static const _lastSearchId = 'last_search_id';
  static const _lastSearchToken = 'last_search_token';
  static const _lastSearchAt = 'last_search_at';

  /// Open the last comparison straight away on start instead of showing the
  /// postal-code form. On by default: the postal code rarely changes, and a
  /// new one is one tap away from the results.
  bool get autoStart => _prefs.getBool(_autoStart) ?? true;
  Future<void> setAutoStart(bool value) => _prefs.setBool(_autoStart, value);

  LastSearch? get lastSearch {
    final searchId = _prefs.getString(_lastSearchId) ?? '';
    final token = _prefs.getString(_lastSearchToken) ?? '';
    final searchedAt = DateTime.tryParse(_prefs.getString(_lastSearchAt) ?? '');
    if (searchId.isEmpty || token.isEmpty || searchedAt == null) return null;
    return LastSearch(
      postalCode: _prefs.getString(_lastSearchPostalCode) ?? '',
      retailers: _prefs.getStringList(_lastSearchRetailers) ?? const [],
      searchId: searchId,
      token: token,
      searchedAt: searchedAt.toLocal(),
    );
  }

  Future<void> setLastSearch(LastSearch value) async {
    await _prefs.setString(_lastSearchPostalCode, value.postalCode);
    await _prefs.setStringList(_lastSearchRetailers, value.retailers);
    await _prefs.setString(_lastSearchId, value.searchId);
    await _prefs.setString(_lastSearchToken, value.token);
    await _prefs.setString(
      _lastSearchAt,
      value.searchedAt.toUtc().toIso8601String(),
    );
  }

  Future<void> clearLastSearch() async {
    for (final key in [
      _lastSearchPostalCode,
      _lastSearchRetailers,
      _lastSearchId,
      _lastSearchToken,
      _lastSearchAt,
    ]) {
      await _prefs.remove(key);
    }
  }

  static String normalizeThemeMode(String value) =>
      const {'system', 'light', 'dark'}.contains(value) ? value : 'system';

  String get themeMode =>
      normalizeThemeMode(_prefs.getString(_themeMode) ?? 'system');
  Future<void> setThemeMode(String value) =>
      _prefs.setString(_themeMode, normalizeThemeMode(value));
}

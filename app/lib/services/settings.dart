import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

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
  static const _updateCheck = 'update_check_on_start';
  static const _updateSkipped = 'update_skipped_tag';
  static const _updateLast = 'update_last_check';

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

  static String normalizeThemeMode(String value) =>
      const {'system', 'light', 'dark'}.contains(value) ? value : 'system';

  String get themeMode =>
      normalizeThemeMode(_prefs.getString(_themeMode) ?? 'system');
  Future<void> setThemeMode(String value) =>
      _prefs.setString(_themeMode, normalizeThemeMode(value));

  /// Whether the app asks GitHub for a newer release when it starts.
  bool get updateCheckOnStart => _prefs.getBool(_updateCheck) ?? true;
  Future<void> setUpdateCheckOnStart(bool value) =>
      _prefs.setBool(_updateCheck, value);

  /// The release tag the user chose to skip; offered again only by a manual check.
  String get skippedUpdateTag => _prefs.getString(_updateSkipped) ?? '';
  Future<void> setSkippedUpdateTag(String value) =>
      _prefs.setString(_updateSkipped, value);

  DateTime? get lastUpdateCheck {
    final raw = _prefs.getString(_updateLast);
    return raw == null ? null : DateTime.tryParse(raw);
  }

  Future<void> setLastUpdateCheck(DateTime value) =>
      _prefs.setString(_updateLast, value.toUtc().toIso8601String());
}

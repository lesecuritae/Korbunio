import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/kitchenowl_client.dart';
import '../services/app_update.dart';
import '../services/settings.dart';
import '../widgets/app_update_flow.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({
    super.key,
    required this.settings,
    required this.onThemeChanged,
  });
  final Settings settings;
  final VoidCallback onThemeChanged;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final _server = TextEditingController(text: widget.settings.serverUrl);
  late final _apiToken = TextEditingController(text: widget.settings.apiKey);
  late final _kitchenOwl = TextEditingController(
    text: widget.settings.kitchenOwlUrl,
  );
  late final _kitchenOwlToken = TextEditingController(
    text: widget.settings.kitchenOwlToken,
  );
  bool _busy = false;
  String _message = '';
  late final AppUpdateFlow _updates = AppUpdateFlow();

  Future<void> _setTheme(String value) async {
    await widget.settings.setThemeMode(value);
    widget.onThemeChanged();
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _server.dispose();
    _apiToken.dispose();
    _kitchenOwl.dispose();
    _kitchenOwlToken.dispose();
    _updates.close();
    super.dispose();
  }

  Future<void> _saveServer() async {
    final url = KorbKlarClient.normalizeBaseUrl(_server.text);
    final token = _apiToken.text.trim();
    final security = KorbKlarClient.connectionSecurityError(url, token);
    if (security != null) return _show(security);
    if (url.isEmpty) {
      await widget.settings.setServerUrl('');
      await widget.settings.setApiKey('');
      return _show(
        'Serververbindung entfernt. Offline-Daten bleiben erhalten.',
      );
    }
    setState(() => _busy = true);
    final client = KorbKlarClient(baseUrl: url, apiKey: token);
    try {
      final check = await client.check();
      if (check != ServerCheck.ok) {
        return _show(
          check == ServerCheck.needsApiKey
              ? 'API-Token fehlt oder wurde abgelehnt.'
              : 'Unter dieser Adresse antwortet kein KorbKlar.',
        );
      }
      await widget.settings.setServerUrl(url);
      await widget.settings.setApiKey(token);
      _server.text = url;
      _show('KorbKlar-Server verbunden.');
    } on KorbKlarException catch (error) {
      _show(error.message);
    } finally {
      client.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _createAppToken() async {
    final url = KorbKlarClient.normalizeBaseUrl(_server.text);
    final adminToken = _apiToken.text.trim();
    final security = KorbKlarClient.connectionSecurityError(url, adminToken);
    if (security != null) return _show(security);
    if (url.isEmpty || adminToken.isEmpty) {
      return _show(
        'Serveradresse und Admin-API-Key werden zur Kopplung benötigt.',
      );
    }
    setState(() => _busy = true);
    final client = KorbKlarClient(baseUrl: url, apiKey: adminToken);
    try {
      final appToken = await client.createAppToken();
      await widget.settings.setServerUrl(url);
      await widget.settings.setApiKey(appToken);
      _server.text = url;
      _apiToken.text = appToken;
      _show('Eigener App-Token erstellt und sicher gespeichert.');
    } on KorbKlarException catch (error) {
      _show(error.message);
    } finally {
      client.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _saveKitchenOwl() async {
    final url = KorbKlarClient.normalizeBaseUrl(_kitchenOwl.text);
    final token = _kitchenOwlToken.text.trim();
    if (url.isEmpty && token.isEmpty) {
      await widget.settings.setKitchenOwlUrl('');
      await widget.settings.setKitchenOwlToken('');
      return _show('Direkte KitchenOwl-Verbindung entfernt.');
    }
    if (Uri.tryParse(url)?.scheme != 'https') {
      return _show('KitchenOwl benötigt wegen des Tokens eine HTTPS-Adresse.');
    }
    setState(() => _busy = true);
    final client = KitchenOwlClient(baseUrl: url, token: token);
    try {
      final targets = await client.targets();
      if (targets.isEmpty) {
        return _show('KitchenOwl liefert keine erreichbare Einkaufsliste.');
      }
      await widget.settings.setKitchenOwlUrl(url);
      await widget.settings.setKitchenOwlToken(token);
      _kitchenOwl.text = url;
      _show('${targets.length} KitchenOwl-Liste(n) verbunden.');
    } on KitchenOwlException catch (error) {
      _show(error.message);
    } finally {
      client.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  void _show(String value) {
    if (mounted) setState(() => _message = value);
  }

  Future<void> _checkForUpdates() async {
    setState(() => _busy = true);
    try {
      await _updates.check(context);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Verbindungen')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text(
          'Darstellung',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(
              value: 'system',
              label: Text('System'),
              icon: Icon(Icons.settings_brightness),
            ),
            ButtonSegment(
              value: 'light',
              label: Text('Hell'),
              icon: Icon(Icons.light_mode),
            ),
            ButtonSegment(
              value: 'dark',
              label: Text('Dunkel'),
              icon: Icon(Icons.dark_mode),
            ),
          ],
          selected: {widget.settings.themeMode},
          onSelectionChanged: _busy
              ? null
              : (values) => _setTheme(values.first),
        ),
        const Divider(height: 40),
        const Text(
          'Eigener KorbKlar-Server',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        const Text(
          'Aktuelle Angebote werden vom eigenen Docker-Backend geladen. Bereits geladene Daten bleiben offline verfügbar.',
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _server,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: 'Serveradresse',
            hintText: 'https://korbklar.example.de',
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _apiToken,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(
            labelText: 'API-Token (optional)',
            helperText:
                'Token werden nur im Android Keystore gespeichert und ausschließlich über HTTPS gesendet.',
          ),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _busy ? null : _saveServer,
          child: const Text('Server prüfen und speichern'),
        ),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: _busy ? null : _createAppToken,
          icon: const Icon(Icons.key),
          label: const Text('Eigenen App-Token erstellen'),
        ),
        const Text(
          'Dafür einmalig den Admin-API-Key des Servers eingeben. Danach ersetzt die App ihn durch einen eigenen Token; der Admin-Key bleibt nicht in der App gespeichert.',
          style: TextStyle(fontSize: 12),
        ),
        const Divider(height: 40),
        const Text(
          'Direktes KitchenOwl',
          style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 8),
        const Text(
          'Die App verbindet sich direkt mit deiner KitchenOwl-Instanz. Der Token wird nicht an den KorbKlar-Server übertragen.',
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _kitchenOwl,
          keyboardType: TextInputType.url,
          autocorrect: false,
          decoration: const InputDecoration(
            labelText: 'KitchenOwl-Adresse',
            hintText: 'https://einkauf.example.de',
          ),
        ),
        const SizedBox(height: 10),
        TextField(
          controller: _kitchenOwlToken,
          obscureText: true,
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(labelText: 'Long-lived Token'),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _busy ? null : _saveKitchenOwl,
          child: const Text('KitchenOwl prüfen und speichern'),
        ),
        if (_message.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 16),
            child: Text(_message),
          ),
        if (AppUpdateService.supported) ...[
          const Divider(height: 40),
          const Text(
            'App-Updates',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 8),
          const Text(
            'Neue Versionen kommen als signierte APK aus den GitHub-Releases '
            'von KorbKlar und werden vor der Installation gegen die dort '
            'hinterlegte Prüfsumme geprüft. Die App sucht nur auf Wunsch.',
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy ? null : _checkForUpdates,
            icon: const Icon(Icons.system_update_alt),
            label: const Text('Jetzt nach Updates suchen'),
          ),
        ],
      ],
    ),
  );
}

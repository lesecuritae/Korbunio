import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/kitchenowl_client.dart';
import '../services/settings.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.settings});
  final Settings settings;

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

  @override
  void dispose() {
    _server.dispose();
    _apiToken.dispose();
    _kitchenOwl.dispose();
    _kitchenOwlToken.dispose();
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

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Verbindungen')),
    body: ListView(
      padding: const EdgeInsets.all(16),
      children: [
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
      ],
    ),
  );
}

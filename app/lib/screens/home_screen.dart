import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../main.dart';
import '../services/settings.dart';
import '../services/offline_store.dart';
import '../services/local_shopping_list.dart';
import '../services/postal_location.dart';
import '../theme.dart';
import 'results_screen.dart';
import 'settings_screen.dart';
import 'local_shopping_list_screen.dart';

/// Postal-code entry and live search progress, mirroring the web home page.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    required this.settings,
    required this.offlineStore,
    required this.localShoppingList,
  });

  final Settings settings;
  final OfflineStore offlineStore;
  final LocalShoppingListStore localShoppingList;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  late final TextEditingController _postalCode = TextEditingController(
    text: widget.settings.postalCode,
  );
  late final TextEditingController _server = TextEditingController(
    text: widget.settings.serverUrl,
  );
  late final TextEditingController _apiKey = TextEditingController(
    text: widget.settings.apiKey,
  );

  StreamSubscription<SearchProgress>? _watch;
  SearchProgress? _progress;
  String _error = '';
  bool _busy = false;
  bool _offlineAvailable = false;
  bool _locating = false;

  /// The search running on the server, kept so a lost connection can be
  /// picked back up instead of starting the whole comparison again.
  KorbKlarClient? _client;
  String _jobId = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _checkOffline();
    if (_postalCode.text.isEmpty) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _useLocation());
    }
  }

  Future<void> _useLocation() async {
    if (_locating) return;
    setState(() {
      _locating = true;
      _error = '';
    });
    try {
      final postalCode = await PostalLocationResolver().resolve();
      _postalCode.text = postalCode;
      await widget.settings.setPostalCode(postalCode);
      await _checkOffline();
    } on PostalLocationException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } on Object {
      if (mounted) {
        setState(
          () => _error =
              'Der Standort konnte nicht in eine PLZ aufgelöst werden.',
        );
      }
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  Future<void> _checkOffline() async {
    final postalCode = _postalCode.text.trim();
    final available =
        RegExp(r'^\d{5}$').hasMatch(postalCode) &&
        await widget.offlineStore.hasPostalCode(postalCode);
    if (mounted) setState(() => _offlineAvailable = available);
  }

  Future<void> _openOffline() async {
    final client = KorbKlarClient(baseUrl: 'http://127.0.0.1:1');
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ResultsScreen(
          client: client,
          handle: const ResultHandle(searchId: 'offline', token: 'offline'),
          settings: widget.settings,
          offlineStore: widget.offlineStore,
          localShoppingList: widget.localShoppingList,
        ),
      ),
    );
    client.close();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _watch?.cancel();
    _client?.close();
    _postalCode.dispose();
    _server.dispose();
    _apiKey.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // Android suspends the app's timers and sockets while it is in the
    // background, which ends the poll even though the server keeps working.
    if (state == AppLifecycleState.resumed && !_busy && _jobId.isNotEmpty) {
      _watchJob();
    }
  }

  bool get _serverConfigured => widget.settings.serverUrl.isNotEmpty;

  Future<void> _openSettings() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => SettingsScreen(settings: widget.settings),
      ),
    );
    _server.text = widget.settings.serverUrl;
    _apiKey.text = widget.settings.apiKey;
    if (mounted) setState(() {});
  }

  Future<void> _saveServer() async {
    final normalized = KorbKlarClient.normalizeBaseUrl(_server.text);
    if (normalized.isEmpty) {
      setState(
        () => _error = 'Bitte die Adresse deines KorbKlar-Servers eingeben.',
      );
      return;
    }
    setState(() {
      _busy = true;
      _error = '';
    });
    final key = _apiKey.text.trim();
    final securityError = KorbKlarClient.connectionSecurityError(
      normalized,
      key,
    );
    if (securityError != null) {
      setState(() {
        _busy = false;
        _error = securityError;
      });
      return;
    }
    final client = KorbKlarClient(baseUrl: normalized, apiKey: key);
    try {
      switch (await client.check()) {
        case ServerCheck.notKorbKlar:
          setState(
            () => _error = 'Unter dieser Adresse antwortet kein KorbKlar.',
          );
          return;
        case ServerCheck.needsApiKey:
          setState(
            () => _error = key.isEmpty
                ? 'Dieser Server verlangt einen API-Key.'
                : 'Der API-Key wurde abgelehnt.',
          );
          return;
        case ServerCheck.ok:
          break;
      }
      await widget.settings.setServerUrl(normalized);
      await widget.settings.setApiKey(key);
      _server.text = normalized;
      setState(() {});
    } on KorbKlarException catch (exception) {
      setState(() => _error = exception.message);
    } finally {
      client.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _search() async {
    final postalCode = _postalCode.text.trim();
    if (!RegExp(r'^\d{5}$').hasMatch(postalCode)) {
      setState(
        () => _error =
            'Bitte eine gültige fünfstellige deutsche Postleitzahl eingeben.',
      );
      return;
    }
    FocusScope.of(context).unfocus();
    await widget.settings.setPostalCode(postalCode);

    await _watch?.cancel();
    _client?.close();
    final client = KorbKlarClient(
      baseUrl: widget.settings.serverUrl,
      apiKey: widget.settings.apiKey,
    );
    _client = client;
    setState(() {
      _busy = true;
      _error = '';
      _progress = null;
      _jobId = '';
    });

    try {
      _jobId = await client.startSearch(postalCode);
      _watchJob();
    } on KorbKlarException catch (exception) {
      _finish();
      if (mounted) {
        setState(() {
          _busy = false;
          _error = exception.message;
        });
      }
    }
  }

  /// Follows the search identified by [_jobId], from the start or again.
  ///
  /// Re-attaching costs one request; restarting the search would re-query
  /// every retailer and take minutes, so a lost connection must not do that.
  void _watchJob() {
    final client = _client;
    if (client == null || _jobId.isEmpty) return;
    _watch?.cancel();
    setState(() {
      _busy = true;
      _error = '';
    });
    _watch = client
        .watchSearch(_jobId)
        .listen(
          (progress) async {
            if (!mounted) return;
            setState(() => _progress = progress);
            if (progress.isFailed) {
              setState(() {
                _busy = false;
                _error = progress.error.isNotEmpty
                    ? progress.error
                    : 'Die Suche ist fehlgeschlagen.';
              });
              _finish();
              return;
            }
            if (!progress.isDone) return;

            final handle = ResultHandle.parse(progress.resultPath);
            if (handle == null) {
              setState(() {
                _busy = false;
                _error = 'Der Server lieferte keinen gültigen Ergebnislink.';
              });
              _finish();
              return;
            }
            setState(() {
              _busy = false;
              _jobId = '';
            });
            await Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => ResultsScreen(
                  client: client,
                  handle: handle,
                  settings: widget.settings,
                  offlineStore: widget.offlineStore,
                  localShoppingList: widget.localShoppingList,
                ),
              ),
            );
            _finish();
          },
          onError: (Object error) {
            if (!mounted) return;
            // The job id is kept: the comparison is still running on the server,
            // so this is recoverable and the user is offered the way back in.
            setState(() {
              _busy = false;
              _error = error is KorbKlarException ? error.message : '$error';
            });
          },
        );
  }

  /// Drops the running search and its connection.
  void _finish() {
    _jobId = '';
    _client?.close();
    _client = null;
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Align(
                    alignment: Alignment.centerRight,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          tooltip: 'Lokale Einkaufsliste',
                          onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute<void>(
                              builder: (_) => LocalShoppingListScreen(
                                store: widget.localShoppingList,
                              ),
                            ),
                          ),
                          icon: const Icon(Icons.shopping_basket_outlined),
                        ),
                        IconButton(
                          tooltip: 'Verbindungen und Einstellungen',
                          onPressed: _busy ? null : _openSettings,
                          icon: const Icon(Icons.settings_outlined),
                        ),
                      ],
                    ),
                  ),
                  const Center(child: KorbKlarWordmark(fontSize: 34)),
                  const SizedBox(height: 8),
                  Center(
                    child: Text(
                      'Regionale Supermarktangebote vergleichen',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: colors.muted, fontSize: 15),
                    ),
                  ),
                  const SizedBox(height: 28),
                  if (!_serverConfigured)
                    ..._serverSetup(colors)
                  else
                    ..._searchForm(colors),
                  if (_error.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    _ErrorBox(message: _error),
                    // The comparison itself is still running on the server.
                    if (_jobId.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      OutlinedButton.icon(
                        onPressed: _watchJob,
                        icon: const Icon(Icons.refresh, size: 18),
                        label: const Text('Suche weiter verfolgen'),
                      ),
                    ],
                  ],
                  if (_offlineAvailable) ...[
                    const SizedBox(height: 12),
                    OutlinedButton.icon(
                      onPressed: _busy ? null : _openOffline,
                      icon: const Icon(Icons.offline_bolt_outlined),
                      label: Text(
                        'Gespeicherte Angebote für ${_postalCode.text} öffnen',
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _serverSetup(KorbColors colors) => [
    _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Server verbinden',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          Text(
            'Adresse deiner KorbKlar-Instanz. Die App rechnet nichts selbst, '
            'sie zeigt den Vergleich deines Servers.',
            style: TextStyle(color: colors.muted, fontSize: 14),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _server,
            autocorrect: false,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(
              hintText: 'http://192.0.2.10:8000',
              prefixIcon: Icon(Icons.dns_outlined),
            ),
            onSubmitted: (_) => _saveServer(),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _apiKey,
            autocorrect: false,
            obscureText: true,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'API-Key (optional)',
              helperText:
                  'Nur nötig, wenn der Server öffentlich erreichbar ist.',
              helperMaxLines: 2,
              prefixIcon: Icon(Icons.key_outlined),
            ),
            onSubmitted: (_) => _saveServer(),
          ),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: _busy ? null : _saveServer,
            child: _busy
                ? const _ButtonSpinner()
                : const Text('Verbindung prüfen'),
          ),
        ],
      ),
    ),
  ];

  List<Widget> _searchForm(KorbColors colors) => [
    _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: _postalCode,
            // Plain digits. TextInputType.number still lets some Android
            // keyboards offer a signed or decimal pad.
            keyboardType: const TextInputType.numberWithOptions(
              signed: false,
              decimal: false,
            ),
            maxLength: 5,
            enabled: !_busy,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            style: const TextStyle(fontSize: 22, letterSpacing: 4),
            decoration:
                const InputDecoration(
                  labelText: 'Postleitzahl',
                  hintText: '26188',
                  counterText: '',
                ).copyWith(
                  suffixIcon: IconButton(
                    tooltip: 'PLZ vom aktuellen Standort übernehmen',
                    onPressed: _locating || _busy ? null : _useLocation,
                    icon: _locating
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.my_location),
                  ),
                ),
            onSubmitted: (_) => _search(),
            onChanged: (_) => _checkOffline(),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy ? null : _search,
            child: _busy
                ? const _ButtonSpinner()
                : const Text('Angebote vergleichen'),
          ),
        ],
      ),
    ),
    if (_progress != null) ...[
      const SizedBox(height: 16),
      _ProgressPanel(progress: _progress!),
    ],
    const SizedBox(height: 16),
    Center(
      child: TextButton.icon(
        onPressed: _busy ? null : _openSettings,
        icon: const Icon(Icons.settings_outlined, size: 18),
        label: Text(
          widget.settings.serverUrl,
          style: TextStyle(color: colors.muted, fontSize: 13),
        ),
      ),
    ),
  ];
}

class _Panel extends StatelessWidget {
  const _Panel({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.panel,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: colors.line),
      ),
      child: child,
    );
  }
}

class _ProgressPanel extends StatelessWidget {
  const _ProgressPanel({required this.progress});

  final SearchProgress progress;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final total = progress.totalSources > 0 ? progress.totalSources : 6;
    return _Panel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  progress.step,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ),
              Text(
                '${progress.progress}%',
                style: TextStyle(color: colors.muted),
              ),
            ],
          ),
          const SizedBox(height: 10),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: progress.progress <= 0 ? null : progress.progress / 100,
              minHeight: 8,
              backgroundColor: colors.chip,
              valueColor: AlwaysStoppedAnimation(colors.accent),
            ),
          ),
          const SizedBox(height: 10),
          Text(
            [
              if (progress.source.isNotEmpty) progress.source,
              if (progress.retailer.isNotEmpty) progress.retailer,
              '${progress.processedSources}/$total Quellen',
              '${progress.processedProducts} Angebote',
            ].join(' · '),
            style: TextStyle(color: colors.muted, fontSize: 13),
          ),
        ],
      ),
    );
  }
}

class _ErrorBox extends StatelessWidget {
  const _ErrorBox({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: colors.error.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.error.withValues(alpha: 0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline, color: colors.error, size: 20),
          const SizedBox(width: 10),
          Expanded(
            child: Text(message, style: TextStyle(color: colors.error)),
          ),
        ],
      ),
    );
  }
}

class _ButtonSpinner extends StatelessWidget {
  const _ButtonSpinner();

  @override
  Widget build(BuildContext context) => const SizedBox(
    height: 20,
    width: 20,
    child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white),
  );
}

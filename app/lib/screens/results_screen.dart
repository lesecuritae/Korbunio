import 'dart:async';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/client.dart';
import '../api/kitchenowl_client.dart';
import '../api/models.dart';
import '../services/settings.dart';
import '../services/offer_week.dart';
import '../services/offline_store.dart';
import '../services/local_shopping_list.dart';
import '../theme.dart';
import '../widgets/local_shopping_list_button.dart';
import '../widgets/offer_card.dart';

const _sortLabels = {
  'price': 'Preis mit Auswahl',
  'unit_price': 'Grundpreis mit Auswahl',
  'retailer': 'Händler',
  'product': 'Produktname',
};

/// The result list, mirroring the web results page: text filter, retailer
/// chips, category, sorting, duplicate view, loyalty programs, warnings and
/// endless scrolling.
class ResultsScreen extends StatefulWidget {
  const ResultsScreen({
    super.key,
    required this.client,
    required this.handle,
    required this.settings,
    required this.offlineStore,
    required this.localShoppingList,
    this.retailers = const [],
    this.nettoMarketId = '',
    this.nettoScottieMarketId = '',
    this.autoRefresh = false,
  });

  final KorbKlarClient client;
  final ResultHandle handle;
  final Settings settings;
  final OfflineStore offlineStore;
  final LocalShoppingListStore localShoppingList;

  /// Retailer selection the search was made with; reused for a fresh one.
  final List<String> retailers;
  final String nettoMarketId;
  final String nettoScottieMarketId;

  /// Start a new search for the same postal code right away and swap it in
  /// when it completes, while [handle] (or the offline store) is shown.
  final bool autoRefresh;

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  final _scroll = ScrollController();
  final _search = TextEditingController();
  final _offers = <Offer>[];

  ResultPage? _page;

  /// The comparison currently shown. Starts as the one handed in and moves
  /// on when a fresh search for the same postal code completes.
  late ResultHandle _handle = widget.handle;

  /// A fresh search running on the server while older data stays visible.
  StreamSubscription<SearchProgress>? _refreshWatch;
  SearchProgress? _refreshProgress;
  String _refreshError = '';
  bool get _refreshRunning => _refreshWatch != null;

  /// Offers filed in this session: offer key to article name.
  final _filed = <String, String>{};
  final _sending = <String>{};
  String _listId = '';
  ShoppingListInfo _shoppingList = ShoppingListInfo.disabled;
  KitchenOwlClient? _directKitchenOwl;
  bool _offline = false;

  String _retailer = '';
  String _category = '';
  String _sort = 'price';
  String _view = 'best_only';
  late List<String> _loyalty = [...widget.settings.loyaltyPrograms];

  int _nextPage = 1;
  bool _loading = false;
  bool _refreshing = false;

  /// Warnings the user has already read. Reset per result, so a new
  /// comparison surfaces its own problems again.
  bool _warningsSeen = false;
  bool _done = false;
  String _error = '';
  Timer? _debounce;

  /// Guards against a slow earlier request overwriting a newer result.
  int _requestSeq = 0;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    _reload();
    _loadShoppingList();
    if (widget.autoRefresh) _startFreshSearch();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _refreshWatch?.cancel();
    _directKitchenOwl?.close();
    _scroll.dispose();
    _search.dispose();
    super.dispose();
  }

  Future<void> _loadShoppingList() async {
    if (widget.settings.kitchenOwlUrl.isNotEmpty &&
        widget.settings.kitchenOwlToken.isNotEmpty) {
      final direct = KitchenOwlClient(
        baseUrl: widget.settings.kitchenOwlUrl,
        token: widget.settings.kitchenOwlToken,
      );
      _directKitchenOwl = direct;
      try {
        final targets = await direct.targets();
        if (!mounted) return;
        setState(() {
          _shoppingList = ShoppingListInfo(
            configured: true,
            targets: targets,
            defaultEntity: targets.length == 1 ? targets.first.entityId : '',
          );
          _listId =
              targets.any(
                (item) => item.entityId == widget.settings.shoppingListEntity,
              )
              ? widget.settings.shoppingListEntity
              : (targets.isNotEmpty ? targets.first.entityId : '');
        });
        return;
      } on KitchenOwlException {
        // Fall through to an optional server-side KitchenOwl adapter.
      }
    }
    try {
      final info = await widget.client.shoppingListTargets(_handle);
      if (!mounted) return;
      final known = info.targets.map((target) => target.entityId).toSet();
      final remembered = widget.settings.shoppingListEntity;
      setState(() {
        _shoppingList = info;
        _listId = known.contains(remembered)
            ? remembered
            : known.contains(info.defaultEntity)
            ? info.defaultEntity
            : (info.targets.isNotEmpty ? info.targets.first.entityId : '');
      });
      await _reconcileFiled();
    } on KorbKlarException {
      // A server without the integration is normal; the app just hides it.
    }
  }

  void _onScroll() {
    if (_scroll.position.pixels >= _scroll.position.maxScrollExtent - 600) {
      _loadMore();
    }
  }

  void _reload() {
    _requestSeq++;
    setState(() {
      _warningsSeen = false;
      _offers.clear();
      _nextPage = 1;
      _done = false;
      _error = '';
    });
    _loadMore();
  }

  Future<void> _loadMore() async {
    if (_loading || _done) return;
    final seq = _requestSeq;
    setState(() => _loading = true);
    try {
      final cacheKey = widget.offlineStore.key(
        postalCode: widget.settings.postalCode,
        filterText: _search.text,
        retailer: _retailer,
        category: _category,
        page: _nextPage,
        view: _view,
        loyalty: _loyalty,
        sort: _sort,
      );
      final page = await widget.client.results(
        _handle,
        filterText: _search.text,
        retailer: _retailer,
        category: _category,
        page: _nextPage,
        view: _view,
        loyaltyPrograms: _loyalty,
        sort: _sort,
      );
      if (!mounted || seq != _requestSeq) return;
      await widget.offlineStore.save(cacheKey, page);
      setState(() {
        _offline = false;
        _page = page;
        _offers.addAll(page.offers);
        _nextPage = page.page + 1;
        _done = !page.hasNext;
      });
    } on KorbKlarException catch (exception) {
      if (!mounted || seq != _requestSeq) return;
      final cacheKey = widget.offlineStore.key(
        postalCode: widget.settings.postalCode,
        filterText: _search.text,
        retailer: _retailer,
        category: _category,
        page: _nextPage,
        view: _view,
        loyalty: _loyalty,
        sort: _sort,
      );
      final cached = await widget.offlineStore.load(cacheKey);
      if (!mounted || seq != _requestSeq) return;
      if (cached != null) {
        setState(() {
          _offline = true;
          _page = cached;
          _offers.addAll(cached.offers);
          _nextPage = cached.page + 1;
          _done = !cached.hasNext;
          _error = 'Offline: gespeicherte Daten werden angezeigt.';
        });
      } else {
        setState(() {
          _error = exception.message;
          _done = true;
        });
      }
    } finally {
      if (mounted && seq == _requestSeq) setState(() => _loading = false);
    }
  }

  /// Re-queries every source for this postal code, bypassing the server's
  /// snapshot cache, then swaps in the new result.
  /// Re-reads the stored comparison for this result.
  ///
  /// Deliberately does not start a new search: the server keeps a snapshot
  /// and re-querying every retailer takes minutes. It also used to replace
  /// the route, which ended the caller's await in the previous screen and
  /// closed the HTTP client this screen was still using.
  Future<void> _refreshFromCache() async {
    if (_refreshing) return;
    setState(() => _refreshing = true);
    _reload();
    await _reconcileFiled();
    if (mounted) setState(() => _refreshing = false);
  }

  /// Starts a new search for the same postal code and swaps the result in
  /// once it completes.
  ///
  /// What is on screen stays on screen meanwhile: a comparison from before
  /// Thursday is still a comparison, only not the current one. The server's
  /// snapshot cache decides whether the retailers are actually queried again,
  /// so within its window this is one request and a few seconds; after an
  /// offer change it takes as long as any search.
  Future<void> _startFreshSearch() async {
    if (_refreshRunning) return;
    final postalCode = widget.settings.postalCode;
    if (!RegExp(r'^\d{5}$').hasMatch(postalCode)) return;
    setState(() {
      _refreshError = '';
      _refreshProgress = null;
    });
    String jobId;
    try {
      jobId = await widget.client.startSearch(
        postalCode,
        retailers: widget.retailers,
        nettoMarketId: widget.nettoMarketId,
        nettoScottieMarketId: widget.nettoScottieMarketId,
      );
    } on KorbKlarException catch (exception) {
      if (mounted) setState(() => _refreshError = exception.message);
      return;
    }
    if (!mounted) return;
    _refreshWatch = widget.client
        .watchSearch(jobId)
        .listen(
          (progress) async {
            if (!mounted) return;
            setState(() => _refreshProgress = progress);
            if (progress.isFailed) {
              _endRefresh(
                progress.error.isNotEmpty
                    ? progress.error
                    : 'Die Suche ist fehlgeschlagen.',
              );
              return;
            }
            if (!progress.isDone) return;
            final handle = ResultHandle.parse(progress.resultPath);
            if (handle == null) {
              _endRefresh('Der Server lieferte keinen gültigen Ergebnislink.');
              return;
            }
            await widget.settings.setLastSearch(
              LastSearch(
                postalCode: postalCode,
                retailers: widget.retailers,
                searchId: handle.searchId,
                token: handle.token,
                searchedAt: DateTime.now(),
              ),
            );
            if (!mounted) return;
            _handle = handle;
            _endRefresh('');
            _reload();
            await _reconcileFiled();
          },
          onError: (Object error) {
            if (!mounted) return;
            _endRefresh(error is KorbKlarException ? error.message : '$error');
          },
        );
    setState(() {});
  }

  void _endRefresh(String error) {
    _refreshWatch?.cancel();
    _refreshWatch = null;
    setState(() {
      _refreshProgress = null;
      _refreshError = error;
    });
  }

  /// Drops offers whose article was checked off in KitchenOwl meanwhile.
  ///
  /// Checking an entry off removes it there, so the app must not keep
  /// claiming it is still on the list.
  Future<void> _reconcileFiled() async {
    if (_listId.isEmpty || _filed.isEmpty) return;
    try {
      final direct = _directKitchenOwl;
      final pending = direct != null
          ? await direct.entries(_listId)
          : await widget.client.listEntries(_handle, _listId);
      if (!mounted) return;
      setState(() {
        _filed.removeWhere((_, article) => !pending.contains(article));
      });
    } on KorbKlarException {
      // Leaving the marks as they are beats guessing they are gone.
    } on KitchenOwlException {
      // Same here.
    }
  }

  bool get _kitchenOwlAvailable =>
      _shoppingList.configured && _shoppingList.targets.isNotEmpty;

  /// Whether the local list is offered at all. It goes away only when the
  /// user chose KitchenOwl alone and that KitchenOwl is actually reachable,
  /// so an offer can always go somewhere.
  bool get _localListShown =>
      !widget.settings.kitchenOwlOnly || !_kitchenOwlAvailable;

  void _onSearchChanged(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), _reload);
  }

  // -------------------------------------------------------- Einkaufsliste

  /// Adds one offer to the app's local shopping list.
  Future<void> _addToList(Offer offer) async {
    setState(() => _sending.add(offer.key));
    try {
      await widget.localShoppingList.add(offer);
      if (mounted) _toast('Zur lokalen Einkaufsliste hinzugefügt.');
    } on Object catch (exception) {
      _toast('$exception');
    } finally {
      if (mounted) setState(() => _sending.remove(offer.key));
    }
  }

  /// Files one offer in the selected KitchenOwl list.
  ///
  /// No collecting step: a tap is the whole interaction. The article lands
  /// on what the household already keeps where one matches, and under a
  /// category named after the shop; see `kitchenowl_articles.dart`.
  Future<void> _addToKitchenOwl(Offer offer) async {
    final entity = _listId.isNotEmpty ? _listId : await _resolveEntity();
    if (entity == null || entity.isEmpty) return;
    final target = _shoppingList.targets.firstWhere(
      (target) => target.entityId == entity,
      orElse: () => const ShoppingListTarget(entityId: '', label: 'KitchenOwl'),
    );
    setState(() => _sending.add(offer.key));
    try {
      final direct = _directKitchenOwl;
      final added = direct != null
          ? [
              await direct.addOffer(
                entity,
                offer,
                householdId: target.householdId,
              ),
            ]
          : await widget.client.addToShoppingList(
              _handle,
              entityId: entity,
              offers: [offer],
            );
      if (!mounted) return;
      final article = added.isNotEmpty ? added.first : offer.product;
      setState(() => _filed[offer.key] = article);
      _toast('„$article“ liegt in „${target.label}“.');
    } on Object catch (exception) {
      final message = exception is KorbKlarException
          ? exception.message
          : exception is KitchenOwlException
          ? exception.message
          : '$exception';
      _toast(message);
    } finally {
      if (mounted) setState(() => _sending.remove(offer.key));
    }
  }

  Future<String?> _resolveEntity() async {
    final targets = _shoppingList.targets;
    if (targets.isEmpty) return null;

    final remembered = widget.settings.shoppingListEntity;
    final known = targets.map((target) => target.entityId).toSet();
    if (remembered.isNotEmpty && known.contains(remembered)) return remembered;
    if (known.contains(_shoppingList.defaultEntity)) {
      return _shoppingList.defaultEntity;
    }
    if (targets.length == 1) return targets.first.entityId;

    final chosen = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: context.colors.panel,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 18, 20, 6),
              child: Text(
                'Ziel-Liste wählen',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
              ),
            ),
            for (final target in targets)
              ListTile(
                leading: const Icon(Icons.checklist),
                title: Text(target.label),
                onTap: () => Navigator.pop(sheetContext, target.entityId),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (chosen != null) {
      await widget.settings.setShoppingListEntity(chosen);
      if (mounted) setState(() => _listId = chosen);
    }
    return chosen;
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  // ------------------------------------------------------------- Sheets

  Future<void> _openLoyalty() async {
    final programs =
        _page?.availableLoyaltyPrograms ?? const <LoyaltyProgram>[];
    if (programs.isEmpty) return;
    final selected = {..._loyalty};
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: context.colors.panel,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (_, setSheetState) => SafeArea(
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Padding(
                  padding: EdgeInsets.fromLTRB(20, 18, 20, 4),
                  child: Text(
                    'Bonusprogramme',
                    style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
                  ),
                ),
                for (final program in programs)
                  CheckboxListTile(
                    value: selected.contains(program.id),
                    title: Text(program.label),
                    subtitle: program.note.isEmpty ? null : Text(program.note),
                    onChanged: (checked) => setSheetState(() {
                      if (checked == true) {
                        selected.add(program.id);
                      } else {
                        selected.remove(program.id);
                      }
                    }),
                  ),
                if ((_page?.loyaltyNote ?? '').isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 4, 20, 10),
                    child: Text(
                      _page!.loyaltyNote,
                      style: TextStyle(
                        color: context.colors.muted,
                        fontSize: 12,
                      ),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
                  child: FilledButton(
                    onPressed: () => Navigator.pop(sheetContext),
                    child: const Text('Übernehmen'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
    final next = selected.toList();
    if (next.join(',') == _loyalty.join(',')) return;
    await widget.settings.setLoyaltyPrograms(next);
    setState(() => _loyalty = next);
    _reload();
  }

  Future<void> _openWarnings() async {
    final warnings = _page?.warnings ?? const <String>[];
    if (warnings.isEmpty) return;
    setState(() => _warningsSeen = true);
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: context.colors.panel,
      builder: (_) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.all(20),
          children: [
            const Text(
              'Hinweise oder Fehler',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 10),
            for (final warning in warnings)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(warning),
              ),
          ],
        ),
      ),
    );
  }

  // -------------------------------------------------------------- Build

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final page = _page;
    final warnings = page?.warnings ?? const <String>[];

    return Scaffold(
      appBar: AppBar(
        backgroundColor: colors.bg,
        surfaceTintColor: Colors.transparent,
        // Up to five actions sit on the right; on a narrow phone the title
        // gets whatever is left, so it must shrink instead of overflowing.
        titleSpacing: 0,
        // The title doubles as the way to a different postal code: with the
        // app opening straight into the results, this is where a user looks.
        title: Tooltip(
          message: 'Neue Suche mit anderer PLZ',
          child: InkWell(
            borderRadius: BorderRadius.circular(8),
            onTap: () => Navigator.of(context).maybePop(),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Flexible(
                    child: Text(
                      page == null ? 'Angebote' : 'PLZ ${page.postalCode}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(width: 6),
                  Icon(
                    Icons.edit_location_alt_outlined,
                    size: 18,
                    color: colors.muted,
                  ),
                ],
              ),
            ),
          ),
        ),
        actions: [
          if (_offline)
            // An icon, not a chip: a chip plus four buttons left the title
            // no room on a phone.
            Tooltip(
              message: 'Offline: gespeicherte Daten',
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 6),
                child: Icon(Icons.cloud_off_outlined, color: colors.muted),
              ),
            ),
          if (_localListShown)
            LocalShoppingListButton(store: widget.localShoppingList),
          IconButton(
            tooltip: _offline
                ? 'Gespeicherte Ergebnisse neu lesen'
                : 'Angebote neu laden',
            onPressed: _refreshing || _refreshRunning
                ? null
                : _offline
                ? _refreshFromCache
                : _startFreshSearch,
            icon: _refreshing || _refreshRunning
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2.2),
                  )
                : const Icon(Icons.refresh),
          ),
          if (warnings.isNotEmpty)
            IconButton(
              tooltip: 'Hinweise',
              onPressed: _openWarnings,
              icon: _warningsSeen
                  ? Icon(Icons.warning_amber_rounded, color: colors.muted)
                  : Badge(
                      label: Text('${warnings.length}'),
                      child: const Icon(Icons.warning_amber_rounded),
                    ),
            ),
          if ((page?.availableLoyaltyPrograms ?? []).isNotEmpty)
            IconButton(
              tooltip: 'Bonusprogramme',
              onPressed: _openLoyalty,
              icon: Icon(
                _loyalty.isEmpty ? Icons.loyalty_outlined : Icons.loyalty,
              ),
            ),
        ],
      ),
      body: Column(
        children: [
          _controls(colors),
          if (_refreshRunning || _refreshError.isNotEmpty)
            _RefreshBanner(
              progress: _refreshProgress,
              error: _refreshError,
              stale: widget.autoRefresh,
              onRetry: _startFreshSearch,
              onDismiss: () => setState(() => _refreshError = ''),
            ),
          if (_shoppingList.configured && _shoppingList.targets.isNotEmpty)
            _listBar(colors),
          if (page != null) _chips(page, colors),
          const Divider(height: 1),
          Expanded(child: _list(colors)),
        ],
      ),
    );
  }

  /// Names the list every tap files into, so the destination is visible
  /// before anything is sent.
  Widget _listBar(KorbColors colors) => Padding(
    padding: const EdgeInsets.fromLTRB(12, 0, 12, 6),
    child: Row(
      children: [
        Text(
          'KitchenOwl',
          style: TextStyle(
            color: colors.accent,
            fontWeight: FontWeight.w700,
            fontSize: 12,
            letterSpacing: 0.4,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: DropdownButtonFormField<String>(
            initialValue: _listId.isEmpty ? null : _listId,
            isExpanded: true,
            decoration: const InputDecoration(
              isDense: true,
              contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            ),
            items: [
              for (final target in _shoppingList.targets)
                DropdownMenuItem(
                  value: target.entityId,
                  child: Text(target.label, overflow: TextOverflow.ellipsis),
                ),
            ],
            onChanged: (value) {
              if (value == null) return;
              setState(() => _listId = value);
              widget.settings.setShoppingListEntity(value);
            },
          ),
        ),
      ],
    ),
  );

  Widget _controls(KorbColors colors) => Padding(
    padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
    child: Column(
      children: [
        TextField(
          controller: _search,
          onChanged: _onSearchChanged,
          decoration: InputDecoration(
            hintText: 'Produkt oder Marke filtern',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _search.text.isEmpty
                ? null
                : IconButton(
                    icon: const Icon(Icons.clear),
                    onPressed: () {
                      _search.clear();
                      _reload();
                    },
                  ),
          ),
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _sort,
                isExpanded: true,
                decoration: const InputDecoration(
                  contentPadding: EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 8,
                  ),
                ),
                items: [
                  for (final entry in _sortLabels.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(entry.value, overflow: TextOverflow.ellipsis),
                    ),
                ],
                onChanged: (value) {
                  if (value == null || value == _sort) return;
                  setState(() => _sort = value);
                  _reload();
                },
              ),
            ),
            const SizedBox(width: 8),
            _ViewToggle(
              view: _view,
              hiddenCount: _page?.hiddenCount ?? 0,
              onChanged: (value) {
                setState(() => _view = value);
                _reload();
              },
            ),
          ],
        ),
      ],
    ),
  );

  Widget _chips(ResultPage page, KorbColors colors) {
    final entries = page.retailerCounts.entries.toList()
      ..sort((a, b) => a.key.toLowerCase().compareTo(b.key.toLowerCase()));
    final total = entries.fold<int>(0, (sum, entry) => sum + entry.value);

    return SizedBox(
      height: 46,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        children: [
          _Chip(
            label: 'Alle Händler · $total',
            active: _retailer.isEmpty,
            onTap: () {
              setState(() {
                _retailer = '';
                _category = '';
              });
              _reload();
            },
          ),
          for (final entry in entries)
            _Chip(
              label: '${entry.key} · ${entry.value}',
              active: _retailer == entry.key,
              onTap: () {
                setState(() {
                  _retailer = entry.key;
                  _category = '';
                });
                _reload();
              },
            ),
        ],
      ),
    );
  }

  Widget _list(KorbColors colors) {
    final page = _page;
    if (_error.isNotEmpty && _offers.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_error, textAlign: TextAlign.center),
        ),
      );
    }
    if (page == null && _loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_offers.isEmpty && !_loading) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            'Keine Angebote passen zu diesem Filter.',
            style: TextStyle(color: colors.muted),
          ),
        ),
      );
    }

    return ListView.separated(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 24),
      itemCount: _offers.length + 1,
      separatorBuilder: (_, _) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        if (index == _offers.length) return _footer(colors);
        final offer = _offers[index];
        return OfferCard(
          offer: offer,
          imageUrl: widget.client.imageUrl(offer.imageUrl),
          imageHeaders: widget.client.imageHeaders,
          showRetailer: _retailer.isEmpty,
          filedIn: _filed[offer.key],
          sending: _sending.contains(offer.key),
          // The local list is its own button and never relabelled by
          // KitchenOwl state; it only disappears when the user asked for
          // KitchenOwl alone.
          onAddToList: _localListShown ? () => _addToList(offer) : null,
          onAddToKitchenOwl: _kitchenOwlAvailable
              ? () => _addToKitchenOwl(offer)
              : null,
          onOpenSource: () => launchUrl(
            Uri.parse(offer.sourceUrl),
            mode: LaunchMode.externalApplication,
          ),
        );
      },
    );
  }

  Widget _footer(KorbColors colors) {
    if (_loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Center(child: CircularProgressIndicator()),
      );
    }
    final page = _page;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 20),
      child: Center(
        child: Text(
          _error.isNotEmpty
              ? _error
              : page == null
              ? ''
              : '${page.filteredOfferCount} passende Treffer · '
                    '${page.hiddenCount} teurere Dubletten '
                    '${_view == 'all' ? 'eingeblendet' : 'ausgeblendet'}',
          textAlign: TextAlign.center,
          style: TextStyle(
            color: _error.isNotEmpty ? colors.error : colors.muted,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}

/// A slim strip above the list while a fresh search runs, or after one
/// failed. The list underneath stays usable throughout.
class _RefreshBanner extends StatelessWidget {
  const _RefreshBanner({
    required this.progress,
    required this.error,
    required this.stale,
    required this.onRetry,
    required this.onDismiss,
  });

  final SearchProgress? progress;
  final String error;

  /// Whether the refresh was started because an offer change lies behind
  /// the shown result, which is worth saying, or by hand, which is not.
  final bool stale;
  final VoidCallback onRetry;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (error.isNotEmpty) {
      return Container(
        margin: const EdgeInsets.fromLTRB(12, 0, 12, 6),
        padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
        decoration: BoxDecoration(
          color: colors.error.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: colors.error.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                'Aktualisierung fehlgeschlagen: $error',
                style: TextStyle(color: colors.error, fontSize: 13),
              ),
            ),
            TextButton(onPressed: onRetry, child: const Text('Erneut')),
            IconButton(
              tooltip: 'Ausblenden',
              onPressed: onDismiss,
              icon: const Icon(Icons.close, size: 18),
            ),
          ],
        ),
      );
    }
    final percent = progress?.progress ?? 0;
    final reason = stale
        ? 'Neue Angebote seit ${OfferWeek.lastChangeLabel(DateTime.now())}'
        : 'Angebote werden neu geladen';
    final detail = [
      if ((progress?.step ?? '').isNotEmpty) progress!.step,
      if ((progress?.retailer ?? '').isNotEmpty) progress!.retailer,
    ].join(' · ');
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 0, 12, 6),
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
      decoration: BoxDecoration(
        color: colors.chip,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '$reason · Vergleich wird aktualisiert',
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Text(
                '$percent %',
                style: TextStyle(color: colors.muted, fontSize: 13),
              ),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: percent <= 0 ? null : percent / 100,
              minHeight: 5,
              backgroundColor: colors.panel,
              valueColor: AlwaysStoppedAnimation(colors.accent),
            ),
          ),
          if (detail.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              detail,
              style: TextStyle(color: colors.muted, fontSize: 12),
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.active, required this.onTap});

  final String label;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Padding(
      padding: const EdgeInsets.only(right: 7),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: active ? colors.chip : colors.panel,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: active ? colors.accent : colors.line),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: active ? FontWeight.w600 : FontWeight.w400,
            ),
          ),
        ),
      ),
    );
  }
}

class _ViewToggle extends StatelessWidget {
  const _ViewToggle({
    required this.view,
    required this.hiddenCount,
    required this.onChanged,
  });

  final String view;
  final int hiddenCount;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final showingAll = view == 'all';
    return Tooltip(
      message: showingAll
          ? 'Nur günstigste Treffer zeigen'
          : 'Teurere Dubletten einblenden',
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: () => onChanged(showingAll ? 'best_only' : 'all'),
        child: Container(
          height: 48,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: showingAll ? colors.chip : colors.panel,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: showingAll ? colors.accent : colors.line),
          ),
          child: Row(
            children: [
              Icon(
                showingAll ? Icons.layers : Icons.layers_outlined,
                size: 18,
                color: showingAll ? colors.accent : colors.muted,
              ),
              if (hiddenCount > 0) ...[
                const SizedBox(width: 6),
                Text('$hiddenCount', style: const TextStyle(fontSize: 13)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

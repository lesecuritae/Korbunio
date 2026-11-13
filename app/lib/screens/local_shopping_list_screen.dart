import 'package:material_ui/material_ui.dart';

import '../services/local_shopping_list.dart';
import '../services/shopping_list.dart';

class LocalShoppingListScreen extends StatefulWidget {
  const LocalShoppingListScreen({super.key, required this.store});
  final LocalShoppingListStore store;

  @override
  State<LocalShoppingListScreen> createState() =>
      _LocalShoppingListScreenState();
}

class _LocalShoppingListScreenState extends State<LocalShoppingListScreen> {
  List<LocalShoppingListEntry> _entries = const [];

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    final entries = await widget.store.loadEntries();
    if (mounted) setState(() => _entries = entries);
  }

  Future<void> _remove(LocalShoppingListEntry entry) async {
    final index = _entries.indexOf(entry);
    final messenger = ScaffoldMessenger.of(context);
    await widget.store.remove(entry.offer.key);
    await _reload();
    if (!mounted) return;
    messenger
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          content: Text('${entry.offer.product} entfernt.'),
          action: SnackBarAction(
            label: 'Rückgängig',
            onPressed: () async {
              await widget.store.restore(entry, index);
              await _reload();
            },
          ),
        ),
      );
  }

  Future<void> _confirmClear() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Liste leeren?'),
        content: Text(
          'Alle ${_entries.length} Einträge werden von der lokalen '
          'Einkaufsliste entfernt.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Abbrechen'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Leeren'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await widget.store.clear();
    await _reload();
  }

  String _euro(double value) =>
      '${value.toStringAsFixed(2).replaceAll('.', ',')} €';

  double get _knownGoodsTotal =>
      _entries.fold(0, (sum, entry) => sum + (entry.goodsTotal ?? 0));

  double get _depositTotal =>
      _entries.fold(0, (sum, entry) => sum + entry.depositTotal);

  double get _knownTotal => _knownGoodsTotal + _depositTotal;

  int get _unknownPrices =>
      _entries.where((entry) => entry.lineTotal == null).length;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Lokale Einkaufsliste'),
      actions: [
        IconButton(
          tooltip: 'Liste leeren',
          onPressed: _entries.isEmpty ? null : _confirmClear,
          icon: const Icon(Icons.delete_sweep_outlined),
        ),
        IconButton(
          tooltip: 'Liste kopieren',
          onPressed: _entries.isEmpty
              ? null
              : () async {
                  await const ShoppingListText().copy([
                    for (final entry in _entries)
                      for (var index = 0; index < entry.quantity; index++)
                        entry.offer,
                  ]);
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Liste kopiert.')),
                  );
                },
          icon: const Icon(Icons.copy_all_outlined),
        ),
      ],
    ),
    body: _entries.isEmpty
        ? const Center(child: Text('Die lokale Einkaufsliste ist leer.'))
        : Column(
            children: [
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.all(12),
                  itemCount: _entries.length,
                  separatorBuilder: (_, _) => const Divider(),
                  itemBuilder: (_, index) => _EntryTile(
                    entry: _entries[index],
                    onQuantity: (quantity) async {
                      await widget.store.setQuantity(
                        _entries[index].offer.key,
                        quantity,
                      );
                      await _reload();
                    },
                    onRemove: () => _remove(_entries[index]),
                  ),
                ),
              ),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      _TotalRow(label: 'Waren', value: _euro(_knownGoodsTotal)),
                      _TotalRow(label: 'Pfand', value: _euro(_depositTotal)),
                      const Divider(),
                      _TotalRow(
                        label: _unknownPrices == 0
                            ? 'Gesamtsumme'
                            : 'Bekannte Gesamtsumme',
                        value: _euro(_knownTotal),
                        emphasized: true,
                      ),
                      if (_unknownPrices > 0)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(
                            'Für $_unknownPrices Position(en) ist kein Preis bekannt.',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
  );
}

/// One list entry. Product and retailer get their own lines and the controls
/// sit on a row of their own, so nothing is pushed off the edge on narrow
/// screens or with a large system font.
class _EntryTile extends StatelessWidget {
  const _EntryTile({
    required this.entry,
    required this.onQuantity,
    required this.onRemove,
  });

  final LocalShoppingListEntry entry;
  final ValueChanged<int> onQuantity;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final offer = entry.offer;
    final theme = Theme.of(context);
    final details = ShoppingListText.detailsFor(offer);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            offer.product,
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              if (offer.retailerText.isNotEmpty)
                Chip(
                  label: Text(offer.retailerText),
                  avatar: const Icon(Icons.storefront_outlined, size: 16),
                  visualDensity: VisualDensity.compact,
                  materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                ),
              if (details.isNotEmpty)
                Text(details, style: theme.textTheme.bodyMedium),
            ],
          ),
          Row(
            children: [
              IconButton(
                tooltip: 'Menge verringern',
                onPressed: entry.quantity <= 1
                    ? null
                    : () => onQuantity(entry.quantity - 1),
                icon: const Icon(Icons.remove_circle_outline),
              ),
              Text(
                '${entry.quantity}',
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              IconButton(
                tooltip: 'Menge erhöhen',
                onPressed: entry.quantity >= 99
                    ? null
                    : () => onQuantity(entry.quantity + 1),
                icon: const Icon(Icons.add_circle_outline),
              ),
              const Spacer(),
              IconButton(
                tooltip: 'Entfernen',
                onPressed: onRemove,
                icon: const Icon(Icons.delete_outline),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TotalRow extends StatelessWidget {
  const _TotalRow({
    required this.label,
    required this.value,
    this.emphasized = false,
  });

  final String label;
  final String value;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final style = emphasized
        ? const TextStyle(fontSize: 20, fontWeight: FontWeight.w800)
        : null;
    // The label may wrap on a narrow screen or with a large system font;
    // the amount always keeps its full width so it is never cut off.
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: Text(label, style: style)),
        const SizedBox(width: 12),
        Text(value, style: style),
      ],
    );
  }
}

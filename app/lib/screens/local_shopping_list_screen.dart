import 'package:flutter/material.dart';

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
                  itemBuilder: (_, index) {
                    final entry = _entries[index];
                    final offer = entry.offer;
                    return ListTile(
                      title: Text(offer.product),
                      subtitle: Text(ShoppingListText.lineFor(offer)),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            tooltip: 'Menge verringern',
                            onPressed: entry.quantity <= 1
                                ? null
                                : () async {
                                    await widget.store.setQuantity(
                                      offer.key,
                                      entry.quantity - 1,
                                    );
                                    await _reload();
                                  },
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
                                : () async {
                                    await widget.store.setQuantity(
                                      offer.key,
                                      entry.quantity + 1,
                                    );
                                    await _reload();
                                  },
                            icon: const Icon(Icons.add_circle_outline),
                          ),
                          IconButton(
                            tooltip: 'Entfernen',
                            onPressed: () async {
                              await widget.store.remove(offer.key);
                              await _reload();
                            },
                            icon: const Icon(Icons.delete_outline),
                          ),
                        ],
                      ),
                    );
                  },
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
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: style),
        Text(value, style: style),
      ],
    );
  }
}

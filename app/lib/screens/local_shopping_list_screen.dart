import 'package:flutter/material.dart';

import '../api/models.dart';
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
  List<Offer> _offers = const [];

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    final offers = await widget.store.load();
    if (mounted) setState(() => _offers = offers);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Lokale Einkaufsliste'),
      actions: [
        IconButton(
          tooltip: 'Liste kopieren',
          onPressed: _offers.isEmpty
              ? null
              : () async {
                  await const ShoppingListText().copy(_offers);
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Liste kopiert.')),
                  );
                },
          icon: const Icon(Icons.copy_all_outlined),
        ),
      ],
    ),
    body: _offers.isEmpty
        ? const Center(child: Text('Die lokale Einkaufsliste ist leer.'))
        : ListView.separated(
            padding: const EdgeInsets.all(12),
            itemCount: _offers.length,
            separatorBuilder: (_, _) => const Divider(),
            itemBuilder: (_, index) {
              final offer = _offers[index];
              return ListTile(
                title: Text(offer.product),
                subtitle: Text(ShoppingListText.lineFor(offer)),
                trailing: IconButton(
                  tooltip: 'Entfernen',
                  onPressed: () async {
                    await widget.store.remove(offer.key);
                    await _reload();
                  },
                  icon: const Icon(Icons.delete_outline),
                ),
              );
            },
          ),
  );
}

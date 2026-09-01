import 'package:flutter/material.dart';

import '../screens/local_shopping_list_screen.dart';
import '../services/local_shopping_list.dart';

class LocalShoppingListButton extends StatelessWidget {
  const LocalShoppingListButton({super.key, required this.store});

  final LocalShoppingListStore store;

  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: 'Lokale Einkaufsliste',
    onPressed: () => Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => LocalShoppingListScreen(store: store),
      ),
    ),
    icon: const Icon(Icons.shopping_basket_outlined),
  );
}

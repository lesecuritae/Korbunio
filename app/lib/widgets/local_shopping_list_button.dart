import 'package:material_ui/material_ui.dart';

import '../screens/local_shopping_list_screen.dart';
import '../services/local_shopping_list.dart';

class LocalShoppingListButton extends StatelessWidget {
  const LocalShoppingListButton({
    super.key,
    required this.store,
    this.onClosed,
  });

  final LocalShoppingListStore store;

  /// Called when the list screen is closed again, so a caller that shows
  /// list membership can refresh what may have been removed meanwhile.
  final VoidCallback? onClosed;

  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: 'Lokale Einkaufsliste',
    onPressed: () async {
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => LocalShoppingListScreen(store: store),
        ),
      );
      onClosed?.call();
    },
    icon: const Icon(Icons.shopping_basket_outlined),
  );
}

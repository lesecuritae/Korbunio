import 'package:flutter/material.dart';

import 'screens/home_screen.dart';
import 'services/settings.dart';
import 'services/offline_store.dart';
import 'services/local_shopping_list.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = await Settings.load();
  final offlineStore = await OfflineStore.open();
  final localShoppingList = await LocalShoppingListStore.open();
  runApp(
    KorbKlarApp(
      settings: settings,
      offlineStore: offlineStore,
      localShoppingList: localShoppingList,
    ),
  );
}

class KorbKlarApp extends StatelessWidget {
  const KorbKlarApp({
    super.key,
    required this.settings,
    required this.offlineStore,
    required this.localShoppingList,
  });

  final Settings settings;
  final OfflineStore offlineStore;
  final LocalShoppingListStore localShoppingList;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KorbKlar',
      debugShowCheckedModeBanner: false,
      theme: korbLightTheme(),
      darkTheme: korbDarkTheme(),
      // The web interface declares `color-scheme: light dark`, so the app
      // follows the system setting the same way.
      themeMode: ThemeMode.system,
      home: HomeScreen(
        settings: settings,
        offlineStore: offlineStore,
        localShoppingList: localShoppingList,
      ),
    );
  }
}

/// The wordmark used on both screens, matching the web header.
class KorbKlarWordmark extends StatelessWidget {
  const KorbKlarWordmark({super.key, this.fontSize = 25});

  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Text.rich(
      TextSpan(
        children: [
          TextSpan(
            text: 'Korb',
            style: TextStyle(color: colors.text),
          ),
          TextSpan(
            text: 'Klar',
            style: TextStyle(color: colors.accent),
          ),
        ],
      ),
      style: TextStyle(fontSize: fontSize, fontWeight: FontWeight.w700),
    );
  }
}

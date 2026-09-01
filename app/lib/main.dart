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

class KorbKlarApp extends StatefulWidget {
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
  State<KorbKlarApp> createState() => _KorbKlarAppState();
}

class _KorbKlarAppState extends State<KorbKlarApp> {
  ThemeMode get _themeMode => switch (widget.settings.themeMode) {
    'light' => ThemeMode.light,
    'dark' => ThemeMode.dark,
    _ => ThemeMode.system,
  };

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'KorbKlar',
      debugShowCheckedModeBanner: false,
      theme: korbLightTheme(),
      darkTheme: korbDarkTheme(),
      themeMode: _themeMode,
      home: HomeScreen(
        settings: widget.settings,
        offlineStore: widget.offlineStore,
        localShoppingList: widget.localShoppingList,
        onThemeChanged: () => setState(() {}),
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

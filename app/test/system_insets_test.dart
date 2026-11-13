import 'dart:io';

import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korbunio_app/screens/home_screen.dart';
import 'package:korbunio_app/screens/local_shopping_list_screen.dart';
import 'package:korbunio_app/screens/settings_screen.dart';
import 'package:korbunio_app/services/local_shopping_list.dart';
import 'package:korbunio_app/services/offline_store.dart';
import 'package:korbunio_app/services/settings.dart';
import 'package:korbunio_app/theme.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A phone with a tall status bar / cutout, a small display and a large
/// system font: the setup where content used to reach under the status bar.
const _statusBar = 48.0; // logical pixels
const _ratio = 3.0;

Future<void> _phone(WidgetTester tester, {double textScale = 1.0}) async {
  tester.view.devicePixelRatio = _ratio;
  tester.view.physicalSize = const Size(360, 700) * _ratio;
  tester.view.padding = const FakeViewPadding(top: _statusBar * _ratio);
  tester.view.viewPadding = const FakeViewPadding(top: _statusBar * _ratio);
  tester.platformDispatcher.textScaleFactorTestValue = textScale;
  addTearDown(tester.view.reset);
  addTearDown(tester.platformDispatcher.clearAllTestValues);
}

/// Every control a finger can hit must start below the status bar.
void _expectBelowStatusBar(WidgetTester tester) {
  final controls = <Finder>[
    find.byType(IconButton),
    find.byType(TextField),
    find.byType(TextButton),
    find.byType(FilledButton),
    find.byType(OutlinedButton),
    find.byType(ElevatedButton),
  ];
  var checked = 0;
  for (final finder in controls) {
    for (final element in finder.evaluate()) {
      final top = tester.getTopLeft(find.byWidget(element.widget)).dy;
      expect(
        top,
        greaterThanOrEqualTo(_statusBar - 0.5),
        reason:
            '${element.widget.runtimeType} starts at $top dp, '
            'under the ${_statusBar}dp status bar',
      );
      checked++;
    }
  }
  expect(checked, greaterThan(0), reason: 'no controls found to check');
}

void main() {
  Future<HomeScreen> home() async {
    SharedPreferences.setMockInitialValues({});
    final settings = await Settings.load();
    final offlineStore = await OfflineStore.open(
      directory: await Directory.systemTemp.createTemp('korbunio-inset-off-'),
    );
    final list = await LocalShoppingListStore.open(
      directory: await Directory.systemTemp.createTemp('korbunio-inset-list-'),
    );
    return HomeScreen(
      settings: settings,
      offlineStore: offlineStore,
      localShoppingList: list,
      onThemeChanged: () {},
    );
  }

  for (final scale in [1.0, 1.5]) {
    testWidgets('home screen clears the status bar (font ${scale}x)', (
      tester,
    ) async {
      await _phone(tester, textScale: scale);
      final screen = await tester.runAsync(home);
      await tester.pumpWidget(
        MaterialApp(theme: korbLightTheme(), home: screen),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      _expectBelowStatusBar(tester);
    });
  }

  testWidgets('shopping list screen clears the status bar', (tester) async {
    await _phone(tester, textScale: 1.5);
    final list = await tester.runAsync(
      () async => LocalShoppingListStore.open(
        directory: await Directory.systemTemp.createTemp('korbunio-inset-l2-'),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: korbLightTheme(),
        home: LocalShoppingListScreen(store: list!),
      ),
    );
    await tester.pumpAndSettle();
    _expectBelowStatusBar(tester);
  });

  testWidgets('settings screen clears the status bar', (tester) async {
    await _phone(tester, textScale: 1.5);
    SharedPreferences.setMockInitialValues({});
    final settings = await tester.runAsync(Settings.load);
    await tester.pumpWidget(
      MaterialApp(
        theme: korbLightTheme(),
        home: SettingsScreen(settings: settings!, onThemeChanged: () {}),
      ),
    );
    await tester.pumpAndSettle();
    _expectBelowStatusBar(tester);
  });

  testWidgets('settings screen scrolls its last entry above the nav bar', (
    tester,
  ) async {
    const navBar = 48.0;
    await _phone(tester);
    tester.view.padding = const FakeViewPadding(
      top: _statusBar * _ratio,
      bottom: navBar * _ratio,
    );
    tester.view.viewPadding = tester.view.padding;
    SharedPreferences.setMockInitialValues({});
    final settings = await tester.runAsync(Settings.load);
    await tester.pumpWidget(
      MaterialApp(
        theme: korbLightTheme(),
        home: SettingsScreen(settings: settings!, onThemeChanged: () {}),
      ),
    );
    await tester.pumpAndSettle();
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -5000));
    await tester.pumpAndSettle();
    final lowest = find
        .descendant(
          of: find.byType(Scrollable).first,
          matching: find.byType(Text),
        )
        .evaluate()
        .map((e) => tester.getBottomLeft(find.byWidget(e.widget)).dy)
        .reduce((a, b) => a > b ? a : b);
    expect(lowest, lessThanOrEqualTo(700 - navBar + 0.5));
  });
}

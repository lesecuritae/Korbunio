import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/services/local_shopping_list.dart';
import 'package:korbklar_app/widgets/local_shopping_list_button.dart';

void main() {
  testWidgets('local shopping list button opens the list from results', (
    tester,
  ) async {
    late Directory root;
    late LocalShoppingListStore shoppingList;
    await tester.runAsync(() async {
      root = await Directory.systemTemp.createTemp('korbklar-list-nav-');
      shoppingList = await LocalShoppingListStore.open(directory: root);
    });
    addTearDown(() => root.delete(recursive: true));

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          appBar: AppBar(
            actions: [LocalShoppingListButton(store: shoppingList)],
          ),
        ),
      ),
    );

    expect(find.byTooltip('Lokale Einkaufsliste'), findsOneWidget);
    await tester.tap(find.byTooltip('Lokale Einkaufsliste'));
    await tester.pumpAndSettle();
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 100)),
    );
    await tester.pumpAndSettle();

    expect(find.text('Lokale Einkaufsliste'), findsOneWidget);
  });
}

import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/services/settings.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('selected retailers persist locally', () async {
    SharedPreferences.setMockInitialValues({});
    final settings = await Settings.load();
    expect(settings.hasSelectedRetailers, isFalse);

    await settings.setSelectedRetailers(['REWE', 'dm']);

    final reloaded = await Settings.load();
    expect(reloaded.selectedRetailers, ['REWE', 'dm']);
    expect(reloaded.hasSelectedRetailers, isTrue);
  });
}

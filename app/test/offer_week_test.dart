import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/services/offer_week.dart';

void main() {
  // 2026-09-02 is a Wednesday.
  final wednesday = DateTime(2026, 9, 2, 14, 30);

  test('the latest change before a Wednesday is Monday midnight', () {
    expect(OfferWeek.lastChange(wednesday), DateTime(2026, 8, 31));
  });

  test('Thursday counts as a change from midnight on', () {
    expect(
      OfferWeek.lastChange(DateTime(2026, 9, 3, 0, 0, 1)),
      DateTime(2026, 9, 3),
    );
    expect(
      OfferWeek.lastChange(DateTime(2026, 9, 6, 23)),
      DateTime(2026, 9, 3),
    );
  });

  test('a search from Tuesday is still fresh on Wednesday', () {
    expect(OfferWeek.isStale(DateTime(2026, 9, 1, 9), now: wednesday), isFalse);
  });

  test('a search from Sunday is stale on Wednesday', () {
    expect(
      OfferWeek.isStale(DateTime(2026, 8, 30, 18), now: wednesday),
      isTrue,
    );
  });

  test('a search from Wednesday is stale on Thursday morning', () {
    expect(OfferWeek.isStale(wednesday, now: DateTime(2026, 9, 3, 7)), isTrue);
  });

  test('the next change after Wednesday is Thursday, after Friday Monday', () {
    expect(OfferWeek.nextChange(wednesday), DateTime(2026, 9, 3));
    expect(OfferWeek.nextChange(DateTime(2026, 9, 4)), DateTime(2026, 9, 7));
  });

  test('the boundary stays at midnight across a DST switch', () {
    // 2026-10-25 is the Sunday clocks go back in Germany; the Monday before
    // it must still come out as 00:00, not 01:00 or 23:00.
    final change = OfferWeek.lastChange(DateTime(2026, 10, 28, 12));
    expect(change, DateTime(2026, 10, 26));
    expect(change.hour, 0);
  });

  test('the label names the weekday of the latest change', () {
    expect(OfferWeek.lastChangeLabel(wednesday), 'Montag');
    expect(OfferWeek.lastChangeLabel(DateTime(2026, 9, 5)), 'Donnerstag');
  });
}

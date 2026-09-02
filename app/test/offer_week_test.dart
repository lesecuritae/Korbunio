import 'package:flutter_test/flutter_test.dart';
import 'package:korbklar_app/services/offer_week.dart';

void main() {
  // 2026-09-02 is a Wednesday.
  final wednesday = DateTime(2026, 9, 2, 14, 30);

  test('the latest change before a Wednesday is Sunday midnight', () {
    // Sunday, not Monday: the server already switches weeks on Sunday.
    expect(OfferWeek.lastChange(wednesday), DateTime(2026, 8, 30));
  });

  test('Thursday counts as a change from midnight on', () {
    expect(
      OfferWeek.lastChange(DateTime(2026, 9, 3, 0, 0, 1)),
      DateTime(2026, 9, 3),
    );
    expect(
      OfferWeek.lastChange(DateTime(2026, 9, 5, 23)),
      DateTime(2026, 9, 3),
    );
  });

  test('a search from Tuesday is still fresh on Wednesday', () {
    expect(OfferWeek.isStale(DateTime(2026, 9, 1, 9), now: wednesday), isFalse);
  });

  test('a search from Saturday is stale on Sunday', () {
    expect(
      OfferWeek.isStale(DateTime(2026, 9, 5, 18), now: DateTime(2026, 9, 6, 8)),
      isTrue,
    );
  });

  test('a search from Sunday is still fresh on Wednesday', () {
    expect(
      OfferWeek.isStale(DateTime(2026, 8, 30, 18), now: wednesday),
      isFalse,
    );
  });

  test('a search from Wednesday is stale on Thursday morning', () {
    expect(OfferWeek.isStale(wednesday, now: DateTime(2026, 9, 3, 7)), isTrue);
  });

  test('the next change after Wednesday is Thursday, after Friday Sunday', () {
    expect(OfferWeek.nextChange(wednesday), DateTime(2026, 9, 3));
    expect(OfferWeek.nextChange(DateTime(2026, 9, 4)), DateTime(2026, 9, 6));
  });

  test('the boundary stays at midnight across a DST switch', () {
    // Clocks go back on Sunday 2026-10-25 at 03:00.
    expect(
      OfferWeek.nextChange(DateTime(2026, 10, 23, 12)),
      DateTime(2026, 10, 25),
    );
    expect(
      OfferWeek.lastChange(DateTime(2026, 10, 26, 12)),
      DateTime(2026, 10, 25),
    );
    expect(OfferWeek.lastChange(DateTime(2026, 10, 26, 12)).hour, 0);
  });

  test('the label names the weekday of the latest change', () {
    expect(OfferWeek.lastChangeLabel(wednesday), 'Sonntag');
    expect(OfferWeek.lastChangeLabel(DateTime(2026, 9, 4)), 'Donnerstag');
  });
}

/// When retailers change their offers.
///
/// German weekly leaflets run Monday to Saturday, and the discounters (ALDI,
/// Lidl, Netto, PENNY, Kaufland) start a second wave on Thursday. Between
/// those two moments a comparison does not go out of date, so the app has no
/// reason to re-query every source on each start. After one of them it does,
/// even though nothing about the stored result says so.
///
/// The week starts on Sunday here, not Monday: the server already selects the
/// coming week on Sundays because most retailers publish it by then, so a
/// Saturday result is out of date on Sunday morning.
///
/// Everything here is local time on purpose: the leaflets follow the calendar
/// of the shop, and the device of someone comparing German offers is set to
/// the same one.
class OfferWeek {
  const OfferWeek._();

  /// Weekdays on which offers change, at midnight.
  static const changeWeekdays = {DateTime.sunday, DateTime.thursday};

  /// Midnight of the most recent change day at or before [now].
  static DateTime lastChange(DateTime now) {
    var day = DateTime(now.year, now.month, now.day);
    while (!changeWeekdays.contains(day.weekday)) {
      // Built from components rather than subtracted as a Duration, so a
      // DST switch inside the week cannot land this an hour off midnight.
      day = DateTime(day.year, day.month, day.day - 1);
    }
    return day;
  }

  /// Midnight of the first change day after [now].
  static DateTime nextChange(DateTime now) {
    var day = DateTime(now.year, now.month, now.day + 1);
    while (!changeWeekdays.contains(day.weekday)) {
      day = DateTime(day.year, day.month, day.day + 1);
    }
    return day;
  }

  /// Whether a comparison made at [searchedAt] predates the latest change.
  static bool isStale(DateTime searchedAt, {DateTime? now}) =>
      searchedAt.isBefore(lastChange(now ?? DateTime.now()));

  /// The German name of the weekday the latest change fell on, for the UI.
  static String lastChangeLabel(DateTime now) =>
      switch (lastChange(now).weekday) {
        DateTime.sunday => 'Sonntag',
        DateTime.thursday => 'Donnerstag',
        _ => 'dieser Woche',
      };
}

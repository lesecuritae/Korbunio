from datetime import datetime, timezone

from supermarkt.config import BERLIN
from supermarkt.offer_week import last_change, next_change, next_change_timestamp

# 2026-09-02 is a Wednesday.
WEDNESDAY = datetime(2026, 9, 2, 14, 30, tzinfo=BERLIN)


def test_the_latest_change_before_a_wednesday_is_sunday_midnight():
    # Sunday, not Monday: offer_reference_date already switches weeks on Sunday.
    assert last_change(WEDNESDAY) == datetime(2026, 8, 30, tzinfo=BERLIN)


def test_thursday_counts_as_a_change_from_midnight_on():
    assert last_change(datetime(2026, 9, 3, 0, 0, 1, tzinfo=BERLIN)) == datetime(2026, 9, 3, tzinfo=BERLIN)
    assert last_change(datetime(2026, 9, 5, 23, tzinfo=BERLIN)) == datetime(2026, 9, 3, tzinfo=BERLIN)


def test_the_next_change_after_wednesday_is_thursday_after_friday_sunday():
    assert next_change(WEDNESDAY) == datetime(2026, 9, 3, tzinfo=BERLIN)
    assert next_change(datetime(2026, 9, 4, 8, tzinfo=BERLIN)) == datetime(2026, 9, 6, tzinfo=BERLIN)


def test_a_saturday_snapshot_does_not_survive_into_sunday():
    assert next_change(datetime(2026, 9, 5, 18, tzinfo=BERLIN)) == datetime(2026, 9, 6, tzinfo=BERLIN)


def test_a_change_day_itself_points_at_the_following_one():
    # On Sunday the snapshot may live until Thursday, on Thursday until Sunday.
    assert next_change(datetime(2026, 9, 6, 9, tzinfo=BERLIN)) == datetime(2026, 9, 10, tzinfo=BERLIN)
    assert next_change(datetime(2026, 9, 3, 9, tzinfo=BERLIN)) == datetime(2026, 9, 6, tzinfo=BERLIN)


def test_the_boundary_is_berlin_midnight_whatever_the_server_clock_says():
    # 2026-09-02 23:30 UTC is already Thursday 01:30 in Berlin.
    late = datetime(2026, 9, 2, 23, 30, tzinfo=timezone.utc)
    assert last_change(late) == datetime(2026, 9, 3, tzinfo=BERLIN)
    assert next_change(late) == datetime(2026, 9, 6, tzinfo=BERLIN)


def test_the_boundary_stays_at_midnight_across_a_dst_switch():
    # Clocks go back on Sunday 2026-10-25 at 03:00; the change at 00:00 that
    # day and the Thursday after it must both come out as 00:00 local time.
    assert next_change(datetime(2026, 10, 23, 12, tzinfo=BERLIN)) == datetime(2026, 10, 25, tzinfo=BERLIN)
    assert next_change(datetime(2026, 10, 25, 12, tzinfo=BERLIN)) == datetime(2026, 10, 29, tzinfo=BERLIN)
    assert last_change(datetime(2026, 10, 26, 12, tzinfo=BERLIN)).hour == 0
    assert last_change(datetime(2026, 10, 26, 12, tzinfo=BERLIN)) == datetime(2026, 10, 25, tzinfo=BERLIN)


def test_the_timestamp_matches_the_datetime():
    assert next_change_timestamp(WEDNESDAY) == datetime(2026, 9, 3, tzinfo=BERLIN).timestamp()

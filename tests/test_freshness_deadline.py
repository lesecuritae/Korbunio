from datetime import datetime

from supermarkt.config import BERLIN
from supermarkt.service import SupermarketEngine

WEDNESDAY = datetime(2026, 9, 2, 14, 30, tzinfo=BERLIN)
THURSDAY = datetime(2026, 9, 3, tzinfo=BERLIN).timestamp()


def test_a_complete_current_week_snapshot_lives_until_the_next_change():
    assert SupermarketEngine.freshness_deadline({"request_errors": []}, "current", now=WEDNESDAY, weekly=True) == THURSDAY


def test_a_snapshot_with_a_failed_source_keeps_the_short_ttl():
    snapshot = {"request_errors": ["REWE offiziell: TimeoutError: read timed out"]}
    assert SupermarketEngine.freshness_deadline(snapshot, "current", now=WEDNESDAY, weekly=True) is None


def test_next_week_previews_keep_the_short_ttl():
    assert SupermarketEngine.freshness_deadline({"request_errors": []}, "next", now=WEDNESDAY, weekly=True) is None


def test_the_weekly_cache_can_be_switched_off():
    assert SupermarketEngine.freshness_deadline({"request_errors": []}, "current", now=WEDNESDAY, weekly=False) is None

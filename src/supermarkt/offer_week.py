"""When retailers change their offers.

German weekly leaflets run Monday to Saturday, and the discounters (ALDI,
Lidl, Netto, PENNY, Kaufland) start a second wave on Thursday. Between those
two moments a snapshot of one postal code does not go out of date, however
often it is opened, so there is no reason to drive every retailer site again
after thirty minutes. After one of them there is.

The week does not start on Monday here but on Sunday: ``offer_reference_date``
already selects the coming week on Sundays because most retailers publish it
by then, so a Saturday snapshot must not survive into Sunday.

All arithmetic is in Europe/Berlin: the leaflets follow the calendar of the
shop, not of the server.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import BERLIN

# datetime.weekday(): Thursday is 3, Sunday is 6.
CHANGE_WEEKDAYS = (3, 6)


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _berlin(now: datetime | None) -> datetime:
    moment = now or datetime.now(BERLIN)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=BERLIN)
    return moment.astimezone(BERLIN)


def last_change(now: datetime | None = None) -> datetime:
    """Midnight of the most recent change day at or before ``now``."""
    day = _midnight(_berlin(now))
    while day.weekday() not in CHANGE_WEEKDAYS:
        # Date arithmetic on the wall clock, then re-anchored to midnight, so
        # a DST switch inside the week cannot land this an hour off.
        day = _midnight((day - timedelta(hours=12)).astimezone(BERLIN))
    return day


def next_change(now: datetime | None = None) -> datetime:
    """Midnight of the first change day after ``now``."""
    day = _midnight((_midnight(_berlin(now)) + timedelta(hours=36)).astimezone(BERLIN))
    while day.weekday() not in CHANGE_WEEKDAYS:
        day = _midnight((day + timedelta(hours=36)).astimezone(BERLIN))
    return day


def next_change_timestamp(now: datetime | None = None) -> float:
    """``next_change`` as a POSIX timestamp, the unit the snapshot store uses."""
    return next_change(now).timestamp()

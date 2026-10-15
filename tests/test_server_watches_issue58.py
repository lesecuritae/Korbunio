"""Delivery receipts and watch filters; every transport is a fake."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from supermarkt import config, history, mcp_server, notify


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.db")


def offers(count=12):
    return [mcp_server.Offer(retailer="REWE", product=f"Cola {i}", pack="1 l", price_without_bonus="2,00 €",
                             valid="15.10.2026–21.10.2026", valid_from="2026-10-15", valid_until="2026-10-21")
            for i in range(count)]


def test_batches_only_acknowledge_delivered_then_retry(monkeypatch, caplog):
    watch = history.add_watch("Cola", None, "01067")
    monkeypatch.setattr(mcp_server, "_offers_from", lambda *_args: offers())
    messages = []
    def send(_title, text):
        if messages:
            raise notify.NotifyError("secret https://example.invalid/secret-topic body")
        messages.append(text)
    monkeypatch.setattr(notify, "send", send)
    mcp_server._check_watches("01067", {})
    with history._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM notified WHERE watch_id = ?", (watch["id"],)).fetchone()[0] == 5
    assert "secret-topic" not in caplog.text
    monkeypatch.setattr(notify, "send", lambda _title, text: messages.append(text))
    mcp_server._check_watches("01067", {})
    assert [len(text.splitlines()) for text in messages] == [5, 5, 2]
    mcp_server._check_watches("01067", {})
    assert len(messages) == 3


def test_filters_cashback_and_preview_becoming_current(monkeypatch):
    history.add_watch("Cola", 100, "01067", ("rewe",), "all")
    rows = offers(1)
    rows[0].bonus_credit = "1,50 €"
    rows[0].price_after_credit = "0,50 €"
    rows.append(mcp_server.Offer(retailer="Lidl", product="Cola", price_without_bonus="0,50 €"))
    monkeypatch.setattr(mcp_server, "_offers_from", lambda *_args: rows)
    messages = []
    monkeypatch.setattr(notify, "send", lambda _title, text: messages.append(text))
    mcp_server._check_watches("01067", {"offer_week": "next"})
    assert not messages  # Cashback is not the amount paid at checkout.
    history.add_watch("Cola", 200, "01067", ("rewe",), "all")
    mcp_server._check_watches("01067", {"offer_week": "next"})
    rows[0].valid = "Aktuelle Woche"  # Display text changes; source validity remains identical.
    mcp_server._check_watches("01067", {"offer_week": "current"})
    assert len(messages) == 1 and "Lidl" not in messages[0]


def test_next_watch_does_not_receive_current(monkeypatch):
    history.add_watch("Cola", None, "01067", offer_week="next")
    monkeypatch.setattr(mcp_server, "_offers_from", lambda *_args: offers(1))
    messages = []
    monkeypatch.setattr(notify, "send", lambda _title, text: messages.append(text))
    mcp_server._check_watches("01067", {})
    assert not messages
    mcp_server._check_watches("01067", {"offer_week": "next"})
    assert len(messages) == 1


def test_concurrent_checks_deliver_once(monkeypatch):
    history.add_watch("Cola", None, "01067")
    monkeypatch.setattr(mcp_server, "_offers_from", lambda *_args: offers(1))
    messages = []
    monkeypatch.setattr(notify, "send", lambda _title, text: messages.append(text))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: mcp_server._check_watches("01067", {}), range(8)))
    assert len(messages) == 1


def test_legacy_schema_migrates_without_losing_receipts():
    with sqlite3.connect(config.HISTORY_DB) as db:
        db.execute("CREATE TABLE watches (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, max_cents INTEGER, plz TEXT NOT NULL, created TEXT NOT NULL)")
        db.execute("INSERT INTO watches VALUES (1, 'Cola', 199, '01067', '2026-10-01')")
        db.execute("CREATE TABLE notified(watch_id INTEGER NOT NULL, offer_key TEXT NOT NULL, PRIMARY KEY(watch_id,offer_key))")
        db.execute("INSERT INTO notified VALUES (1, 'old-receipt')")
    assert history.list_watches()[0] == {"id": 1, "query": "Cola", "max_cents": 199, "postal_code": "01067", "retailer_ids": [], "offer_week": "current"}
    assert history.unnotified(1, ["old-receipt"]) == []


def test_http_failure_keeps_all_receipts_pending(monkeypatch):
    import urllib.error
    monkeypatch.setenv("SUPERMARKT_NOTIFY_URL", "https://example.invalid/secret-topic")
    history.add_watch("Cola", None, "01067")
    monkeypatch.setattr(mcp_server, "_offers_from", lambda *_args: offers(2))
    def failure(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.invalid/secret-topic", 503, "secret body", {}, None)
    monkeypatch.setattr(notify._OPENER, "open", failure)
    mcp_server._check_watches("01067", {})
    with history._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM notified").fetchone()[0] == 0
    with pytest.raises(notify.NotifyError, match="HTTP 503") as error:
        notify.send("title", "text")
    assert "secret-topic" not in str(error.value)
    assert error.value.__suppress_context__


def test_snapshot_next_week_uses_engine_provider_parameter(monkeypatch):
    calls = []
    class Engine:
        def snapshot(self, *args, **kwargs):
            calls.append(kwargs)
            return {"offer_week": kwargs["offer_week"]}, False
    monkeypatch.setattr(mcp_server.runtime, "get_engine", lambda: Engine())
    assert mcp_server._load_snapshot("01067", (), offer_week="next")["offer_week"] == "next"
    assert calls == [{"retailers": (), "offer_week": "next"}]


def test_bundle_threshold_applies_to_total_and_message_explains_minimum(monkeypatch):
    row = mcp_server.Offer(retailer="Kaufland", product="Em-eukal (synthetic arithmetic case)",
                           price_without_bonus="3,00 €", multi_buy_quantity=3, multi_buy_total_price=3.0,
                           multi_buy_condition="3 Stück für 3 €")
    monkeypatch.setattr(mcp_server, "_offers_from", lambda *_args: [row])
    messages = []
    monkeypatch.setattr(notify, "send", lambda _title, text: messages.append(text))
    history.add_watch("Em-eukal", 100, "01067")
    mcp_server._check_watches("01067", {})
    assert not messages
    history.add_watch("Em-eukal", 300, "01067")
    mcp_server._check_watches("01067", {})
    assert len(messages) == 1
    assert "3 Stück für insgesamt 3,00 €" in messages[0]
    assert "1,00 € je Stück nur im Mehrkauf" in messages[0]


def test_unselected_membership_does_not_lower_server_watch_threshold(monkeypatch):
    history.add_watch("Cola", 100, "01067")
    row = mcp_server.Offer(retailer="REWE", product="Cola",price_without_bonus="2,00 €",
        price_with_bonus="0,79 €",bonus_program="Example Club")
    monkeypatch.setattr(mcp_server,"_offers_from",lambda *_args:[row])
    messages=[]
    monkeypatch.setattr(notify,"send",lambda _title,text:messages.append(text))
    mcp_server._check_watches("01067",{})
    assert messages == []

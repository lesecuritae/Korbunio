import asyncio
import threading
import types

import pytest
from mcp.client import Client
from starlette.testclient import TestClient

from supermarkt import access, mcp_server, runtime
from supermarkt.asgi import app

OFFERS = [
    {"offer_id": "a", "retailer": "Kaufland", "product": "Hochland Schmelzkäse", "pack": "200 g", "unit_price": "7,95 €/kg",
     "regular_price_text": "1,99 €", "effective_price": 1.99, "effective_price_text": "1,99 €", "validity": "Kaufland, gültig 2026-09-17 bis 2026-09-23", "image_url": "https://img.example/a.jpg"},
    {"offer_id": "b", "retailer": "REWE", "product": "Schmelzkäse", "pack": "", "unit_price": "",
     "regular_price_text": "1,49 €", "effective_price": 1.49, "effective_price_text": "1,49 €", "validity": "gültig bis 20.09.", "image_url": None},
]


class FakeEngine:
    def page(self, snapshot, loyalty_programs=(), **_kwargs):
        offers = [dict(o) for o in OFFERS]
        if loyalty_programs:
            offers[0].update(effective_price=1.59, effective_price_text="1,59 €", loyalty_benefit="Kaufland Card")
        return {"offers": offers, "available_loyalty_programs": [{"id": "kaufland_xtra", "label": "Kaufland Card", "retailers": ["Kaufland"], "priced_offer_count": 1}]}


class FakeImages:
    def get(self, **_kwargs):
        return types.SimpleNamespace(data=b"\x89PNGfake", content_type="image/png", origin="test")


@pytest.fixture(autouse=True)
def fake_runtime(monkeypatch, tmp_path):
    from supermarkt import config
    monkeypatch.setattr(config, "HISTORY_DB", tmp_path / "history.sqlite3")
    monkeypatch.setattr(config, "NOTIFY_FILE", tmp_path / "notify.json")
    monkeypatch.setattr(config, "KITCHENOWL_FILE", tmp_path / "kitchenowl-default.json")
    monkeypatch.delenv("SUPERMARKT_NOTIFY_URL", raising=False)
    monkeypatch.setattr(runtime, "get_engine", lambda: FakeEngine())
    monkeypatch.setattr(runtime, "get_image_service", lambda: FakeImages())
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda plz, retailers, refresh=False: {"plz": plz})
    monkeypatch.setenv("SUPERMARKT_MCP_WARMUP", "0")
    mcp_server._inflight.clear()
    mcp_server._last_used.clear()
    mcp_server._new_postal_codes.clear()


def call(name, arguments):
    async def run():
        async with Client(mcp_server.mcp) as client:
            return await client.call_tool(name, arguments)
    return asyncio.run(run())


def test_find_offers_lists_cheapest_first_with_bonus_price_and_image():
    result = call("find_offers", {"product": "Schmelzkäse", "postal_code": "01067"})
    offers = result.structured_content["offers"]
    assert [o["retailer"] for o in offers] == ["REWE", "Kaufland"]
    assert offers[1]["price_without_bonus"] == "1,99 €" and offers[1]["price_with_bonus"] == "1,59 €"
    assert offers[1]["bonus_program"] == "Kaufland Card" and offers[0]["price_with_bonus"] is None
    text = result.content[0].text
    assert "1,59 € mit Kaufland Card" in text and "gültig gültig" not in text
    assert "gültig 17.09.2026 bis 23.09.2026" in text and "Kaufland, gültig" not in text
    assert [block.type for block in result.content].count("image") == 1


def test_only_one_image_by_default_and_up_to_three_on_request():
    assert [b.type for b in call("find_offers", {"product": "x", "postal_code": "01067"}).content].count("image") == 1
    result = call("find_offers", {"product": "x", "postal_code": "01067", "max_images": 0})
    assert all(block.type == "text" for block in result.content)


def test_search_widens_to_single_words_when_nothing_matches(monkeypatch):
    class Picky(FakeEngine):
        def page(self, snapshot, loyalty_programs=(), keywords=(), **kwargs):
            if not keywords:
                return {"offers": [], "available_loyalty_programs": []}
            return super().page(snapshot, loyalty_programs=loyalty_programs, **kwargs)
    monkeypatch.setattr(runtime, "get_engine", lambda: Picky())
    result = call("find_offers", {"product": "Schmelzkäses", "postal_code": "01067", "with_images": False})
    assert result.structured_content["found"] == 2 and "ähnliche Treffer" in result.content[0].text


def test_too_many_new_postal_codes_are_refused(monkeypatch):
    monkeypatch.setattr(mcp_server, "NEW_POSTAL_CODE_LIMIT", 2)
    assert not call("find_offers", {"product": "x", "postal_code": "01067", "with_images": False}).is_error
    assert not call("find_offers", {"product": "x", "postal_code": "01069", "with_images": False}).is_error
    assert call("find_offers", {"product": "x", "postal_code": "01097", "with_images": False}).is_error
    assert not call("find_offers", {"product": "x", "postal_code": "01067", "with_images": False}).is_error


def test_find_offers_without_images_and_with_limit():
    result = call("find_offers", {"product": "x", "postal_code": "01067", "with_images": False, "limit": 1})
    assert len(result.structured_content["offers"]) == 1
    assert all(block.type == "text" for block in result.content)


def test_find_offers_rejects_bad_input():
    assert call("find_offers", {"product": "x", "postal_code": "abc"}).is_error
    assert call("find_offers", {"product": " ", "postal_code": "01067"}).is_error
    assert call("find_offers", {"product": "x", "postal_code": "01067", "retailers": ["Nirgendwo"]}).is_error


def test_slow_load_answers_politely_and_keeps_loading(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(mcp_server, "_load_snapshot", lambda plz, retailers, refresh=False: release.wait(10) and {"plz": plz})
    monkeypatch.setattr(mcp_server, "LOAD_DEADLINE_SECONDS", 0.5)
    monkeypatch.setattr("asyncio.wait", _short_wait(asyncio.wait))

    async def run():
        async with Client(mcp_server.mcp) as client:
            first = await client.call_tool("find_offers", {"product": "x", "postal_code": "01067"})
            release.set()
            await asyncio.sleep(0.3)
            second = await client.call_tool("find_offers", {"product": "x", "postal_code": "01067"})
            return first, second
    first, second = asyncio.run(run())
    assert first.structured_content["status"] == "loading"
    assert "noch einmal" in first.content[0].text
    assert second.structured_content["found"] == 2


def _short_wait(real):
    async def wait(tasks, timeout=None, **kwargs):
        return await real(tasks, timeout=min(timeout or 0.2, 0.2), **kwargs)
    return wait


def test_list_retailers_and_programs():
    retailers = call("list_retailers", {}).structured_content["result"]
    assert any(r["name"] == "Kaufland" and r["bonus_programs"] for r in retailers)
    assert call("list_bonus_programs", {"postal_code": "01067"}).structured_content["programs"][0]["id"] == "kaufland_xtra"


def test_http_endpoint_honours_optional_api_key(monkeypatch):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(app) as client:
        assert client.post("/mcp", json=payload, headers=headers).status_code == 200
        monkeypatch.setenv("SUPERMARKT_API_KEY", "secret-for-test")
        assert client.post("/mcp", json=payload, headers=headers).status_code == 401
        assert client.post("/mcp", json=payload, headers={**headers, "Authorization": "Bearer secret-for-test"}).status_code == 200


class _FakeKitchenOwl:
    """Kleiner KitchenOwl-Ersatz auf localhost, der Anfragen mitschreibt."""

    def __init__(self):
        import json
        from http.server import BaseHTTPRequestHandler, HTTPServer
        outer = self
        self.items: list[dict] = [{"id": 1, "name": "Milch"}]
        self.requests: list[tuple] = []

        class Handler(BaseHTTPRequestHandler):
            def _reply(self, payload):
                data = json.dumps(payload).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            def do_GET(self):
                outer.requests.append(("GET", self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != "Bearer test-token":
                    self.send_response(401); self.send_header("Content-Length", "0"); self.end_headers(); return
                if self.path == "/api/household":
                    return self._reply([{"id": 1, "name": "Haus"}])
                if self.path == "/api/household/1/shoppinglist":
                    return self._reply([{"id": 7, "name": "Einkauf"}, {"id": 8, "name": "Baumarkt"}])
                self._reply(outer.items)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(("POST", self.path, self.headers.get("Authorization"), body))
                outer.items.append({"id": len(outer.items) + 1, **body})
                self._reply({"id": len(outer.items)})

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def kitchenowl(monkeypatch):
    fake = _FakeKitchenOwl()
    monkeypatch.setenv("SUPERMARKT_KITCHENOWL_URL", fake.url)
    monkeypatch.setenv("SUPERMARKT_KITCHENOWL_TOKEN", "test-token")
    monkeypatch.setenv("SUPERMARKT_KITCHENOWL_LIST_ID", "7")
    assert mcp_server.register_shopping_tool()
    yield fake
    fake.close()
    monkeypatch.delenv("SUPERMARKT_KITCHENOWL_URL")
    mcp_server.register_shopping_tool()


def test_shopping_tool_is_hidden_without_kitchenowl(monkeypatch):
    monkeypatch.delenv("SUPERMARKT_KITCHENOWL_URL", raising=False)
    assert not mcp_server.register_shopping_tool()

    async def names():
        async with Client(mcp_server.mcp) as client:
            return [tool.name for tool in (await client.list_tools()).tools]
    assert "add_to_shopping_list" not in asyncio.run(names())


def test_shopping_tool_adds_with_note_and_skips_duplicates(kitchenowl):
    result = call("add_to_shopping_list", {"item": "Hochland Schmelzkäse", "retailer": "Kaufland", "price": "1,59 €"})
    assert result.structured_content == {"item": "Hochland Schmelzkäse", "added": True, "note": "bei Kaufland · 1,59 €"}
    post = [r for r in kitchenowl.requests if r[0] == "POST"][0]
    assert post[1] == "/api/shoppinglist/7/add-item-by-name" and post[2] == "Bearer test-token"
    assert post[3] == {"name": "Hochland Schmelzkäse", "description": "bei Kaufland · 1,59 €"}
    again = call("add_to_shopping_list", {"item": "hochland schmelzkäse"})
    assert again.structured_content["added"] is False and "schon" in again.content[0].text
    assert len([r for r in kitchenowl.requests if r[0] == "POST"]) == 1


def test_shopping_tool_refuses_plain_http_to_other_hosts(monkeypatch):
    monkeypatch.setenv("SUPERMARKT_KITCHENOWL_URL", "http://kitchenowl.example.test")
    monkeypatch.setenv("SUPERMARKT_KITCHENOWL_TOKEN", "t")
    monkeypatch.setenv("SUPERMARKT_KITCHENOWL_LIST_ID", "1")
    assert not mcp_server.register_shopping_tool()
    monkeypatch.delenv("SUPERMARKT_KITCHENOWL_URL")


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    from supermarkt import config
    monkeypatch.setattr(config, "KITCHENOWL_FILE", tmp_path / "kitchenowl.json")
    for name in ("URL", "TOKEN", "LIST_ID"):
        monkeypatch.delenv(f"SUPERMARKT_KITCHENOWL_{name}", raising=False)
    monkeypatch.delenv("SUPERMARKT_API_KEY", raising=False)
    yield tmp_path / "kitchenowl.json"
    mcp_server.register_shopping_tool()


def test_settings_page_saves_token_privately_and_enables_the_tool(settings_file):
    fake = _FakeKitchenOwl()
    try:
        client = TestClient(app)
        assert client.get("/settings").status_code == 200
        assert client.get("/api/v1/kitchenowl").json()["configured"] is False
        lists = client.post("/api/v1/kitchenowl/lists", json={"url": fake.url, "token": "test-token"}).json()["lists"]
        assert lists == [{"id": "7", "label": "Haus · Einkauf"}, {"id": "8", "label": "Haus · Baumarkt"}]
        saved = client.put("/api/v1/kitchenowl", json={"url": fake.url, "token": "test-token", "list_id": "8"}).json()
        assert saved["configured"] and saved["list_label"] == "Haus · Baumarkt"
        assert "test-token" not in client.get("/api/v1/kitchenowl").text
        assert (settings_file.stat().st_mode & 0o777) == 0o600
        names = [tool.name for tool in asyncio.run(_tools())]
        assert "add_to_shopping_list" in names
        assert call("add_to_shopping_list", {"item": "Milch", "retailer": "Lidl"}).structured_content["added"] is False
        assert client.delete("/api/v1/kitchenowl").json()["configured"] is False
        assert "add_to_shopping_list" not in [tool.name for tool in asyncio.run(_tools())]
    finally:
        fake.close()


def test_browser_and_compatibility_client_can_file_items_in_kitchenowl(settings_file):
    fake = _FakeKitchenOwl()
    try:
        client = TestClient(app)
        saved = client.put(
            "/api/v1/kitchenowl",
            json={"url": fake.url, "token": "test-token", "list_id": "7"},
        )
        assert saved.status_code == 200

        result_token = access.result_token("compatibility-result")
        base = "/results/compatibility-result/shopping-list"
        targets = client.get(f"{base}/targets", params={"token": result_token}).json()
        assert targets == {
            "configured": True,
            "targets": [{"entity_id": "7", "label": "Haus · Einkauf"}],
            "default_entity": "7",
        }

        filed = client.post(
            f"{base}/items",
            params={"token": result_token},
            json={
                "entity_id": "7",
                "items": [{"product": "Butter", "retailer": "EDEKA", "price_text": "1,79 €", "pack": "250 g"}],
            },
        )
        assert filed.status_code == 200
        assert filed.json() == {"added": ["Butter"]}
        post = [request for request in fake.requests if request[0] == "POST"][-1]
        assert post[1] == "/api/shoppinglist/7/add-item-by-name"
        assert post[3] == {"name": "Butter", "description": "bei EDEKA · 1,79 € · 250 g"}

        entries = client.get(
            f"{base}/entries",
            params={"token": result_token, "entity_id": "7"},
        )
        assert entries.json()["items"] == ["Milch", "Butter"]

        browser = client.post(
            "/api/v1/kitchenowl/items",
            json={"entity_id": "7", "items": [{"name": "Brot", "description": "Menge: 1"}]},
        )
        assert browser.status_code == 200
        assert browser.json() == {"added": ["Brot"]}
    finally:
        fake.close()


async def _tools():
    async with Client(mcp_server.mcp) as client:
        return (await client.list_tools()).tools


def test_settings_reject_wrong_token_unknown_list_and_plain_http(settings_file):
    fake = _FakeKitchenOwl()
    try:
        client = TestClient(app)
        assert client.post("/api/v1/kitchenowl/lists", json={"url": fake.url, "token": "falsch"}).status_code == 502
        assert client.put("/api/v1/kitchenowl", json={"url": fake.url, "token": "test-token", "list_id": "99"}).status_code == 422
        assert client.post("/api/v1/kitchenowl/lists", json={"url": "http://kitchenowl.example.test", "token": "x"}).status_code == 502
        assert client.post("/api/v1/kitchenowl/lists", json={"url": "https://user:pw@kitchenowl.example.test", "token": "x"}).status_code == 502
        assert not settings_file.exists()
    finally:
        fake.close()


def test_settings_need_the_admin_key_when_one_is_configured(settings_file, monkeypatch):
    monkeypatch.setenv("SUPERMARKT_API_KEY", "admin-for-test")
    client = TestClient(app)
    assert client.get("/api/v1/kitchenowl").status_code == 401
    assert client.get("/api/v1/kitchenowl", headers={"Authorization": "Bearer admin-for-test"}).status_code == 200
    assert client.post("/api/v1/kitchenowl/items", json={"items": [{"name": "Milch"}]}).status_code == 401


# ---- Preisverlauf, Beobachten, Benachrichtigen, Listenabgleich, Adapter ---------------------


class _Receiver:
    """Nimmt Benachrichtigungen per POST an."""

    def __init__(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        outer = self
        self.messages: list[tuple[str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                outer.messages.append((self.headers.get("Title", ""), body))
                self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/topic"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def receiver(monkeypatch):
    fake = _Receiver()
    monkeypatch.setenv("SUPERMARKT_NOTIFY_URL", fake.url)
    assert mcp_server.register_watch_tools()
    yield fake
    fake.close()
    monkeypatch.delenv("SUPERMARKT_NOTIFY_URL", raising=False)
    mcp_server.register_watch_tools()


def _snapshot(price_a=1.99):
    return {"offers": [
        {"offer_id": "a", "retailer": "Kaufland", "brand": "Hochland", "name": "Hochland Schmelzkäse", "price": price_a, "match_key": "k1"},
        {"offer_id": "b", "retailer": "REWE", "brand": "", "name": "Schmelzkäse", "price": 1.49, "match_key": "k2"},
        {"offer_id": "c", "retailer": "REWE", "brand": "", "name": "Ohne Preis", "price": None, "match_key": "k3"},
    ]}


def test_price_history_keeps_the_lowest_price_per_day_and_answers_through_the_tool():
    from supermarkt import history
    history.record("01067", _snapshot(1.99))
    history.record("01067", _snapshot(1.59))  # am selben Tag: der niedrigste bleibt
    history.record("04109", _snapshot(0.99))  # andere Postleitzahl zählt nicht
    rows = history.price_history("schmelzkäse hochland", "01067")
    assert len(rows) == 1 and rows[0]["lowest_cents"] == 159 and rows[0]["days_seen"] == 1
    result = call("price_history", {"product": "Schmelzkäse", "postal_code": "01067"})
    text = result.content[0].text
    assert "Kaufland: Hochland Schmelzkäse" in text and "Hochland Hochland" not in text and "1,59 €" in text
    assert "gesehen seit " + ".".join(reversed(rows[0]["first_seen"].split("-"))) in text
    assert "noch keine Preise" in call("price_history", {"product": "Kaviar", "postal_code": "01067"}).content[0].text


def test_watch_tools_need_a_notification_address(monkeypatch):
    monkeypatch.delenv("SUPERMARKT_NOTIFY_URL", raising=False)
    assert not mcp_server.register_watch_tools()
    assert "watch_product" not in [tool.name for tool in asyncio.run(_tools())]


def test_watch_notifies_once_per_new_matching_offer(receiver):
    from supermarkt import history
    added = call("watch_product", {"product": "Schmelzkäse", "max_price": "1,59", "postal_code": "01067"})
    assert added.structured_content["max_cents"] == 159
    assert "Nr." in added.content[0].text
    assert call("list_watches", {}).structured_content["watches"][0]["query"] == "Schmelzkäse"
    mcp_server._check_watches("01067", {"plz": "01067"})
    assert len(receiver.messages) == 1
    title, body = receiver.messages[0]
    import base64
    assert base64.b64decode(title[len("=?UTF-8?B?"):-2]).decode() == "Korbuino: Schmelzkäse im Angebot" and "REWE: Schmelzkäse 1,49 €" in body
    mcp_server._check_watches("01067", {"plz": "01067"})  # nichts Neues
    assert len(receiver.messages) == 1
    assert call("remove_watch", {"watch_id": added.structured_content["id"]}).structured_content["removed"] is True
    assert history.list_watches() == []


def test_watch_rejects_bad_price_and_too_many(receiver):
    assert call("watch_product", {"product": "x", "max_price": "abc", "postal_code": "01067"}).is_error
    for number in range(20):
        assert not call("watch_product", {"product": f"Artikel {number}", "postal_code": "01067"}).is_error
    assert call("watch_product", {"product": "Einer zu viel", "postal_code": "01067"}).is_error


def test_notify_settings_test_the_address_before_saving(monkeypatch, receiver):
    client = TestClient(app)
    monkeypatch.delenv("SUPERMARKT_NOTIFY_URL", raising=False)
    assert client.put("/api/v1/notify", json={"url": "http://kitchen.example.test/x"}).status_code == 502
    assert client.put("/api/v1/notify", json={"url": receiver.url}).json() == {"configured": True}
    assert receiver.messages and "Test" in receiver.messages[-1][1]
    assert receiver.url not in client.get("/api/v1/notify").text
    assert client.delete("/api/v1/notify").json() == {"configured": False}


def test_check_shopping_list_compares_the_kitchenowl_list_with_offers(kitchenowl):
    kitchenowl.items[:] = [{"id": 1, "name": "Schmelzkäse"}, {"id": 2, "name": "Kaviar"}]

    class Split(FakeEngine):
        def page(self, snapshot, loyalty_programs=(), filter_text="", **kwargs):
            if filter_text != "Schmelzkäse":
                return {"offers": [], "available_loyalty_programs": []}
            return super().page(snapshot, loyalty_programs=loyalty_programs, **kwargs)
    import supermarkt.runtime as rt
    rt.get_engine = lambda: Split()
    result = call("check_shopping_list", {"postal_code": "01067"})
    assert result.structured_content["items"][0]["offers"] and not result.structured_content["items"][1]["offers"]
    assert "1 von 2" in result.content[0].text and "Kaviar: nicht im Angebot" in result.content[0].text


def test_shopping_additions_are_limited_per_hour(kitchenowl, monkeypatch):
    monkeypatch.setattr(mcp_server, "SHOPPING_ADDS_PER_HOUR", 2)
    mcp_server._shopping_adds.clear()
    assert not call("add_to_shopping_list", {"item": "Eins"}).is_error
    assert not call("add_to_shopping_list", {"item": "Zwei"}).is_error
    assert call("add_to_shopping_list", {"item": "Drei"}).is_error


def test_stdio_bridge_forwards_json_and_event_streams():
    import json
    from supermarkt import mcp_bridge
    seen = []

    def post(url, body):
        seen.append((url, body))
        if b"stream" in body:
            return "text/event-stream", b"event: message\ndata: {\"id\": 1}\n\n"
        return "application/json", b'{"id": 2}'
    assert mcp_bridge.forward("https://x/mcp", '{"stream": 1}', post) == ['{"id": 1}']
    assert mcp_bridge.forward("https://x/mcp", '{"id": 2}', post) == ['{"id": 2}']
    assert mcp_bridge.messages("application/json", b"") == []
    import urllib.error

    def refuse(_url, _body):
        raise urllib.error.HTTPError("https://x/mcp", 401, "no", {}, None)
    error = json.loads(mcp_bridge.forward("https://x/mcp", '{"jsonrpc": "2.0", "id": 5, "method": "tools/list"}', refuse)[0])
    assert error["id"] == 5 and "401" in error["error"]["message"]
    assert mcp_bridge.forward("https://x/mcp", '{"method": "notifications/initialized"}', refuse) == []


def test_everyday_synonyms_widen_the_search(monkeypatch):
    seen = []

    class Spy(FakeEngine):
        def page(self, snapshot, loyalty_programs=(), keywords=(), **kwargs):
            seen.append(tuple(keywords))
            return super().page(snapshot, loyalty_programs=loyalty_programs, **kwargs)
    monkeypatch.setattr(runtime, "get_engine", lambda: Spy())
    call("find_offers", {"product": "Osterhase", "postal_code": "01067", "with_images": False})
    assert any("schokohase" in keywords for keywords in seen)


def test_hint_when_a_retailer_has_no_computable_bonus(monkeypatch):
    class Edeka(FakeEngine):
        def page(self, snapshot, loyalty_programs=(), **kwargs):
            result = super().page(snapshot, loyalty_programs=loyalty_programs, **kwargs)
            result["offers"][1]["retailer"] = "EDEKA"
            return result
    monkeypatch.setattr(runtime, "get_engine", lambda: Edeka())
    text = call("find_offers", {"product": "x", "postal_code": "01067", "with_images": False}).content[0].text
    assert "Hinweis: Bei EDEKA gibt es keinen berechenbaren Bonuspreis" in text
    assert "Kaufland" not in text.split("Hinweis:")[1]


def test_source_status_lists_last_day_per_retailer():
    from supermarkt import history
    history.record("01067", _snapshot())
    rows = TestClient(app).get("/health/sources").json()["retailers"]
    assert {row["retailer"] for row in rows} == {"Kaufland", "REWE"}
    assert all(row["days_ago"] == 0 and row["offers"] >= 1 for row in rows)

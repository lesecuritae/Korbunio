"""supermarkt.grocy against an in-memory fake Grocy speaking the verified 4.7 API shapes (real HTTP on loopback)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from supermarkt import grocy

KEY = "k" * 48


class FakeGrocy:
    def __init__(self):
        self.products = {}
        self.rows = {}
        self.next_id = 1
        self.requests = []
        self.hang_next_post_after_create = False
        self.stall_seconds = 0
        self.lists = {1: "Shopping list", 2: "Other"}

    def new_id(self):
        value = self.next_id
        self.next_id += 1
        return value


def make_server(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, payload=None):
            body = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def handle_any(self, method):
            state.requests.append((method, self.path, self.headers.get("GROCY-API-KEY")))
            if self.headers.get("GROCY-API-KEY") != KEY:
                return self.send(401, {"error_message": "Unauthorized"})
            if "key=" in self.path or KEY in self.path:
                return self.send(400, {"error_message": "key in URL"})
            parts = urlsplit(self.path)
            segments = [s for s in parts.path.split("/") if s]
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else {}
            if parts.path == "/api/system/info":
                return self.send(200, {"grocy_version": {"Version": "4.7.1"}})
            if parts.path == "/api/objects/shopping_lists":
                return self.send(200, [{"id": str(i), "name": n} for i, n in state.lists.items()])
            if parts.path == "/api/objects/locations":
                return self.send(200, [{"id": "2", "name": "Fridge"}])
            if parts.path == "/api/objects/quantity_units":
                return self.send(200, [{"id": "2", "name": "Piece"}, {"id": "3", "name": "Pack"}])
            if segments[:3] == ["api", "objects", "products"]:
                if len(segments) == 3 and method == "GET":
                    return self.send(200, [{"id": str(i), **p} for i, p in state.products.items()])
                if len(segments) == 3 and method == "POST":
                    if any(p["name"] == body["name"] for p in state.products.values()):
                        return self.send(400, {"error_message": "UNIQUE constraint failed: products.name"})
                    pid = state.new_id()
                    state.products[pid] = {"name": body["name"]}
                    return self.send(200, {"created_object_id": str(pid)})
                pid = int(segments[3]) if segments[3].isdigit() else -1
                if pid not in state.products:
                    return self.send(404, {"error_message": "Object not found"})
                if method == "GET":
                    return self.send(200, {"id": str(pid), **state.products[pid]})
                if method == "DELETE":  # Grocy cascades
                    del state.products[pid]
                    state.rows = {k: v for k, v in state.rows.items() if v.get("product_id") != str(pid)}
                    return self.send(204)
            if segments[:3] == ["api", "objects", "shopping_list"]:
                if len(segments) == 3 and method == "GET":
                    wanted = parse_qs(parts.query).get("query[]", [""])[0]
                    rows = [r for r in state.rows.values() if not wanted.startswith("shopping_list_id=") or str(r["shopping_list_id"]) == wanted.split("=")[1]]
                    return self.send(200, rows)
                if len(segments) == 3 and method == "POST":
                    rid = state.new_id()
                    state.rows[rid] = {"id": str(rid), "product_id": str(body.get("product_id")), "note": body.get("note"), "amount": str(body["amount"]),
                                       "shopping_list_id": str(body["shopping_list_id"]), "done": "0"}
                    if state.hang_next_post_after_create:  # request applied, answer lost
                        state.hang_next_post_after_create = False
                        time.sleep(state.stall_seconds)
                        return None
                    return self.send(200, {"created_object_id": str(rid)})
                rid = int(segments[3]) if segments[3].isdigit() else -1
                if method == "GET":
                    return self.send(200, state.rows[rid]) if rid in state.rows else self.send(404, {"error_message": "Object not found"})
                if method == "DELETE":
                    if rid not in state.rows:
                        return self.send(400, {"error_message": "Object not found"})
                    del state.rows[rid]
                    return self.send(204)
            return self.send(400, {"error_message": "Entity does not exist or is not exposed"})

        def do_GET(self):
            self.handle_any("GET")

        def do_POST(self):
            self.handle_any("POST")

        def do_DELETE(self):
            self.handle_any("DELETE")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture()
def fake():
    state = FakeGrocy()
    server = make_server(state)
    yield state, grocy.Settings(f"http://127.0.0.1:{server.server_address[1]}", KEY, 1, 3)
    server.shutdown()


def test_verify_and_missing_or_wrong_key(fake):
    state, settings = fake
    assert grocy.verify(settings) == {"version": "4.7.1", "list_label": "Shopping list"}
    with pytest.raises(grocy.GrocyError, match="abgelehnt"):
        grocy.verify(grocy.Settings(settings.url, "", 1, 3))
    with pytest.raises(grocy.GrocyError, match="abgelehnt"):
        grocy.verify(grocy.Settings(settings.url, "x" * 48, 1, 3))
    with pytest.raises(grocy.GrocyError, match="gibt es nicht"):
        grocy.verify(grocy.Settings(settings.url, KEY, 99, 3))
    assert all(KEY not in path for _, path, _ in state.requests)  # key only in the header, never in the URL


def test_add_creates_unknown_product_and_row_and_retry_is_idempotent(fake):
    state, settings = fake
    first = grocy.add_items(settings, [("Monster Energy 0,5 l", "bei REWE · 0,99 €", 2), ("Milch", "", 1)])
    assert [r["status"] for r in first] == ["added", "added"] and len(state.rows) == 2 and len(state.products) == 2
    again = grocy.add_items(settings, [("monster energy 0,5 l", "bei REWE · 0,99 €", 2), ("Milch", "", 1)])
    assert [r["status"] for r in again] == ["exists", "exists"] and len(state.rows) == 2 and len(state.products) == 2
    assert [r["row_id"] for r in again] == [r["row_id"] for r in first]
    assert {row["note"] for row in state.rows.values()} == {"bei REWE · 0,99 €", None}


def test_same_item_twice_in_one_batch_creates_one_row(fake):
    state, settings = fake
    result = grocy.add_items(settings, [("Brot", "", 1), ("Brot", "", 1)])
    assert [r["status"] for r in result] == ["added", "exists"] and len(state.rows) == 1


def test_existing_product_is_reused_not_recreated(fake):
    state, settings = fake
    state.products[state.new_id()] = {"name": "Butter"}
    result = grocy.add_items(settings, [("Butter", "", 1)])
    assert result[0]["status"] == "added" and len(state.products) == 1


def test_lost_answer_after_create_is_recovered_not_duplicated(fake):
    state, settings = fake
    grocy.add_items(settings, [("Haferflocken", "", 1)])
    state.rows.clear()
    state.hang_next_post_after_create = True
    state.stall_seconds = 4  # longer than the 3 s client timeout
    result = grocy.add_items(settings, [("Haferflocken", "", 1)])
    assert result[0]["status"] == "added" and len(state.rows) == 1  # found by re-reading, no second POST


def test_unknown_outcome_without_trace_is_reported(fake):
    state, settings = fake
    with pytest.raises(grocy.GrocyUnknownOutcome):
        grocy.add_items(grocy.Settings("http://127.0.0.1:9", KEY, 1, 3), [("X", "", 1)])


def test_remove_is_identity_bound_confirmed_and_keeps_product(fake):
    state, settings = fake
    added = grocy.add_items(settings, [("Kaffee", "", 1), ("Tee", "", 1)])
    kaffee, tee = added[0]["row_id"], added[1]["row_id"]
    with pytest.raises(grocy.GrocyError, match="passt nicht"):
        grocy.remove_item(settings, kaffee, "Tee")
    assert len(state.rows) == 2
    assert grocy.remove_item(settings, kaffee, "kaffee") is True
    assert int(kaffee) not in state.rows and int(tee) in state.rows
    assert any(p["name"] == "Kaffee" for p in state.products.values())  # master data kept
    assert grocy.remove_item(settings, kaffee, "Kaffee") is False  # already gone: nothing deleted, no error


@pytest.mark.parametrize("bad", ["abc", "", "1;2", "../x", "-1", "1.5"])
def test_invalid_ids_are_refused_before_any_request(fake, bad):
    state, settings = fake
    before = len(state.requests)
    with pytest.raises(grocy.GrocyError, match="Ungültige"):
        grocy.remove_item(settings, bad, "x")
    assert len(state.requests) == before


def test_row_of_another_list_is_never_deleted(fake):
    state, settings = fake
    rid = state.new_id()
    state.rows[rid] = {"id": str(rid), "product_id": "", "note": "fremd", "amount": "1", "shopping_list_id": "2", "done": "0"}
    with pytest.raises(grocy.GrocyError, match="gehört nicht"):
        grocy.remove_item(settings, str(rid), "fremd")
    assert rid in state.rows


def test_list_items_reads_only_open_rows_of_the_configured_list(fake):
    state, settings = fake
    grocy.add_items(settings, [("Eier", "10er", 1)])
    other = state.new_id()
    state.rows[other] = {"id": str(other), "product_id": "", "note": "Andere Liste", "amount": "1", "shopping_list_id": "2", "done": "0"}
    items = grocy.list_items(settings)
    assert [(i["name"], i["note"]) for i in items] == [("Eier", "10er")]


def test_url_rules_and_secret_file_permissions(tmp_path, monkeypatch):
    assert grocy.normalize_url("https://grocy.example.net/") == "https://grocy.example.net"
    assert grocy.normalize_url("http://127.0.0.1:9283") == "http://127.0.0.1:9283"
    for bad in ("http://grocy.example.net", "https://u:p@grocy.example.net", "https://g.example.net?key=1", "ftp://x", ""):
        with pytest.raises(grocy.GrocyError):
            grocy.normalize_url(bad)
    from supermarkt import config
    monkeypatch.setattr(config, "GROCY_FILE", tmp_path / "grocy.json")
    grocy.save(grocy.Settings("https://g.example.net", "secret-key-123", 3, 20))
    assert oct((tmp_path / "grocy.json").stat().st_mode & 0o777) == "0o600"
    loaded = grocy.load()
    assert (loaded.url, loaded.api_key, loaded.shopping_list_id, loaded.timeout_seconds) == ("https://g.example.net", "secret-key-123", 3, 20)
    grocy.clear()
    assert grocy.load() is None


def test_redirects_are_not_followed(monkeypatch):
    class Redirector(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/steal")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(grocy.GrocyError, match="leitet um"):
            grocy.call(grocy.Settings(f"http://127.0.0.1:{server.server_address[1]}", KEY, 1, 3), "GET", "/api/system/info")
    finally:
        server.shutdown()


def test_rest_routes_add_list_remove_and_hide_the_key(fake, tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from supermarkt import config
    from supermarkt.asgi import app
    state, settings = fake
    monkeypatch.setattr(config, "GROCY_FILE", tmp_path / "grocy.json")
    monkeypatch.setenv("SUPERMARKT_MCP_WARMUP", "0")
    client = TestClient(app)
    assert client.get("/api/v1/grocy").json()["configured"] is False
    assert client.post("/api/v1/grocy/items", json={"items": [{"name": "X"}]}).status_code == 404
    saved = client.put("/api/v1/grocy", json={"url": settings.url, "api_key": KEY, "shopping_list_id": 1})
    assert saved.status_code == 200 and saved.json()["configured"] is True and KEY not in saved.text
    assert client.put("/api/v1/grocy", json={"url": settings.url, "api_key": "wrong" * 10}).status_code == 502
    added = client.post("/api/v1/grocy/items", json={"items": [{"name": "Energy Test", "note": "bei REWE", "amount": 2}]}).json()["items"][0]
    assert added["status"] == "added"
    assert client.get("/api/v1/grocy/items").json()["items"][0]["name"] == "Energy Test"
    assert client.delete(f"/api/v1/grocy/items/{added['row_id']}", params={"name": "Anderer"}).status_code == 422
    assert client.delete(f"/api/v1/grocy/items/{added['row_id']}", params={"name": "Energy Test"}).json() == {"removed": True}
    assert client.delete("/api/v1/grocy/items/abc", params={"name": "x"}).status_code == 422
    assert any(p["name"] == "Energy Test" for p in state.products.values())
    assert client.delete("/api/v1/grocy").json()["configured"] is False


def test_mcp_shopping_tool_uses_grocy_when_kitchenowl_is_absent(fake, tmp_path, monkeypatch):
    import asyncio
    from supermarkt import config, mcp_server
    state, settings = fake
    monkeypatch.setattr(config, "KITCHENOWL_FILE", tmp_path / "none-kitchenowl.json")
    monkeypatch.setattr(config, "GROCY_FILE", tmp_path / "grocy.json")
    for name in ("SUPERMARKT_KITCHENOWL_URL", "SUPERMARKT_KITCHENOWL_TOKEN", "SUPERMARKT_KITCHENOWL_LIST_ID"):
        monkeypatch.delenv(name, raising=False)
    grocy.save(settings)
    mcp_server._shopping_adds.clear()
    first = asyncio.run(mcp_server.add_to_shopping_list("Monster Ultra", retailer="Netto", price="0,88 €"))
    second = asyncio.run(mcp_server.add_to_shopping_list("Monster Ultra", retailer="Netto", price="0,88 €"))
    assert first.structured_content["added"] is True and second.structured_content["added"] is False
    assert len(state.rows) == 1 and "Netto" in next(iter(state.rows.values()))["note"]
    assert mcp_server.register_shopping_tool() is True


def test_untrusted_certificate_is_a_clear_definite_failure_not_an_unknown_outcome(monkeypatch):
    import ssl
    import urllib.error

    def refuse(*_a, **_k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("self signed certificate"))

    monkeypatch.setattr(grocy._OPENER, "open", refuse)
    with pytest.raises(grocy.GrocyError, match="TLS-Zertifikat") as info:
        grocy.call(grocy.Settings("https://grocy.example.net", KEY, 1, 3), "GET", "/api/system/info")
    assert not isinstance(info.value, grocy.GrocyUnknownOutcome)


def test_two_shopping_lists_stay_separate_and_share_the_product(fake):
    state, settings = fake
    other = grocy.Settings(settings.url, KEY, 2, 3)
    a = grocy.add_items(settings, [("Milch", "Liste 1", 1)])[0]
    b = grocy.add_items(other, [("Milch", "Liste 2", 1)])[0]
    assert (a["status"], b["status"]) == ("added", "added") and a["row_id"] != b["row_id"] and a["product_id"] == b["product_id"]
    assert len(state.products) == 1 and len(state.rows) == 2
    assert [i["note"] for i in grocy.list_items(settings)] == ["Liste 1"] and [i["note"] for i in grocy.list_items(other)] == ["Liste 2"]
    with pytest.raises(grocy.GrocyError, match="gehört nicht"):
        grocy.remove_item(other, a["row_id"], "Milch")  # list 2 can never delete list 1's row
    assert grocy.remove_item(settings, a["row_id"], "Milch") is True
    assert [i["row_id"] for i in grocy.list_items(other)] == [b["row_id"]]


def test_parallel_adds_of_the_same_and_of_different_articles_create_no_duplicates(fake):
    state, settings = fake
    outcomes, errors = [], []

    def work(name):
        try:
            outcomes.append((name, grocy.add_items(settings, [(name, "", 1)])[0]["status"]))
        except Exception as exc:  # noqa: BLE001 - reported by the assertion
            errors.append(exc)

    names = ["Brot"] * 6 + ["Butter"] * 4 + [f"Artikel {i}" for i in range(6)]
    threads = [threading.Thread(target=work, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors
    assert len(state.rows) == 8 and len(state.products) == 8  # Brot, Butter, 6 others – one row each
    assert sum(1 for n, s in outcomes if n == "Brot" and s == "added") == 1
    assert sum(1 for n, s in outcomes if n == "Butter" and s == "added") == 1


def test_mcp_tool_parallel_calls_do_not_duplicate(fake, tmp_path, monkeypatch):
    import asyncio

    from supermarkt import config, mcp_server
    state, settings = fake
    monkeypatch.setattr(config, "KITCHENOWL_FILE", tmp_path / "no-kitchenowl.json")
    monkeypatch.setattr(config, "GROCY_FILE", tmp_path / "grocy.json")
    for name in ("SUPERMARKT_KITCHENOWL_URL", "SUPERMARKT_KITCHENOWL_TOKEN", "SUPERMARKT_KITCHENOWL_LIST_ID"):
        monkeypatch.delenv(name, raising=False)
    grocy.save(settings)
    mcp_server._shopping_adds.clear()

    async def run():
        return await asyncio.gather(*(mcp_server.add_to_shopping_list("Haferdrink", retailer="Lidl") for _ in range(5)))

    results = asyncio.run(run())
    assert sorted(r.structured_content["added"] for r in results) == [False, False, False, False, True]
    assert len(state.rows) == 1

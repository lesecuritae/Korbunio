import json

import pytest

from supermarkt import notify

URL = "https://api.telegram.org/bot123:ABC/sendMessage?chat_id=4711"


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_telegram_gets_json_with_chat_id_and_title_in_first_line(monkeypatch):
    seen = {}

    def fake_open(request, timeout=0):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["type"] = request.get_header("Content-type")
        return _Resp()

    monkeypatch.setattr(notify._OPENER, "open", fake_open)
    notify.send("Korbuino: Kong im Angebot", "Lidl: Kong 0,49 € (02.–07.11.)", URL)

    assert seen["url"] == "https://api.telegram.org/bot123:ABC/sendMessage"  # chat_id wandert in den Body
    assert seen["body"] == {"chat_id": "4711", "text": "Korbuino: Kong im Angebot\nLidl: Kong 0,49 € (02.–07.11.)"}
    assert seen["type"].startswith("application/json")


def test_telegram_without_chat_id_is_refused_before_any_request(monkeypatch):
    monkeypatch.setattr(notify._OPENER, "open", lambda *a, **k: pytest.fail("no request expected"))
    with pytest.raises(notify.NotifyError, match="chat_id"):
        notify.send("t", "x", "https://api.telegram.org/bot1:A/sendMessage")


def test_ntfy_still_gets_plain_text_with_title_header(monkeypatch):
    seen = {}

    def fake_open(request, timeout=0):
        seen["data"], seen["title"] = request.data, request.get_header("Title")
        return _Resp()

    monkeypatch.setattr(notify._OPENER, "open", fake_open)
    notify.send("Titel", "Text", "https://ntfy.example/thema")
    assert seen == {"data": b"Text", "title": "Titel"}

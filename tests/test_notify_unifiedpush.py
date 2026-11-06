from supermarkt import notify


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _capture(monkeypatch):
    seen = {}

    def fake_open(request, timeout=0):
        seen["body"], seen["title"] = request.data.decode(), request.get_header("Title")
        return _Resp()

    monkeypatch.setattr(notify._OPENER, "open", fake_open)
    return seen


def test_nextpush_endpoint_gets_title_as_first_line(monkeypatch):
    seen = _capture(monkeypatch)
    notify.send("Korbuino: Kong im Angebot", "Lidl: Kong 0,49 €", "https://cloud.example/index.php/apps/uppush/push/abc")
    assert seen["body"] == "Korbuino: Kong im Angebot\nLidl: Kong 0,49 €"


def test_ntfy_keeps_plain_text_and_title_header(monkeypatch):
    seen = _capture(monkeypatch)
    notify.send("Titel", "Text", "https://ntfy.example/thema")
    assert seen == {"body": "Text", "title": "Titel"}

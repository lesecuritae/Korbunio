import io, pytest
from urllib.error import HTTPError
from supermarkt import http as h
from supermarkt.models import ToolError

class Resp:
    def __init__(self, body, url="https://x.example/a"): self.b=body; self.u=url
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def geturl(self): return self.u
    def read(self,n=-1): return self.b[:n]

def client(): return h.HttpClient(5)

def test_429_is_retried_once_honouring_retry_after(monkeypatch):
    """BUG candidate: 429 with Retry-After is turned into an immediate ToolError, no retry/backoff."""
    calls=[]
    def fake(req, timeout=None, context=None):
        calls.append(1)
        if len(calls)==1:
            raise HTTPError(req.full_url,429,"Too Many",{"Retry-After":"0"},io.BytesIO(b""))
        return Resp(b'{"results":[]}')
    monkeypatch.setattr(h,"urlopen",fake)
    assert client().get_json("https://x.example/a")=={"results":[]}

def test_html_instead_of_json_and_truncated_json_raise(monkeypatch):
    for body in (b"<html>login</html>", b'{"results":[{"id":1},', b""):
        monkeypatch.setattr(h,"urlopen",lambda r,timeout=None,context=None,b=body: Resp(b))
        with pytest.raises(ToolError): client().get_json("https://x.example/a")

def test_null_and_list_payload_rejected(monkeypatch):
    for body in (b"null", b"[]", b'"x"'):
        monkeypatch.setattr(h,"urlopen",lambda r,timeout=None,context=None,b=body: Resp(b))
        with pytest.raises(ToolError): client().get_json("https://x.example/a")

def test_redirect_to_login_html_then_json_error(monkeypatch):
    monkeypatch.setattr(h,"urlopen",lambda r,timeout=None,context=None: Resp(b"<form>login</form>","https://x.example/login"))
    with pytest.raises(ToolError): client().get_json("https://x.example/a")

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from fastapi import HTTPException, Request

from .common import clean_text
from .config import MARKTGURU_HOME
from .images import is_rejected_image_url, normalize_image_url
from .loyalty import normalize_program_ids
from .models import AGGREGATOR_RETAILERS
from .security import api_key, signature, valid_signature


def require_api_auth(request: Request) -> None:
    expected = api_key()
    if not expected:
        return
    authorization = request.headers.get("authorization", "")
    scheme, _, credential = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not credential or not secrets.compare_digest(credential, expected):
        raise HTTPException(status_code=401, detail="Ungültiger Bearer-Token")


def result_token(search_id: str) -> str:
    return signature(search_id, namespace="result")


def verify_result_token(search_id: str, token: str) -> None:
    if not valid_signature(token, search_id, namespace="result"):
        raise HTTPException(status_code=403, detail="Ungültiger oder fehlender Ergebnis-Schlüssel")


def build_result_path(search_id: str, loyalty_programs: tuple[str, ...] = ()) -> str:
    params: dict[str, str] = {"token": result_token(search_id)}
    selected = normalize_program_ids(loyalty_programs)
    if selected:
        params["loyalty"] = ",".join(selected)
    return f"/results/{quote(search_id, safe='')}?{urlencode(params)}"


def build_result_url(request: Request, search_id: str, loyalty_programs: tuple[str, ...] = ()) -> str:
    return str(request.base_url).rstrip("/") + build_result_path(search_id, loyalty_programs)


def image_proxy_signature(source_url: str, referer: str, product: str, retailer: str) -> str:
    return signature(source_url, referer, product, retailer, namespace="image")


def build_image_proxy_url(offer: dict[str, Any]) -> str:
    source_url = normalize_image_url(offer.get("image_url"))
    if not source_url or is_rejected_image_url(source_url):
        return ""
    retailer = clean_text(offer.get("retailer"))
    product = clean_text(offer.get("product"))
    if not product:
        return ""
    image_host = (urlsplit(source_url).hostname or "").casefold()
    if image_host == "content-media.bonial.biz":
        referer = "https://www.kaufda.de/"
    else:
        referer = MARKTGURU_HOME if retailer in AGGREGATOR_RETAILERS else normalize_image_url(offer.get("source_url"))
    return "/image?" + urlencode({
        "src": source_url,
        "ref": referer,
        "q": product,
        "retailer": retailer,
        "sig": image_proxy_signature(source_url, referer, product, retailer),
    })


def proxy_page_images(page: dict[str, Any]) -> dict[str, Any]:
    for offer in page.get("offers") or []:
        if isinstance(offer, dict):
            offer["image_url"] = build_image_proxy_url(offer)
    return page

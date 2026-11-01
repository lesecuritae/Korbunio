from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import grocy, kitchenowl, notify
from .api_models import ShoppingListWriteRequest
from .api_routes import add_kitchenowl_items
from .security import api_key
from .access import require_admin_auth
from .ui import static_text

router = APIRouter()


def require_settings_access(request: Request) -> None:
    """Mit gesetztem Admin-Schlüssel nur damit; ohne Schlüssel ist der Server offen wie der Rest."""
    if api_key():
        require_admin_auth(request)


class ListsRequest(BaseModel):
    url: str = Field(max_length=300)
    token: str = Field(default="", max_length=4000)


class SaveRequest(ListsRequest):
    list_id: str = Field(pattern=r"^\d{1,12}$")


def _refresh_mcp() -> None:
    try:
        from .mcp_server import register_shopping_tool, register_watch_tools
    except ImportError:  # MCP nicht installiert oder abgeschaltet
        return
    register_shopping_tool()
    register_watch_tools()


def _status() -> dict:
    settings = kitchenowl.load()
    return {
        "configured": settings is not None,
        "url": settings.url if settings else "",
        "list_id": settings.list_id if settings else "",
        "list_label": settings.list_label if settings else "",
        "auth_required": bool(api_key()),
    }


@router.get("/settings", include_in_schema=False, response_class=HTMLResponse)
def settings_page() -> HTMLResponse:
    return HTMLResponse(static_text("settings.html"), headers={"Cache-Control": "no-store"})


@router.get("/api/v1/kitchenowl", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def kitchenowl_status() -> dict:
    return _status()


@router.post("/api/v1/kitchenowl/lists", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def kitchenowl_lists(payload: ListsRequest) -> dict:
    token = payload.token.strip() or (kitchenowl.load().token if kitchenowl.load() else "")
    if not token:
        raise HTTPException(status_code=422, detail="Bitte den KitchenOwl-Token eintragen.")
    try:
        return {"lists": kitchenowl.fetch_lists(payload.url, token)}
    except kitchenowl.KitchenOwlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/api/v1/kitchenowl", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def kitchenowl_save(payload: SaveRequest) -> dict:
    current = kitchenowl.load()
    token = payload.token.strip() or (current.token if current else "")
    if not token:
        raise HTTPException(status_code=422, detail="Bitte den KitchenOwl-Token eintragen.")
    try:
        url = kitchenowl.normalize_url(payload.url)
        lists = {entry["id"]: entry["label"] for entry in kitchenowl.fetch_lists(url, token)}
    except kitchenowl.KitchenOwlError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if payload.list_id not in lists:
        raise HTTPException(status_code=422, detail="Diese Liste gibt es bei KitchenOwl nicht.")
    kitchenowl.save(kitchenowl.Settings(url, token, payload.list_id, lists[payload.list_id]))
    _refresh_mcp()
    return _status()


@router.delete("/api/v1/kitchenowl", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def kitchenowl_delete() -> dict:
    kitchenowl.clear()
    _refresh_mcp()
    return _status()


@router.post("/api/v1/kitchenowl/items", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def kitchenowl_add_items(payload: ShoppingListWriteRequest) -> dict[str, list[str]]:
    """Files browser shopping-list items without exposing the KitchenOwl token."""
    return add_kitchenowl_items(payload)


class NotifyRequest(BaseModel):
    url: str = Field(max_length=500)


@router.get("/api/v1/notify", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def notify_status() -> dict:
    return {"configured": notify.load() is not None}


@router.put("/api/v1/notify", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def notify_save(payload: NotifyRequest) -> dict:
    try:
        url = notify.normalize_url(payload.url)
        notify.send("Korbuino", "Test: So melden sich Beobachtungen.", url)
        notify.save(url)
    except notify.NotifyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _refresh_mcp()
    return notify_status()


@router.delete("/api/v1/notify", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def notify_delete() -> dict:
    notify.clear()
    _refresh_mcp()
    return notify_status()


class GrocySaveRequest(BaseModel):
    url: str = Field(max_length=300)
    api_key: str = Field(default="", max_length=400)
    shopping_list_id: int = Field(default=1, ge=1, le=10**9)


class GrocyItem(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=500)
    amount: float = Field(default=1.0, gt=0, le=10_000)


class GrocyAddRequest(BaseModel):
    items: list[GrocyItem] = Field(min_length=1, max_length=100)


def _grocy_status() -> dict:
    settings = grocy.load()
    return {"configured": settings is not None, "url": settings.url if settings else "",
            "shopping_list_id": settings.shopping_list_id if settings else None, "auth_required": bool(api_key())}


def _grocy_settings() -> grocy.Settings:
    settings = grocy.load()
    if settings is None:
        raise HTTPException(status_code=404, detail="Grocy ist auf diesem Server nicht eingerichtet.")
    return settings


@router.get("/api/v1/grocy", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def grocy_status() -> dict:
    return _grocy_status()


@router.put("/api/v1/grocy", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def grocy_save(payload: GrocySaveRequest) -> dict:
    current = grocy.load()
    key = payload.api_key.strip() or (current.api_key if current else "")
    if not key:
        raise HTTPException(status_code=422, detail="Bitte den Grocy-API-Schlüssel eintragen.")
    try:
        settings = grocy.Settings(grocy.normalize_url(payload.url), key, payload.shopping_list_id)
        grocy.verify(settings)
    except grocy.GrocyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    grocy.save(settings)
    _refresh_mcp()
    return _grocy_status()


@router.delete("/api/v1/grocy", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def grocy_delete() -> dict:
    grocy.clear()
    _refresh_mcp()
    return _grocy_status()


@router.post("/api/v1/grocy/items", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def grocy_add_items(payload: GrocyAddRequest) -> dict:
    settings = _grocy_settings()
    try:
        results = grocy.add_items(settings, [(item.name, item.note, item.amount) for item in payload.items])
    except grocy.GrocyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"items": results}


@router.get("/api/v1/grocy/items", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def grocy_items() -> dict:
    settings = _grocy_settings()
    try:
        return {"items": grocy.list_items(settings)}
    except grocy.GrocyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/api/v1/grocy/items/{row_id}", include_in_schema=False, dependencies=[Depends(require_settings_access)])
def grocy_remove_item(row_id: str, name: str) -> dict:
    """Removes exactly one list row (identity checked, confirmed by re-reading). Never deletes Grocy products."""
    settings = _grocy_settings()
    try:
        removed = grocy.remove_item(settings, row_id, name)
    except grocy.GrocyError as exc:
        raise HTTPException(status_code=422 if "Ungültige" in str(exc) or "passt nicht" in str(exc) or "gehört nicht" in str(exc) else 502, detail=str(exc)) from exc
    return {"removed": removed}

"""Per-thread diagnostics for adapters that one process shares between concurrent loads.

An adapter such as the REWE source records which market it used in ``last_*`` attributes while it loads. With two
overlapping requests (different postal codes) a plain instance attribute is overwritten by the other request. Each load
runs in one worker thread and the service snapshots these attributes in that same thread right after loading, so
thread-local storage keeps the values request-bound without serialising any network I/O.
"""
from __future__ import annotations

import threading
from typing import Any, Callable


class RequestState:
    def __init__(self, default: Any = None, factory: Callable[[], Any] | None = None) -> None:
        self.default = default
        self.factory = factory

    def __set_name__(self, owner: type, name: str) -> None:
        self.slot = "_rs_" + name

    @staticmethod
    def _local(obj: Any) -> threading.local:
        local = obj.__dict__.get("_request_local")
        if local is None:
            local = obj.__dict__.setdefault("_request_local", threading.local())
        return local

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        if obj is None:
            return self
        local = self._local(obj)
        if not hasattr(local, self.slot):
            setattr(local, self.slot, self.factory() if self.factory else self.default)
        return getattr(local, self.slot)

    def __set__(self, obj: Any, value: Any) -> None:
        setattr(self._local(obj), self.slot, value)

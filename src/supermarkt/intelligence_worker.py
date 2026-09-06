"""Long-running Clawforge intelligence worker entry point.

The API process keeps scheduler autostart disabled. This module owns the
separate worker process used by Compose and handles graceful termination.
"""

from __future__ import annotations

import os
import signal
import threading
from typing import Any

from .clawforge.feed_sync import IntelligenceService


def run_worker(*, service: IntelligenceService | None = None, poll_seconds: float | None = None, stop_event: threading.Event | None = None) -> None:
    intelligence = service or IntelligenceService.create()
    stop = stop_event or threading.Event()

    def request_stop(_signum: int, _frame: Any) -> None:
        stop.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
    interval = poll_seconds if poll_seconds is not None else float(os.getenv("CLAWFORGE_WORKER_POLL_SECONDS", "5"))
    intelligence.scheduler.start(poll_seconds=max(1.0, interval))
    try:
        stop.wait()
    finally:
        intelligence.stop()


def main() -> None:
    run_worker()


if __name__ == "__main__":  # pragma: no cover - process entry point
    main()

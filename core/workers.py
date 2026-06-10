# core/workers.py — supervised background workers for LocusAI
#
# Wraps a periodic "tick" function in a loop that NEVER dies: every tick runs
# inside try/except, failures are logged and retried with exponential backoff,
# and a heartbeat is recorded so /health can show each worker is alive.

import threading
import time
import logging
from datetime import datetime, timezone
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger(__name__)

# name -> {started_at, last_run, last_error, runs, errors, interval}
HEARTBEATS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

# How stale (seconds past its interval) a worker's last_run can be before it's
# considered unhealthy. Generous multiple to avoid false alarms.
STALE_MULTIPLIER = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_supervised(
    name: str,
    tick: Callable[[], None],
    interval: float,
    *,
    initial_delay: float = 0.0,
    stop_event: Optional[threading.Event] = None,
    max_backoff: float = 60.0,
) -> None:
    """Run `tick` every `interval` seconds forever, surviving any exception.

    Exits only when `stop_event` is set (used in tests). On error, retries with
    exponential backoff capped at `max_backoff`."""
    with _LOCK:
        HEARTBEATS[name] = {
            "started_at": _now().isoformat(), "last_run": None,
            "last_error": None, "runs": 0, "errors": 0, "interval": interval,
        }
    hb = HEARTBEATS[name]

    def _sleep(seconds: float) -> None:
        if stop_event is not None:
            stop_event.wait(seconds)
        else:
            time.sleep(seconds)

    if initial_delay:
        _sleep(initial_delay)

    backoff = 1.0
    while not (stop_event is not None and stop_event.is_set()):
        try:
            tick()
            hb["last_run"] = _now().isoformat()
            hb["runs"] += 1
            backoff = 1.0
            wait = interval
        except Exception as e:  # never let the loop die
            hb["errors"] += 1
            hb["last_error"] = f"{type(e).__name__}: {e}"
            logger.warning("Worker '%s' tick failed (#%d): %s",
                           name, hb["errors"], e, exc_info=True)
            wait = min(interval, backoff)
            backoff = min(backoff * 2, max_backoff)
        _sleep(wait)


def start_worker(
    name: str,
    tick: Callable[[], None],
    interval: float,
    *,
    initial_delay: float = 0.0,
) -> threading.Thread:
    """Spawn a daemon thread running `tick` under supervision."""
    t = threading.Thread(
        target=run_supervised, name=f"worker:{name}",
        args=(name, tick, interval), kwargs={"initial_delay": initial_delay},
        daemon=True,
    )
    t.start()
    logger.info("Started supervised worker '%s' (every %ss)", name, interval)
    return t


def heartbeat_snapshot() -> Dict[str, Dict[str, Any]]:
    """Per-worker status for /health, including a derived `healthy` flag."""
    out = {}
    now = _now()
    with _LOCK:
        items = list(HEARTBEATS.items())
    for name, hb in items:
        healthy = True
        last_run = hb.get("last_run")
        interval = hb.get("interval") or 0
        if last_run:
            try:
                age = (now - datetime.fromisoformat(last_run)).total_seconds()
                healthy = age <= max(interval * STALE_MULTIPLIER, interval + 60)
            except (ValueError, TypeError):
                pass
        out[name] = {**hb, "healthy": healthy}
    return out

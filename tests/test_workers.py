# tests/test_workers.py — supervised background worker harness

import threading
import time

from core import workers


def _run(name, tick, *, duration=0.25, interval=0.01):
    stop = threading.Event()
    t = threading.Thread(
        target=workers.run_supervised, args=(name, tick, interval),
        kwargs={"stop_event": stop}, daemon=True,
    )
    t.start()
    time.sleep(duration)
    stop.set()
    t.join(timeout=2)
    return workers.HEARTBEATS[name]


class TestSupervisor:
    def test_runs_repeatedly_and_records_heartbeat(self):
        calls = []
        hb = _run("t_repeat", lambda: calls.append(1))
        assert len(calls) >= 3
        assert hb["runs"] >= 3
        assert hb["last_run"] is not None
        assert hb["errors"] == 0

    def test_survives_exceptions_and_recovers(self):
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] <= 2:
                raise ValueError("boom")

        hb = _run("t_flaky", flaky)
        assert hb["errors"] >= 2          # caught the failures
        assert hb["runs"] >= 1            # kept going and recovered
        assert "boom" in (hb["last_error"] or "")

    def test_never_dies_when_tick_always_fails(self):
        def always_fail():
            raise RuntimeError("nope")

        hb = _run("t_dead", always_fail, duration=0.2)
        # Loop must still be alive and accumulating errors, not crashed.
        assert hb["errors"] >= 2
        assert hb["runs"] == 0

    def test_heartbeat_snapshot_marks_healthy(self):
        _run("t_health", lambda: None, duration=0.1)
        snap = workers.heartbeat_snapshot()
        assert "t_health" in snap
        assert snap["t_health"]["healthy"] is True

    def test_initial_delay_respected(self):
        calls = []
        stop = threading.Event()
        t = threading.Thread(
            target=workers.run_supervised, args=("t_delay", lambda: calls.append(1), 0.01),
            kwargs={"initial_delay": 0.2, "stop_event": stop}, daemon=True,
        )
        t.start()
        time.sleep(0.05)  # before the delay elapses
        early = len(calls)
        stop.set()
        t.join(timeout=2)
        assert early == 0  # nothing ran during the initial delay

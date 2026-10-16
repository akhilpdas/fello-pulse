"""Found by actually running the container stack: on a fresh deployment there is no trained model until
``bootstrap-demo`` has run, so the worker raised ``LookupError`` and exited -- and the container runtime restarted it
forever. A worker must *wait* for what it needs and pick it up when it appears, with no restart.

Names the production change that makes it fail: ``worker.serve`` accepting a callable that yields the current
runtimes each tick (and tolerating "no model yet"), and ``cli.cmd_serve`` using it.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pulse.cli as cli
from pulse.agent import worker
from pulse.config import FrozenClock


def test_serve_asks_for_the_runtimes_every_tick_and_survives_a_missing_model(monkeypatch, caplog):
    seen = []

    def runtimes():
        seen.append(len(seen))
        if len(seen) < 3:
            raise LookupError("no promoted model yet")
        return []

    ticked = []
    monkeypatch.setattr(worker, "tick", lambda rts, **kw: ticked.append(list(rts)) or [])
    worker.serve(runtimes, clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)), max_ticks=4, sleep=lambda s: None)
    assert seen == [0, 1, 2, 3], "the runtimes must be re-resolved on every tick"
    assert ticked == [[], [], [], []], "no crash, and a tick with nothing to run until the model exists"
    assert "no promoted model yet" in caplog.text or "waiting" in caplog.text.lower()


def test_a_plain_list_still_works():
    seen = []
    import pulse.agent.worker as w
    original = w.tick
    w.tick = lambda rts, **kw: seen.append(rts) or []
    try:
        w.serve(["x"], clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)), max_ticks=2, sleep=lambda s: None)
    finally:
        w.tick = original
    assert seen == [["x"], ["x"]]


def test_the_serve_command_waits_instead_of_exiting_when_there_is_no_model(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_load_promoted", lambda artifacts: (_ for _ in ()).throw(LookupError("no promoted model")))
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    rc = cli.cmd_serve(argparse.Namespace(artifacts="../artifacts", simulate_present=False, max_ticks=2))
    assert rc == 0, "a missing model must not be fatal"
    assert "waiting" in capsys.readouterr().out.lower()


def test_a_clock_that_follows_the_datas_present_works_before_any_data_exists():
    """A fresh stack has no events yet, so ``--simulate-present`` cannot know the data's present at start-up. The clock must
    behave as the real clock until data appears, then fix its offset and keep moving."""
    from datetime import timedelta

    from pulse.config import LazyOffsetClock

    real = FrozenClock(datetime(2026, 10, 17, 9, 0, tzinfo=UTC))
    newest = {"v": None}
    clock = LazyOffsetClock(real, lambda: newest["v"])
    assert clock.now() == datetime(2026, 10, 17, 9, 0, tzinfo=UTC)  # no data yet: the real clock
    newest["v"] = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    assert clock.now() == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)  # data appeared: its present
    real.advance(minutes=30)
    newest["v"] = datetime(2030, 1, 1, tzinfo=UTC)  # later data must not move the fixed offset
    assert clock.now() == datetime(2026, 11, 10, 9, 30, tzinfo=UTC) and clock.now() - real.now() == timedelta(days=24)

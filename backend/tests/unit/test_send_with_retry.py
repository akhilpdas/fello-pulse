"""agent/transport.py's send_with_retry (T076): bounded retry, stop on first
success, surface the final result on exhaustion."""

from __future__ import annotations

from pulse.agent.transport import RecordingTransport, send_with_retry


def test_succeeds_immediately_without_extra_attempts():
    t = RecordingTransport()
    result, attempts = send_with_retry(t, to="a@x.test", subject="s", body="b")
    assert result.ok is True
    assert attempts == 1


def test_recovers_within_the_retry_budget():
    t = RecordingTransport(fail_next=2)
    result, attempts = send_with_retry(t, to="a@x.test", subject="s", body="b", max_attempts=3)
    assert result.ok is True
    assert attempts == 3


def test_exhausts_the_budget_and_surfaces_the_last_failure():
    t = RecordingTransport(fail_next=10)
    result, attempts = send_with_retry(t, to="a@x.test", subject="s", body="b", max_attempts=3)
    assert result.ok is False
    assert result.error == "simulated_transport_failure"
    assert attempts == 3
    assert t.sent == []

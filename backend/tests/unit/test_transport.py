"""agent/transport.py (T064): the outbound interface and its recording
implementation -- no real network call, every attempt kept for assertions."""

from __future__ import annotations

from pulse.agent.transport import RecordingTransport


def test_send_records_the_message_and_reports_ok():
    t = RecordingTransport()
    result = t.send(to="csm@example.test", subject="Hi", body="body")
    assert result.ok is True
    assert t.sent == [{"to": "csm@example.test", "subject": "Hi", "body": "body"}]


def test_fail_next_simulates_a_bounded_number_of_failures():
    t = RecordingTransport(fail_next=2)
    r1 = t.send(to="a@x.test", subject="s", body="b")
    r2 = t.send(to="a@x.test", subject="s", body="b")
    r3 = t.send(to="a@x.test", subject="s", body="b")
    assert (r1.ok, r2.ok, r3.ok) == (False, False, True)
    assert len(t.sent) == 1

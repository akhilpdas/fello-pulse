"""T254 / T256 (FR-013, FR-017, FR-018, FR-021): a real SMTP transport, exercised against an in-process fake
mail server that can be told to misbehave. No test sends real mail.

Names the production change that makes it fail: ``pulse.agent.transport.SmtpTransport`` (and the
``SendResult.kind`` classification that ``send_with_retry`` honours) plus ``pulse.tools.smtp_sink``.
"""

from __future__ import annotations

import email

import pytest

from pulse.agent.transport import RecordingTransport, SmtpTransport, send_with_retry
from pulse.config import Settings
from pulse.tools.smtp_sink import SmtpSink


def _transport(sink: SmtpSink, **kw) -> SmtpTransport:
    return SmtpTransport(host="127.0.0.1", port=sink.port, starttls=False, timeout=kw.pop("timeout", 2.0), **kw)


def _send(t, **kw):
    return t.send(to="sofia@acme.example.com", subject="Checking in", body="Hello Sofia,\n\nA note.\n",
                  sender="csm@northwind.example.com", message_id="<action-123@pulse.example.com>", **kw)


def test_delivers_exactly_one_message_with_the_right_headers_and_body():
    with SmtpSink() as sink:
        result = _send(_transport(sink))
        assert result.ok and result.kind == "ok"
        assert len(sink.messages) == 1
        m = sink.messages[0]
        assert m["mail_from"] == "csm@northwind.example.com" and m["rcpt_to"] == ["sofia@acme.example.com"]
        parsed = email.message_from_string(m["data"])
        assert parsed["From"] == "csm@northwind.example.com" and parsed["To"] == "sofia@acme.example.com"
        assert parsed["Subject"] == "Checking in"
        assert parsed["Message-ID"] == "<action-123@pulse.example.com>"  # derived from the action, so duplicates are detectable
        assert "A note." in parsed.get_payload(decode=True).decode()


def test_settings_build_a_transport_and_the_password_is_not_in_its_repr():
    s = Settings(smtp_host="mail.example.test", smtp_port=2525, smtp_user="u", smtp_password="hunter2-smtp",
                 smtp_starttls=False, _env_file=None)
    t = SmtpTransport.from_settings(s)
    assert (t.host, t.port, t.starttls) == ("mail.example.test", 2525, False)
    assert "hunter2-smtp" not in repr(t) and "hunter2-smtp" not in str(t.__dict__.get("password_repr", ""))


def test_nothing_listening_is_a_transient_failure():
    with SmtpSink() as sink:
        port = sink.port
    t = SmtpTransport(host="127.0.0.1", port=port, starttls=False, timeout=1.0)  # sink is gone
    r = _send(t)
    assert (r.ok, r.kind) == (False, "transient")


@pytest.mark.parametrize("mode,kind", [
    ("reject_rcpt", "permanent"),      # 550: this address will never work
    ("tempfail_rcpt", "transient"),    # 451: try again later
    ("greet_421", "transient"),        # service not available
    ("hang_after_data", "ambiguous"),  # the body was sent and no answer came back: it may or may not have been accepted
])
def test_failures_are_classified(mode, kind):
    with SmtpSink(mode=mode) as sink:
        r = _send(_transport(sink, timeout=0.6))
        assert (r.ok, r.kind) == (False, kind), r
        assert r.error


def test_transient_failures_are_retried_up_to_the_bound_and_then_succeed():
    with SmtpSink(mode="tempfail_rcpt", fail_first=2) as sink:
        result, attempts = send_with_retry(_transport(sink), to="a@b.example.com", subject="s", body="b",
                                           sender="x@y.example.com", message_id="<m1@p>", max_attempts=3)
        assert result.ok and attempts == 3
        assert len(sink.messages) == 1


def test_a_permanent_failure_is_not_retried():
    with SmtpSink(mode="reject_rcpt") as sink:
        result, attempts = send_with_retry(_transport(sink), to="a@b.example.com", subject="s", body="b",
                                           sender="x@y.example.com", message_id="<m2@p>", max_attempts=3)
        assert (result.ok, result.kind, attempts) == (False, "permanent", 1)
        assert sink.rcpt_attempts == 1


def test_an_ambiguous_outcome_is_never_retried_so_a_customer_cannot_get_two_emails():
    with SmtpSink(mode="hang_after_data") as sink:
        result, attempts = send_with_retry(_transport(sink, timeout=0.6), to="a@b.example.com", subject="s", body="b",
                                           sender="x@y.example.com", message_id="<m3@p>", max_attempts=3)
        assert (result.ok, result.kind, attempts) == (False, "ambiguous", 1)
        assert sink.data_attempts == 1


def test_the_recording_transport_accepts_the_same_call_and_remains_the_safe_default():
    t = RecordingTransport()
    r = t.send(to="a@b.example.com", subject="s", body="b", sender="x@y.example.com", message_id="<m@p>")
    assert r.ok and r.kind == "ok" and t.sent[0]["to"] == "a@b.example.com"

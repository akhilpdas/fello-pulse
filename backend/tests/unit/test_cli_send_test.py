"""``pulse send-test``: the one-command way to prove the *real* mail path with real credentials -- send a clearly labelled
test message to an address you choose, and say exactly how it went. It touches no database and no customer.

Until someone runs this against a real provider, "real email works" is unverified; this makes that a one-minute job.
Tested here against the fake SMTP server.

Names the production change that makes it fail: ``pulse.cli.cmd_send_test``.
"""

from __future__ import annotations

import argparse

import pytest

import pulse.cli as cli
from pulse.config import reset_settings
from pulse.tools.smtp_sink import SmtpSink


@pytest.fixture(autouse=True)
def _settings():
    yield
    reset_settings()


def _args(**kw):
    return argparse.Namespace(**{"to": "me@example.test", "sender": "pulse@example.test", **kw})


def _configure(monkeypatch, sink):
    monkeypatch.setenv("PULSE_SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("PULSE_SMTP_PORT", str(sink.port))
    monkeypatch.setenv("PULSE_SMTP_STARTTLS", "false")
    monkeypatch.delenv("PULSE_SMTP_USER", raising=False)
    monkeypatch.delenv("PULSE_SMTP_PASSWORD", raising=False)
    reset_settings()


def test_sends_one_clearly_labelled_message_and_reports_success(monkeypatch, capsys):
    with SmtpSink() as sink:
        _configure(monkeypatch, sink)
        assert cli.cmd_send_test(_args()) == 0
        assert len(sink.messages) == 1 and sink.messages[0]["rcpt_to"] == ["me@example.test"]
        assert "test message" in sink.messages[0]["data"].lower() and "no customer" in sink.messages[0]["data"].lower()
    assert "delivered" in capsys.readouterr().out.lower()


def test_without_a_configured_host_it_says_so_and_sends_nothing(monkeypatch, capsys):
    monkeypatch.setenv("PULSE_SMTP_HOST", "")
    reset_settings()
    assert cli.cmd_send_test(_args()) == 2
    assert "PULSE_SMTP_HOST" in capsys.readouterr().out


def test_a_provider_refusal_is_reported_with_its_classification_and_a_failing_exit_code(monkeypatch, capsys):
    with SmtpSink(mode="reject_rcpt") as sink:
        _configure(monkeypatch, sink)
        assert cli.cmd_send_test(_args()) == 1
    out = capsys.readouterr().out.lower()
    assert "permanent" in out and "550" in out


def test_an_unconfirmed_outcome_tells_you_to_check_the_inbox(monkeypatch, capsys):
    with SmtpSink(mode="hang_after_data") as sink:
        _configure(monkeypatch, sink)
        monkeypatch.setenv("PULSE_SMTP_TIMEOUT", "0.6")
        reset_settings()
        assert cli.cmd_send_test(_args()) == 1
    assert "check" in capsys.readouterr().out.lower()

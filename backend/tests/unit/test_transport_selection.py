"""T269 (FR-022): the deployment uses real SMTP only when it is configured; with nothing configured the whole
system runs on the recording stub. The tenant's own switches (the send gate) decide the rest.

Names the production change that makes it fail: ``pulse.agent.transport.select_transport``, used by the API
dependency and by both worker entry points (``pulse cycle`` / ``pulse serve``).
"""

from __future__ import annotations

from pulse.agent.transport import RecordingTransport, SmtpTransport, select_transport
from pulse.config import Settings


def test_nothing_configured_means_the_recording_stub():
    assert isinstance(select_transport(Settings(_env_file=None)), RecordingTransport)


def test_a_configured_host_means_real_smtp_without_leaking_the_password():
    t = select_transport(Settings(smtp_host="mail.example.test", smtp_user="u", smtp_password="hunter2-smtp", _env_file=None))
    assert isinstance(t, SmtpTransport) and t.host == "mail.example.test"
    assert "hunter2-smtp" not in repr(t)


def test_an_empty_host_is_not_configured():
    assert isinstance(select_transport(Settings(smtp_host="", _env_file=None)), RecordingTransport)


def test_the_cli_workers_use_the_selector_not_a_hard_coded_stub():
    from pathlib import Path
    cli = (Path(__file__).resolve().parents[2] / "pulse" / "cli.py").read_text()
    assert "RecordingTransport()" not in cli and cli.count("select_transport(") >= 2

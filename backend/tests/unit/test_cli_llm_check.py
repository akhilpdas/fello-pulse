"""``pulse llm-check``: the command around ``check_llm`` (spec 003, T027)."""

from __future__ import annotations

import pulse.cli as cli
from pulse.llm_check import CheckResult


def _fake(result):
    def check(**kw):
        check.called_with = kw
        return result
    return check


def test_it_is_a_subcommand():
    assert callable(cli.build_parser().parse_args(["llm-check"]).fn)


def test_success_exits_zero_and_prints_model_latency_and_observed_limits(monkeypatch, capsys):
    monkeypatch.setattr("pulse.llm_check.check_llm", _fake(CheckResult(
        True, "ok", "openai_compatible", "llama-3.3-70b-versatile", 412, "pong",
        {"limit-requests": "1000", "remaining-requests": "999"})))
    assert cli.cmd_llm_check(None) == 0
    out = capsys.readouterr().out
    assert "llama-3.3-70b-versatile" in out and "412 ms" in out and "limit-requests: 1000" in out and "pong" in out


def test_failure_exits_non_zero_and_says_what_to_do(monkeypatch, capsys):
    monkeypatch.setattr("pulse.llm_check.check_llm", _fake(CheckResult(
        False, "unauthorized", "openai_compatible", "m", 80, detail="HTTP 401: the provider rejected the key")))
    assert cli.cmd_llm_check(None) == 1
    assert "rejected the key" in capsys.readouterr().out


def test_the_key_is_never_printed(monkeypatch, capsys):
    monkeypatch.setenv("PULSE_LLM_API_KEY", "gsk_super_secret_value")
    monkeypatch.setattr("pulse.llm_check.check_llm", _fake(CheckResult(True, "ok", "openai_compatible", "m", 1, "pong")))
    from pulse.config import get_settings
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    cli.cmd_llm_check(None)
    assert "gsk_super_secret_value" not in capsys.readouterr().out

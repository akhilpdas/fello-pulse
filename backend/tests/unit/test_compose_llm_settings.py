"""The language-model choice must be selectable when running in Docker (found by the reviewer-style dry run).

``docker-compose.yml`` passed ``PULSE_LLM_ENABLED`` and the key into the containers but not the provider, base URL or
model, so the free-model option (Ollama, Groq, ...) could not be switched on without editing the file. Switching between
templates, a free model and Anthropic must be a matter of environment variables (or a ``.env`` file) only.
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.yml"
NEEDED = ("PULSE_LLM_ENABLED", "PULSE_LLM_PROVIDER", "PULSE_LLM_BASE_URL", "PULSE_LLM_MODEL", "PULSE_LLM_API_KEY")


def _env(service: str) -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"][service]["environment"]


def test_the_api_and_the_worker_receive_every_language_model_setting():
    for service in ("api", "worker"):   # the worker is the one that drafts during unattended cycles
        missing = [k for k in NEEDED if k not in _env(service)]
        assert not missing, (service, missing)


def test_the_defaults_leave_drafting_off_and_anthropic_the_provider():
    env = _env("api")
    assert env["PULSE_LLM_ENABLED"].endswith(":-false}")
    assert ":-anthropic}" in env["PULSE_LLM_PROVIDER"]
    # an empty string would override the code's default model name, so the default must be spelled out
    assert "claude-" in env["PULSE_LLM_MODEL"]

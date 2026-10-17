"""Choosing the language-model provider by configuration.

* default is Anthropic and behaves exactly as before (no key -> no model, templates only);
* ``PULSE_LLM_PROVIDER=openai_compatible`` + ``PULSE_LLM_BASE_URL`` selects a free/local model, which needs no key;
* the feature is still off unless ``PULSE_LLM_ENABLED`` is true, and a mistake in the configuration degrades to the
  template drafter instead of raising.

Names the production change that makes these fail: ``Settings.llm_provider`` / ``llm_base_url`` and ``cycle._make_llm``.
"""

from __future__ import annotations

import pytest

import pulse.agent.cycle as cycle
from pulse.agent.llm_drafter import AnthropicClient, LlmDrafter, OpenAICompatibleClient
from pulse.config import Settings
from pulse.db.session import owner_session


@pytest.fixture
def settings_with(monkeypatch):
    def apply(**fields):
        s = Settings(**fields)
        monkeypatch.setattr(cycle, "get_settings", lambda: s)
        return s
    return apply


def _make(enabled=True, key=None):
    with owner_session() as session:
        return cycle._make_llm(session, None, enabled, key)


def test_settings_default_to_anthropic_with_no_base_url():
    s = Settings()
    assert s.llm_provider == "anthropic" and s.llm_base_url is None


def test_settings_read_the_provider_from_the_environment(monkeypatch):
    monkeypatch.setenv("PULSE_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("PULSE_LLM_BASE_URL", "http://localhost:11434/v1")
    s = Settings()
    assert s.llm_provider == "openai_compatible" and s.llm_base_url == "http://localhost:11434/v1"


def test_a_keyless_local_model_is_used_when_enabled(settings_with):
    settings_with(llm_provider="openai_compatible", llm_base_url="http://127.0.0.1:11434/v1", llm_model="llama3.2")
    drafter = _make(enabled=True, key=None)
    assert isinstance(drafter, LlmDrafter) and isinstance(drafter.client, OpenAICompatibleClient)
    assert drafter.model == "llama3.2"


def test_a_local_model_is_still_off_unless_enabled(settings_with):
    settings_with(llm_provider="openai_compatible", llm_base_url="http://127.0.0.1:11434/v1")
    assert _make(enabled=False, key=None) is None


def test_anthropic_without_a_key_is_still_no_model(settings_with):
    settings_with(llm_provider="anthropic")
    assert _make(enabled=True, key=None) is None
    assert _make(enabled=True, key="   ") is None


def test_a_misconfigured_local_provider_degrades_to_templates_instead_of_raising(settings_with):
    settings_with(llm_provider="openai_compatible", llm_base_url=None)
    assert _make(enabled=True, key=None) is None
    settings_with(llm_provider="not-a-provider", llm_base_url="http://x/v1")
    assert _make(enabled=True, key="k") is None


def test_the_anthropic_path_is_unchanged_when_a_key_is_given(settings_with):
    pytest.importorskip("anthropic")
    settings_with(llm_provider="anthropic")
    drafter = _make(enabled=True, key="sk-test")
    assert isinstance(drafter.client, AnthropicClient)

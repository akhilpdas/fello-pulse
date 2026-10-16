"""The unattended worker honours the deployment's language-model settings (FR-024): with the feature enabled and
a key present, its cycles draft through the model drafter; with neither, they do not.

Names the production change that makes it fail: ``worker.run_once`` passing ``llm_enabled`` / ``llm_api_key``
from settings to ``run_cycle`` (it passed neither, so the model could never run unattended).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

import pulse.agent.llm_drafter as llm_module
from pulse.agent.llm_drafter import LlmDrafter
from pulse.agent.transport import RecordingTransport
from pulse.agent.worker import run_once
from pulse.config import reset_settings
from pulse.db.session import owner_session
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 7, 8, 9, 0, tzinfo=UTC)


class Echo:
    def complete(self, system, user, *, model, max_tokens, timeout):
        doc = json.loads(user)
        return json.dumps({"subject": "Following up", "claims": doc["allowed_claims"][:1],
                           "body": f"Hi {doc['account_name']} team, " + "; ".join(doc["facts"]) + f". Best, {doc['csm_name']}"})


def _run(monkeypatch, *, enabled: bool, key: str | None):
    monkeypatch.setenv("PULSE_LLM_ENABLED", "true" if enabled else "false")
    if key:
        monkeypatch.setenv("PULSE_LLM_API_KEY", key)
    else:
        monkeypatch.delenv("PULSE_LLM_API_KEY", raising=False)
    reset_settings()
    seen = {}
    monkeypatch.setattr(llm_module, "build_llm_drafter",
                        lambda k, **kw: seen.setdefault("key", k) and LlmDrafter(Echo(), model=kw["model"], max_calls=kw["max_calls"]))
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        seed_account(s, tenant_id, AS_OF, "wk-a", n_tickets=15)
    result = run_once(tenant_id=tenant_id, model=toy_support_model(13), model_version="t", tenant_config=cfg,
                      as_of=AS_OF, transport=RecordingTransport(), worker_id="w", lease_seconds=60)
    with owner_session() as s:
        sources = s.execute(text("SELECT draft_source FROM action WHERE agent_run_id = :r"), {"r": result.run_id}).scalars().all()
    reset_settings()
    return sources, seen


def test_enabled_and_keyed_the_unattended_cycle_drafts_through_the_model(monkeypatch):
    sources, seen = _run(monkeypatch, enabled=True, key="sk-test-key")
    assert sources == ["llm"] and seen["key"] == "sk-test-key"


def test_disabled_or_unkeyed_the_unattended_cycle_never_touches_the_model(monkeypatch):
    for enabled, key in [(False, "sk-test-key"), (True, None), (False, None)]:
        sources, seen = _run(monkeypatch, enabled=enabled, key=key)
        assert sources == ["template"] and seen == {}, (enabled, key)

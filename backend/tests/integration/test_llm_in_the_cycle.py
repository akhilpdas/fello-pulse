"""T280 / T282 / T284 / T286 (FR-025..FR-029, SC-009..SC-011): the model inside a real cycle.

* a good reply becomes the draft, with the model and the grounding facts recorded;
* every way the model can fail -- or be wrong -- falls back to the template, the cycle still succeeds, and the run
  record says how many drafts fell back and why;
* calls are bounded and a dead provider trips a breaker;
* **ranking is byte-identical** whether the model is off, on, or failing (constitution II).

Names the production change that makes it fail: ``run_cycle`` building facts, calling an ``LlmDrafter`` (injected
via ``llm_factory``) and recording ``draft_model`` / ``draft_fallback_reason``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from pulse.agent.cycle import run_cycle
from pulse.agent.llm_drafter import LlmDrafter
from pulse.agent.transport import RecordingTransport
from pulse.db.session import owner_session, tenant_session
from tests.integration._agent_fixtures import seed_account, seed_tenant, toy_support_model

AS_OF = datetime(2026, 7, 8, 9, 0, tzinfo=UTC)


class Scripted:
    def __init__(self, reply=None, raises=None, fn=None):
        self.reply, self.raises, self.fn, self.calls = reply, raises, fn, 0

    def complete(self, system, user, *, model, max_tokens, timeout):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.fn(user) if self.fn else self.reply


def _grounded_reply(user: str) -> str:
    """A model that does what it is told: states only the facts it was given."""
    doc = json.loads(user)
    return json.dumps({"subject": "Following up", "claims": doc["allowed_claims"][:1],
                       "body": f"Hi {doc['account_name']} team, " + "; ".join(doc["facts"]) + f". Best, {doc['csm_name']}"})


def _world(n_accounts=1, slug="llm"):
    tenant_id, cfg = seed_tenant(AS_OF)
    with owner_session() as s:
        for i in range(n_accounts):
            seed_account(s, tenant_id, AS_OF, f"{slug}-{i}", n_tickets=15)
    return tenant_id, cfg


def _run(tenant_id, cfg, client=None, **kw):
    factory = (lambda: LlmDrafter(client, model="claude-sonnet-5-5", max_calls=kw.pop("max_calls", 50), timeout=5.0,
                                  breaker_threshold=kw.pop("breaker", 3))) if client is not None else None
    with tenant_session(tenant_id) as s:
        return run_cycle(s, tenant_id=tenant_id, model=toy_support_model(13), model_version="t",
                         tenant_config=cfg, as_of=AS_OF, transport=RecordingTransport(), llm_factory=factory)


def _actions(run_id):
    with owner_session() as s:
        return s.execute(text("SELECT draft_source, draft_model, draft_fallback_reason, subject, body, grounding"
                              " FROM action WHERE agent_run_id = :r ORDER BY created_at"), {"r": run_id}).mappings().all()


def test_a_grounded_reply_becomes_the_draft_with_the_model_and_facts_recorded():
    tenant_id, cfg = _world()
    result = _run(tenant_id, cfg, Scripted(fn=_grounded_reply))
    (a,) = _actions(result.run_id)
    assert (a["draft_source"], a["draft_model"], a["draft_fallback_reason"]) == ("llm", "claude-sonnet-5-5", None)
    assert a["grounding"]["facts"], "the facts the model was given are stored with the action"
    assert any("support ticket" in f for f in a["grounding"]["facts"])
    assert result.stage_counts["llm_drafted"] == 1 and result.stage_counts["llm_fallbacks"] == 0


def test_a_model_that_invents_a_fact_is_rejected_and_the_template_is_used():
    tenant_id, cfg = _world()
    bad = json.dumps({"subject": "Hello", "claims": ["support_experience"],
                      "body": "Hi, we saw 999 tickets and are offering you a 50 percent discount."})
    result = _run(tenant_id, cfg, Scripted(reply=bad))
    (a,) = _actions(result.run_id)
    assert (a["draft_source"], a["draft_model"]) == ("template", None)
    assert a["draft_fallback_reason"].startswith("invalid:unsupported_number:")  # 50 and 999 are both invented
    assert result.stage_counts["llm_fallbacks"] == 1


def test_every_provider_failure_falls_back_and_the_cycle_still_succeeds():
    for client, reason in [(Scripted(raises=RuntimeError("boom")), "provider_error:RuntimeError"),
                           (Scripted(raises=TimeoutError()), "timeout"),
                           (Scripted(reply=""), "empty_reply"),
                           (Scripted(reply="not json at all"), "unparseable_reply")]:
        tenant_id, cfg = _world()
        result = _run(tenant_id, cfg, client)
        (a,) = _actions(result.run_id)
        assert a["draft_source"] == "template" and a["draft_fallback_reason"] == reason, reason
        with owner_session() as s:
            assert s.execute(text("SELECT status FROM agent_run WHERE id = :r"), {"r": result.run_id}).scalar() == "succeeded"


def test_calls_are_bounded_and_the_rest_get_templates():
    tenant_id, cfg = _world(n_accounts=4)
    client = Scripted(fn=_grounded_reply)
    result = _run(tenant_id, cfg, client, max_calls=2)
    sources = [a["draft_source"] for a in _actions(result.run_id)]
    assert client.calls == 2 and sorted(sources) == ["llm", "llm", "template", "template"]
    assert {a["draft_fallback_reason"] for a in _actions(result.run_id)} == {None, "budget_exhausted"}


def test_a_dead_provider_trips_the_breaker_so_it_is_not_called_for_every_account():
    tenant_id, cfg = _world(n_accounts=6)
    client = Scripted(raises=RuntimeError("down"))
    result = _run(tenant_id, cfg, client, breaker=2)
    assert client.calls == 2, "after two consecutive failures the breaker opens and the provider is left alone"
    reasons = [a["draft_fallback_reason"] for a in _actions(result.run_id)]
    assert reasons.count("circuit_open") == 4 and all(r for r in reasons)


def _scores(tenant_id):
    with owner_session() as s:
        return s.execute(text("SELECT a.external_ref, sc.probability, sc.tier, sc.priority, sc.dominant_driver"
                              " FROM score sc JOIN account a ON a.id = sc.account_id WHERE sc.tenant_id = :t"
                              " ORDER BY a.external_ref"), {"t": tenant_id}).all()


def test_ranking_is_identical_with_the_model_off_on_or_failing():
    outcomes = {}
    for label, client in [("off", None), ("on", Scripted(fn=_grounded_reply)), ("failing", Scripted(raises=RuntimeError("x")))]:
        tenant_id, cfg = _world(n_accounts=3, slug="inv")  # identical data every time
        _run(tenant_id, cfg, client)
        outcomes[label] = [row[1:] for row in _scores(tenant_id)]  # drop the (unique) external_ref
    assert outcomes["off"] == outcomes["on"] == outcomes["failing"] and len(outcomes["off"]) == 3

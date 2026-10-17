"""A second language-model provider: any server that speaks the OpenAI-style ``/chat/completions`` protocol (Ollama,
LM Studio, Groq, OpenRouter, Google's Gemini endpoint, ...). It exists so the demo can run on a free or local model with
no Anthropic key, and so switching to Anthropic later is one setting. Every guardrail is the same: the drafter, the
grounding validator, the call budget and the breaker do not know which provider is behind ``LlmClient``.

Names the production change that makes these fail: ``llm_drafter.OpenAICompatibleClient`` and the ``llm_provider`` /
``llm_base_url`` settings that select it.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pulse.agent import llm_drafter
from pulse.agent.llm_drafter import LlmDrafter, LlmUnavailable, OpenAICompatibleClient, build_llm_drafter


class _Server:
    """A real local HTTP server (so a real request goes over a real socket) that records what it was sent."""

    def __init__(self, status=200, body=None, delay=0.0):
        outer = self
        self.requests, self.status, self.body, self.delay = [], status, body, delay

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "json": json.loads(raw)})
                time.sleep(outer.delay)
                payload = json.dumps(outer.body if outer.body is not None else
                                     {"choices": [{"message": {"content": "hello from the model"}}]}).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):  # silence
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    made = []

    def make(**kw):
        made.append(_Server(**kw))
        return made[-1]

    yield make
    for s in made:
        s.close()


def test_sends_the_prompt_to_chat_completions_and_returns_the_reply_text(server):
    s = server()
    out = OpenAICompatibleClient(s.url, api_key="k-123").complete(
        "SYSTEM TEXT", '{"facts": []}', model="llama3.2", max_tokens=321, timeout=5)
    assert out == "hello from the model"
    r = s.requests[0]
    assert r["path"] == "/v1/chat/completions"
    assert r["json"]["model"] == "llama3.2" and r["json"]["max_tokens"] == 321
    assert r["json"]["messages"] == [{"role": "system", "content": "SYSTEM TEXT"},
                                     {"role": "user", "content": '{"facts": []}'}]
    assert r["json"]["temperature"] <= 0.3  # low, so a small model follows the output format


def test_sends_the_key_as_a_bearer_token_when_there_is_one_and_nothing_when_there_is_not(server):
    s = server()
    OpenAICompatibleClient(s.url, api_key="k-123").complete("s", "u", model="m", max_tokens=5, timeout=5)
    OpenAICompatibleClient(s.url, api_key=None).complete("s", "u", model="m", max_tokens=5, timeout=5)
    assert s.requests[0]["headers"]["Authorization"] == "Bearer k-123"
    assert "Authorization" not in s.requests[1]["headers"]  # a local model needs no key


def test_a_trailing_slash_on_the_base_url_is_harmless(server):
    s = server()
    OpenAICompatibleClient(s.url + "/", api_key=None).complete("s", "u", model="m", max_tokens=5, timeout=5)
    assert s.requests[0]["path"] == "/v1/chat/completions"


def test_a_provider_error_status_raises_so_the_drafter_falls_back(server):
    s = server(status=500, body={"error": "boom"})
    with pytest.raises(Exception):  # noqa: B017,PT011 - any exception is "the provider failed"
        OpenAICompatibleClient(s.url, api_key=None).complete("s", "u", model="m", max_tokens=5, timeout=5)


def test_a_reply_without_choices_raises(server):
    s = server(body={"unexpected": True})
    with pytest.raises(Exception):  # noqa: B017,PT011
        OpenAICompatibleClient(s.url, api_key=None).complete("s", "u", model="m", max_tokens=5, timeout=5)


def test_a_slow_provider_times_out_and_the_drafter_reports_a_timeout(server):
    s = server(delay=1.5)
    drafter = LlmDrafter(OpenAICompatibleClient(s.url, api_key=None), model="m", max_calls=5, timeout=0.3)
    draft, reason = drafter.draft("adoption_nudge", account_name="Acme", csm_name="Dana", facts=["Usage fell."])
    assert draft is None and reason == "timeout"


def test_a_dead_server_is_a_provider_error_not_a_crash():
    drafter = LlmDrafter(OpenAICompatibleClient("http://127.0.0.1:9/v1", api_key=None), model="m", max_calls=5, timeout=1)
    draft, reason = drafter.draft("adoption_nudge", account_name="Acme", csm_name="Dana", facts=["Usage fell."])
    assert draft is None and reason.startswith("provider_error:")


def test_only_http_and_https_urls_are_accepted():
    for bad in ("file:///etc/passwd", "ftp://x/v1", "localhost:11434/v1", ""):
        with pytest.raises(LlmUnavailable):
            OpenAICompatibleClient(bad, api_key=None)


def test_the_client_never_prints_its_key():
    assert "secret-key" not in repr(OpenAICompatibleClient("http://127.0.0.1:1/v1", api_key="secret-key"))


def test_build_selects_the_provider_and_rejects_what_it_cannot_build():
    d = build_llm_drafter("", model="m", max_calls=3, provider="openai_compatible", base_url="http://127.0.0.1:1/v1")
    assert isinstance(d.client, OpenAICompatibleClient)
    with pytest.raises(LlmUnavailable):
        build_llm_drafter("", model="m", max_calls=3, provider="openai_compatible", base_url=None)
    with pytest.raises(LlmUnavailable):
        build_llm_drafter("k", model="m", max_calls=3, provider="carrier-pigeon", base_url=None)


def test_the_provider_is_not_loaded_unless_enabled():
    import pulse.agent.cycle as cycle

    assert "llm_drafter" not in vars(cycle)  # still only ever imported lazily, inside the enabled branch
    assert hasattr(llm_drafter, "OpenAICompatibleClient")

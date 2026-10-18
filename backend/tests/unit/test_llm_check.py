"""``pulse llm-check``: one real, minimal call through the configured provider (spec 003, T026).

It answers "does my key work, how fast is it, and what are my limits?" in a few seconds, before a whole cycle is spent
finding out. A real local HTTP server stands in for the provider so a real request crosses a real socket.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pulse.llm_check import check_llm


class _Provider:
    def __init__(self, status=200, body=None, headers=None, delay=0.0):
        outer = self
        self.seen = []

        class H(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.seen.append({"auth": self.headers.get("Authorization"), "agent": self.headers.get("User-Agent"), "json": json.loads(raw)})
                time.sleep(delay)
                payload = json.dumps(body if body is not None else {"choices": [{"message": {"content": "pong"}}]}).encode()
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


@pytest.fixture
def provider():
    made = []

    def make(**kw):
        made.append(_Provider(**kw)); return made[-1]
    yield make
    for m in made:
        m.close()


def _check(url, key="k", timeout=5.0):
    return check_llm(provider="openai_compatible", base_url=url, model="m", api_key=key, timeout=timeout)


def test_a_working_provider_reports_ok_with_its_reply_and_how_long_it_took(provider):
    p = provider()
    r = _check(p.url)
    assert r.ok and r.kind == "ok" and r.reply == "pong" and r.latency_ms >= 0
    assert p.seen[0]["auth"] == "Bearer k" and p.seen[0]["json"]["model"] == "m"


def test_the_providers_rate_limit_headers_are_reported_as_observed_not_assumed(provider):
    p = provider(headers={"x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "998",
                          "x-ratelimit-limit-tokens": "12000", "x-ratelimit-remaining-tokens": "11980"})
    r = _check(p.url)
    assert r.limits == {"limit-requests": "1000", "remaining-requests": "998",
                        "limit-tokens": "12000", "remaining-tokens": "11980"}


def test_a_provider_that_sends_no_limit_headers_gives_an_empty_report(provider):
    assert _check(provider().url).limits == {}


def test_a_rejected_key_is_named_as_such(provider):
    r = _check(provider(status=401, body={"error": {"message": "Invalid API Key"}}).url)
    assert not r.ok and r.kind == "unauthorized"


def test_a_provider_that_is_too_slow_is_a_timeout(provider):
    r = _check(provider(delay=2.0).url, timeout=0.5)
    assert not r.ok and r.kind == "timeout"


def test_nothing_listening_is_unreachable_not_a_crash():
    r = _check("http://127.0.0.1:9/v1")
    assert not r.ok and r.kind == "unreachable"


def test_a_reply_that_is_not_a_chat_completion_is_a_bad_reply(provider):
    r = _check(provider(body={"unexpected": True}).url)
    assert not r.ok and r.kind == "bad_reply"


def test_a_hosted_provider_without_a_key_is_refused_before_any_call(provider):
    p = provider()
    r = check_llm(provider="openai_compatible", base_url="https://api.groq.com/openai/v1", model="m", api_key=None, timeout=5)
    assert not r.ok and r.kind == "no_key" and p.seen == []


def test_a_local_model_needs_no_key(provider):
    assert _check(provider().url, key=None).ok


def test_the_check_identifies_itself_instead_of_sending_pythons_default_user_agent(provider):
    # Found live: Groq (behind Cloudflare) answers "Python-urllib/3.x" with HTTP 403 (error 1010) -- a good key reported as rejected.
    p = provider()
    assert _check(p.url).ok
    assert p.seen[0]["agent"].startswith("fello-pulse/") and "urllib" not in p.seen[0]["agent"].lower()

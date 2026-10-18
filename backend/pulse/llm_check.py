"""``pulse llm-check``: one real, minimal call through the configured provider (spec 003).

Answers "does my key work, how fast is it, and what are my limits?" in seconds -- before a whole cycle is spent finding
out. For OpenAI-style providers (Ollama, Groq, ...) it also reports the rate-limit headers the provider actually sent, so
limits are *observed*, not taken from a blog post. Nothing here ranks or decides anything: it is a connectivity probe.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
_LIMIT_HEADERS = ("limit-requests", "remaining-requests", "limit-tokens", "remaining-tokens",
                  "reset-requests", "reset-tokens")


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    kind: str                     # ok | no_key | unauthorized | rate_limited | timeout | unreachable | bad_reply | http_error | error
    provider: str
    model: str
    latency_ms: int = 0
    reply: str = ""
    limits: dict = field(default_factory=dict)
    detail: str = ""


def _fail(kind, provider, model, detail="", started=None, limits=None):
    ms = int((time.monotonic() - started) * 1000) if started else 0
    return CheckResult(False, kind, provider, model, ms, "", limits or {}, detail)


def check_llm(*, provider: str, base_url: str | None, model: str, api_key: str | None, timeout: float) -> CheckResult:
    if provider == "anthropic":
        return _check_anthropic(model, api_key, timeout)
    if provider != "openai_compatible":
        return _fail("error", provider, model, f"unknown provider {provider!r} (use 'anthropic' or 'openai_compatible')")
    if not base_url:
        return _fail("error", provider, model, "PULSE_LLM_BASE_URL is not set")
    host = urlsplit(base_url).hostname or ""
    if not api_key and host not in _LOCAL_HOSTS:
        return _fail("no_key", provider, model, f"{host} is a hosted provider and needs PULSE_LLM_API_KEY (free keys exist)")

    body = json.dumps({"model": model, "max_tokens": 8, "temperature": 0,
                       "messages": [{"role": "user", "content": "Reply with the single word: pong"}]}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - the operator's own configured URL
            raw, got = resp.read(), resp.headers
    except urllib.error.HTTPError as exc:
        limits = _limits(exc.headers)
        if exc.code in (401, 403):
            return _fail("unauthorized", provider, model, f"HTTP {exc.code}: the provider rejected the key", started, limits)
        if exc.code == 429:
            return _fail("rate_limited", provider, model, "HTTP 429: the free limit is used up", started, limits)
        return _fail("http_error", provider, model, f"HTTP {exc.code}", started, limits)
    except (TimeoutError, socket.timeout):
        return _fail("timeout", provider, model, f"no answer within {timeout:g}s", started)
    except urllib.error.URLError as exc:
        kind = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "unreachable"
        return _fail(kind, provider, model, str(exc.reason), started)
    latency = int((time.monotonic() - started) * 1000)
    try:
        reply = json.loads(raw)["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError):
        return _fail("bad_reply", provider, model, "the reply is not a chat completion", started, _limits(got))
    return CheckResult(True, "ok", provider, model, latency, reply.strip(), _limits(got))


def _limits(headers) -> dict:
    out = {}
    for name in _LIMIT_HEADERS:
        value = headers.get(f"x-ratelimit-{name}") if headers is not None else None
        if value is not None:
            out[name] = value
    retry = headers.get("retry-after") if headers is not None else None
    if retry is not None:
        out["retry-after"] = retry
    return out


def _check_anthropic(model: str, api_key: str | None, timeout: float) -> CheckResult:
    if not api_key:
        return _fail("no_key", "anthropic", model, "PULSE_LLM_API_KEY is not set")
    started = time.monotonic()
    try:
        from pulse.agent.llm_drafter import AnthropicClient
        reply = AnthropicClient(api_key).complete("Answer in one word.", "Reply with the single word: pong",
                                                  model=model, max_tokens=8, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - any failure of the SDK is reported, not raised
        return _fail("error", "anthropic", model, f"{type(exc).__name__}: {exc}", started)
    return CheckResult(True, "ok", "anthropic", model, int((time.monotonic() - started) * 1000), reply.strip())

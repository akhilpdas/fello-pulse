"""Outbound dispatch (T064; 002 US2). A ``Transport`` sends one message and says exactly how it
went. ``RecordingTransport`` never touches a network and is the default for tests and the demo;
``SmtpTransport`` is the real thing, used only when SMTP is configured **and** the tenant has switched
outbound email on (see ``select_transport``).

Outcomes are classified because the right response differs:

``transient``  the message was definitely not accepted and trying again may work (connection refused,
               a 4xx reply) -- retried, bounded.
``permanent``  definitely not accepted and trying again cannot work (a 5xx reply) -- not retried.
``ambiguous``  the body was sent and no answer came back, so the provider may or may not have accepted
               it. **Never retried**: a second send risks a second email to a customer. It surfaces to a
               human (FR-018).
"""

from __future__ import annotations

import smtplib
import socket
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SendResult:
    ok: bool
    error: str | None = None
    kind: str = "ok"  # ok | transient | permanent | ambiguous
    provider_message_id: str | None = None


class Transport(Protocol):
    def send(
        self, *, to: str, subject: str, body: str, sender: str | None = None, message_id: str | None = None,
    ) -> SendResult: ...


def send_with_retry(
    transport: Transport, *, to: str, subject: str, body: str, sender: str | None = None,
    message_id: str | None = None, max_attempts: int = 3,
) -> tuple[SendResult, int]:
    """Bounded retry for a human-triggered send (T076): try up to
    ``max_attempts`` times, stop on the first success, and return the final
    result plus how many attempts it took -- the caller surfaces a final
    failure rather than swallowing it."""
    attempts = 0
    result = SendResult(False, "never attempted", kind="permanent")
    for _ in range(max_attempts):
        attempts += 1
        result = transport.send(to=to, subject=subject, body=body, sender=sender, message_id=message_id)
        # Only a *definite* non-delivery is retried. A permanent refusal cannot succeed, and an ambiguous
        # outcome must not be retried: the first attempt may already have been delivered.
        if result.ok or result.kind != "transient":
            break
    return result, attempts


@dataclass
class RecordingTransport:
    sent: list[dict] = field(default_factory=list)
    # Test hook: the next N calls fail before sends succeed again --
    # exercises T076's bounded retry without a real flaky network.
    fail_next: int = 0

    def send(
        self, *, to: str, subject: str, body: str, sender: str | None = None, message_id: str | None = None,
    ) -> SendResult:
        if self.fail_next > 0:
            self.fail_next -= 1
            return SendResult(False, "simulated_transport_failure", kind="transient")
        self.sent.append({"to": to, "subject": subject, "body": body, "sender": sender, "message_id": message_id})
        return SendResult(True, None)


class SmtpTransport:
    """Authenticated SMTP submission using only the standard library. Credentials come from the
    deployment's environment (``Settings``), never from the database or the repository, and never appear
    in ``repr``."""

    def __init__(
        self, host: str, port: int = 587, *, user: str | None = None, password: str | None = None,
        starttls: bool = True, timeout: float = 15.0,
    ) -> None:
        self.host, self.port, self.user, self.starttls, self.timeout = host, port, user, starttls, timeout
        self._password = password

    @classmethod
    def from_settings(cls, s) -> SmtpTransport:
        return cls(
            s.smtp_host, s.smtp_port, user=s.smtp_user,
            password=s.smtp_password.get_secret_value() if s.smtp_password else None, starttls=s.smtp_starttls,
            timeout=s.smtp_timeout,
        )

    def __repr__(self) -> str:
        return f"SmtpTransport(host={self.host!r}, port={self.port}, user={self.user!r}, starttls={self.starttls})"

    def send(
        self, *, to: str, subject: str, body: str, sender: str | None = None, message_id: str | None = None,
    ) -> SendResult:
        sender = sender or self.user
        if not sender:
            return SendResult(False, "no sender address configured", kind="permanent")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, to, subject
        if message_id:
            msg["Message-ID"] = message_id
        msg.set_content(body)

        smtp = None
        stage = "connect"
        try:
            smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            smtp.ehlo()
            if self.starttls:
                smtp.starttls()
                smtp.ehlo()
            if self.user and self._password:
                smtp.login(self.user, self._password)
            code, resp = smtp.mail(sender)
            if code >= 400:
                return self._by_code(code, resp)
            code, resp = smtp.rcpt(to)
            if code >= 400:
                return self._by_code(code, resp)
            stage = "data"  # from here a lost answer cannot be told apart from a lost message
            code, resp = smtp.data(msg.as_bytes())
            text = resp.decode(errors="replace") if isinstance(resp, bytes) else str(resp)
            return SendResult(True, None, provider_message_id=text.split()[-1] if text.split() else None)
        except smtplib.SMTPDataError as exc:  # the server answered the body with a refusal: definite
            return self._by_code(exc.smtp_code, exc.smtp_error)
        except smtplib.SMTPResponseException as exc:  # includes SMTPConnectError (e.g. 421 at greeting)
            return self._by_code(exc.smtp_code, exc.smtp_error)
        except (smtplib.SMTPServerDisconnected, socket.timeout) as exc:
            return SendResult(False, f"{type(exc).__name__}: {exc}", kind="ambiguous" if stage == "data" else "transient")
        except smtplib.SMTPException as exc:
            # Credentials offered to a server with no AUTH, a refused login, every recipient refused: a
            # configuration or address problem that retrying cannot fix. (SMTPException subclasses OSError,
            # so this must come before the network-error clause or it would be retried as "transient".)
            return SendResult(False, f"{type(exc).__name__}: {exc}", kind="permanent")
        except OSError as exc:
            return SendResult(False, f"{type(exc).__name__}: {exc}", kind="ambiguous" if stage == "data" else "transient")
        finally:
            if smtp is not None:
                try:
                    smtp.close()
                except Exception:  # noqa: BLE001 - closing a broken connection must not mask the result
                    pass

    @staticmethod
    def _by_code(code: int, resp) -> SendResult:
        text = resp.decode(errors="replace") if isinstance(resp, bytes) else str(resp)
        return SendResult(False, f"{code} {text}", kind="permanent" if code >= 500 else "transient")


def select_transport(settings) -> Transport:
    """Real SMTP when the deployment has a mail host configured, otherwise the recording stub -- so the
    system is fully functional with nothing configured. Whether a given tenant may actually send is a
    separate question, answered by ``pulse.domain.send_gate``."""
    if settings.smtp_host:
        return SmtpTransport.from_settings(settings)
    return RecordingTransport()

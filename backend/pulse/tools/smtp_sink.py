"""A tiny SMTP server that keeps what it is sent -- and can be told to misbehave.

Two uses: the test double for ``SmtpTransport`` (Python 3.12+ removed ``smtpd``), and the **demo mail
sink**: run it, point ``PULSE_SMTP_HOST``/``PULSE_SMTP_PORT`` at it, and approve a draft to watch a real
SMTP conversation land somewhere harmless. It speaks just enough SMTP for ``smtplib`` and never relays.

    python3 -m pulse.tools.smtp_sink            # listen on 127.0.0.1:1025 and print each message

Failure modes (``mode=``): ``ok``, ``reject_rcpt`` (550), ``tempfail_rcpt`` (451, the first
``fail_first`` recipients, or all if 0), ``greet_421`` (service unavailable), ``hang_after_data`` (accept the
body, never answer -- the genuinely ambiguous case).
"""

from __future__ import annotations

import socketserver
import threading
import time


class _Handler(socketserver.StreamRequestHandler):
    server: _Server

    def _say(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        sink = self.server.sink
        sink.connections += 1
        if sink.mode == "greet_421":
            return self._say("421 4.3.2 service not available")
        self._say("220 pulse-sink ESMTP")
        mail_from, rcpts = None, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").strip()
            cmd = line.upper()
            if cmd.startswith("EHLO"):
                self.wfile.write(b"250-pulse-sink\r\n250 SIZE 10485760\r\n")
                self.wfile.flush()
            elif cmd.startswith("HELO") or cmd.startswith(("RSET", "NOOP")):
                self._say("250 ok")
            elif cmd.startswith("MAIL FROM:"):
                mail_from, rcpts = line[10:].strip().strip("<>"), []
                self._say("250 2.1.0 ok")
            elif cmd.startswith("RCPT TO:"):
                sink.rcpt_attempts += 1
                if sink.mode == "reject_rcpt":
                    self._say("550 5.1.1 no such user")
                elif sink.mode == "tempfail_rcpt" and (sink.fail_first == 0 or sink.rcpt_attempts <= sink.fail_first):
                    self._say("451 4.3.0 try again later")
                else:
                    rcpts.append(line[8:].strip().strip("<>"))
                    self._say("250 2.1.5 ok")
            elif cmd == "DATA":
                self._say("354 end data with <CR><LF>.<CR><LF>")
                lines = []
                while True:
                    part = self.rfile.readline()
                    if not part or part.rstrip(b"\r\n") == b".":
                        break
                    text = part.decode(errors="replace")
                    lines.append(text[1:] if text.startswith("..") else text)  # undo dot-stuffing
                sink.data_attempts += 1
                if sink.mode == "hang_after_data":
                    time.sleep(5)  # the client's timeout fires first; it cannot know what happened
                    return
                sink.messages.append({"mail_from": mail_from, "rcpt_to": rcpts, "data": "".join(lines)})
                self._say(f"250 2.0.0 queued as SINK{len(sink.messages)}")
            elif cmd == "QUIT":
                return self._say("221 bye")
            else:
                self._say("502 command not implemented")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    sink: SmtpSink


class SmtpSink:
    def __init__(self, mode: str = "ok", fail_first: int = 0, host: str = "127.0.0.1", port: int = 0) -> None:
        self.mode, self.fail_first = mode, fail_first
        self.messages: list[dict] = []
        self.connections = self.rcpt_attempts = self.data_attempts = 0
        self._server = _Server((host, port), _Handler)
        self._server.sink = self
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> SmtpSink:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._server.shutdown()
        self._server.server_close()


if __name__ == "__main__":  # pragma: no cover - the demo mail sink
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1025
    with SmtpSink(port=port) as sink:
        print(f"pulse mail sink listening on 127.0.0.1:{sink.port} (Ctrl-C to stop)", flush=True)
        seen = 0
        try:
            while True:
                time.sleep(0.5)
                while seen < len(sink.messages):
                    m = sink.messages[seen]
                    seen += 1
                    print(f"\n--- message {seen}: {m['mail_from']} -> {', '.join(m['rcpt_to'])}\n{m['data']}", flush=True)
        except KeyboardInterrupt:
            pass

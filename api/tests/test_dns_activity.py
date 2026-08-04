"""Tests for api/dns_activity.py's CoreDNS log parsing.

A real production incident: the local WireGuard CoreDNS instance never had
the `log` plugin enabled (see config/wireguard-coredns/Corefile), so real
peer queries were never logged in the first place. What *was* getting
captured and stored as if it were a real query was the `loop` plugin's
canary probe (two large random numbers, e.g.
"4148863610893235485.505215156570136642") - it happens to loosely match
the same log-line shape _LOG_LINE_RE expects for a real query. This spins
up a fake HTTP server that mimics Docker's `/containers/{id}/logs` API
(multiplexed stream framing + timestamps) to exercise _poll_container end
to end without needing a real Docker socket.

Uses asyncio.get_event_loop().run_until_complete(), matching every other
async helper in test_oracle_region.py, rather than @pytest.mark.asyncio -
pulling in pytest-asyncio's per-test event loop management poisons the
main thread's default event loop policy for every *other* file in this
suite that relies on that same get_event_loop() pattern, since it's a
process-wide asyncio policy state, not scoped to one test file.
"""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import dns_activity


def _frame(line: str) -> bytes:
    """One frame of Docker's multiplexed log stream: 1-byte stream type
    (1 = stdout), 3 reserved zero bytes, 4-byte big-endian length, payload."""
    payload = line.encode()
    header = bytes([1, 0, 0, 0]) + len(payload).to_bytes(4, "big")
    return header + payload


class _FakeDockerLogsHandler(BaseHTTPRequestHandler):
    body = b""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.docker.raw-stream")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)


@pytest.fixture()
def fake_docker_logs(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FakeDockerLogsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(dns_activity, "DOCKER_LOG_PROXY_URL", f"http://127.0.0.1:{server.server_port}")
    dns_activity._last_since_epoch.clear()
    try:
        yield _FakeDockerLogsHandler
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_real_query_line_is_parsed(fake_docker_logs):
    ts = "2026-08-04T15:40:39.860915000Z"
    real_line = '[INFO] 10.13.13.4:51234 - 12345 "A IN example.com. udp 512 false 4096" NOERROR qr,aa,rd 100 0.000123456s'
    fake_docker_logs.body = _frame(f"{ts} {real_line}\n")

    entries = asyncio.get_event_loop().run_until_complete(dns_activity._poll_container("fake-container"))
    assert len(entries) == 1
    _dt, ip, domain = entries[0]
    assert ip == "10.13.13.4"
    assert domain == "example.com"


def test_loop_plugin_canary_is_not_mistaken_for_a_real_query(fake_docker_logs):
    """The exact bug found in production: a `loop` plugin canary probe
    (all-digits "domain", source 127.0.0.1) must never be stored as a
    real DNS query."""
    ts = "2026-08-04T15:40:39.860915000Z"
    canary_line = (
        '[INFO] 127.0.0.1:57891 - 12345 '
        '"HINFO CH 4148863610893235485.505215156570136642. udp 512 false 4096" '
        'NOERROR qr,rd,ra 96 0.000073s'
    )
    fake_docker_logs.body = _frame(f"{ts} {canary_line}\n")

    entries = asyncio.get_event_loop().run_until_complete(dns_activity._poll_container("fake-container"))
    assert entries == []


def test_mixed_stream_keeps_only_the_real_query(fake_docker_logs):
    ts1 = "2026-08-04T15:40:39.860915000Z"
    ts2 = "2026-08-04T15:40:40.100000000Z"
    canary_line = (
        '[INFO] 127.0.0.1:57891 - 12345 '
        '"HINFO CH 3178195700335953380.4266553555614082993. udp 512 false 4096" '
        'NOERROR qr,rd,ra 96 0.000073s'
    )
    real_line = '[INFO] 10.13.13.5:41000 - 999 "AAAA IN anthropic.com. udp 512 false 4096" NOERROR qr,aa,rd 88 0.00009s'
    fake_docker_logs.body = _frame(f"{ts1} {canary_line}\n") + _frame(f"{ts2} {real_line}\n")

    entries = asyncio.get_event_loop().run_until_complete(dns_activity._poll_container("fake-container"))
    assert len(entries) == 1
    assert entries[0][1] == "10.13.13.5"
    assert entries[0][2] == "anthropic.com"

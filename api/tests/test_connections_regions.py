"""Tests for the region-aware /api/system/connections fan-out.

Monitoring's "Active Connections" table previously only ever queried the
local WireGuard server, so a remote-region peer (e.g. an Oracle-provisioned
instance) could be genuinely connected and never show up there, even though
it was listed correctly (with its region tag) on the WireGuard Peers page.
This mirrors test_wireguard_peer_regions.py's fake-agent pattern, but the
fake agent also serves /peers/stats (real handshake/traffic data), matching
the new route added to region-agent/agent.py.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _FakeStatsAgentHandler(BaseHTTPRequestHandler):
    # Class-level so the fixture can set it per-test before the server starts.
    stats = []

    def log_message(self, format, *args):
        pass

    def _send_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "healthy", "wireguard_status": "running", "peer_count": len(self.stats)})
        elif self.path == "/peers/stats":
            self._send_json(200, self.stats)
        else:
            self._send_json(404, {"detail": "not found"})

    def do_DELETE(self):
        name = self.path.split("/")[2]
        self.stats[:] = [p for p in self.stats if p["name"] != name]  # mutate the shared class-level list in place
        self._send_json(200, {"message": f"Peer {name} deleted successfully"})


@pytest.fixture()
def fake_stats_agent():
    _FakeStatsAgentHandler.stats = []
    server = HTTPServer(("127.0.0.1", 0), _FakeStatsAgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def registered_stats_region(client, admin_headers, fake_stats_agent):
    _server, url = fake_stats_agent
    resp = client.post(
        "/regions",
        json={
            "slug": "stats-test-region",
            "display_name": "Stats Test Region",
            "country_code": "de",
            "agent_url": url,
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.40",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    region_id = resp.json()["id"]
    yield "stats-test-region"
    client.delete(f"/regions/{region_id}", headers=admin_headers)


def test_connected_remote_peer_appears_in_active_connections(client, admin_headers, registered_stats_region):
    _FakeStatsAgentHandler.stats = [{
        "public_key": "fakepub",
        "name": "orc1",
        "ip": "10.13.13.5",
        "latest_handshake": int(time.time()),
        "rx_bytes": 1024 * 1024,
        "tx_bytes": 2 * 1024 * 1024,
    }]

    resp = client.get("/api/system/connections", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    conns = resp.json()
    remote = [c for c in conns if c["id"] == f"{registered_stats_region}:orc1"]
    assert len(remote) == 1
    assert remote[0]["protocol"] == "WireGuard"
    assert remote[0]["ip_address"] == "10.13.13.5"
    assert "Stats Test Region" in remote[0]["username"]


def test_stale_remote_peer_excluded_from_active_connections(client, admin_headers, registered_stats_region):
    """A peer with no recent handshake (>=180s) is provisioned but not
    currently connected, and must not be reported as an active connection -
    matches the exact freshness window already used for local peers."""
    _FakeStatsAgentHandler.stats = [{
        "public_key": "fakepub",
        "name": "old1",
        "ip": "10.13.13.6",
        "latest_handshake": int(time.time()) - 3600,
        "rx_bytes": 0,
        "tx_bytes": 0,
    }]

    resp = client.get("/api/system/connections", headers=admin_headers)
    assert resp.status_code == 200
    assert all(c["id"] != f"{registered_stats_region}:old1" for c in resp.json())


def test_connections_degrade_gracefully_when_region_unreachable(client, admin_headers, fake_stats_agent):
    server, url = fake_stats_agent
    resp = client.post(
        "/regions",
        json={
            "slug": "flaky-stats-region",
            "display_name": "Flaky Stats Region",
            "country_code": "jp",
            "agent_url": url,
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.50",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    region_id = resp.json()["id"]

    server.shutdown()

    conn_resp = client.get("/api/system/connections", headers=admin_headers)
    assert conn_resp.status_code == 200

    client.delete(f"/regions/{region_id}", headers=admin_headers)


def test_disconnect_remote_connection_routes_to_region_agent(client, admin_headers, registered_stats_region):
    _FakeStatsAgentHandler.stats = [{
        "public_key": "fakepub",
        "name": "rmv1",
        "ip": "10.13.13.7",
        "latest_handshake": int(time.time()),
        "rx_bytes": 0,
        "tx_bytes": 0,
    }]

    resp = client.delete(f"/api/system/connections/{registered_stats_region}:rmv1", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert _FakeStatsAgentHandler.stats == []


def test_vpn_performance_widget_counts_remote_peers(client, admin_headers, registered_stats_region):
    """/api/system/resources feeds the Monitoring page's "VPN Performance"
    card - same gap as /api/system/connections had, different endpoint: a
    connected remote-region peer must count toward the wireguard
    connections/transfer figures, not just show as 0/Inactive."""
    _FakeStatsAgentHandler.stats = [{
        "public_key": "fakepub",
        "name": "prf1",
        "ip": "10.13.13.9",
        "latest_handshake": int(time.time()),
        "rx_bytes": 5 * 1024 * 1024,
        "tx_bytes": 3 * 1024 * 1024,
    }]

    resp = client.get("/api/system/resources", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    wg = resp.json()["vpn"]["wireguard"]
    assert wg["connections"] >= 1
    assert wg["active"] is True
    assert wg["transfer"] >= 8.0


def test_vpn_performance_widget_degrades_gracefully_when_region_unreachable(client, admin_headers, fake_stats_agent):
    server, url = fake_stats_agent
    resp = client.post(
        "/regions",
        json={
            "slug": "flaky-perf-region",
            "display_name": "Flaky Perf Region",
            "country_code": "jp",
            "agent_url": url,
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.60",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    region_id = resp.json()["id"]

    server.shutdown()

    resources_resp = client.get("/api/system/resources", headers=admin_headers)
    assert resources_resp.status_code == 200
    assert "error" not in resources_resp.json()

    client.delete(f"/regions/{region_id}", headers=admin_headers)

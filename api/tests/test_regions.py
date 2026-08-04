"""Tests for the multi-region feature's /regions routes.

The "reachable agent" cases use a tiny in-process fake HTTP server
(fake_region_agent fixture) instead of Docker or a real region-agent
process, so these stay fast and don't depend on the `wg` binary or any
external stack being up.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from .conftest import ADMIN_USERNAME, ADMIN_PASSWORD


class _FakeAgentHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # silence request logging in test output

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "healthy", "wireguard_status": "running", "peer_count": 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture()
def fake_region_agent():
    """A real (if minimal) HTTP server on an ephemeral loopback port that
    only answers GET /health - enough to exercise RegionClient/region_service
    for real, without needing Docker or the `wg` binary."""
    server = HTTPServer(("127.0.0.1", 0), _FakeAgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def regular_user_headers(client):
    client.post("/auth/register", json={"username": "region_test_user", "password": "RegionTestPassw0rd!"})
    login = client.post("/auth/login", json={"username": "region_test_user", "password": "RegionTestPassw0rd!"})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_regions_starts_with_local(client, admin_headers):
    resp = client.get("/regions", headers=admin_headers)
    assert resp.status_code == 200
    regions = resp.json()
    local = [r for r in regions if r["is_local"]]
    assert len(local) == 1
    assert local[0]["slug"] == "local"
    # Never leaks the encrypted key material back to the client.
    assert "agent_key_encrypted" not in local[0]
    assert "agent_key" not in local[0]


def test_non_admin_cannot_create_region(client, regular_user_headers):
    resp = client.post(
        "/regions",
        json={
            "slug": "nope",
            "display_name": "Nope",
            "country_code": "US",
            "agent_url": "http://127.0.0.1:1",
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.5",
        },
        headers=regular_user_headers,
    )
    assert resp.status_code == 403


def test_create_region_with_unreachable_agent_is_rejected(client, admin_headers):
    """Port 1 on loopback should have nothing listening - a fast,
    deterministic "connection refused" rather than a mock."""
    resp = client.post(
        "/regions",
        json={
            "slug": "unreachable-test",
            "display_name": "Unreachable Test",
            "country_code": "US",
            "agent_url": "http://127.0.0.1:1",
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.5",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 400

    # And it must not have been saved despite the rejection.
    list_resp = client.get("/regions", headers=admin_headers)
    slugs = [r["slug"] for r in list_resp.json()]
    assert "unreachable-test" not in slugs


def test_create_list_healthcheck_delete_region(client, admin_headers, fake_region_agent):
    create_resp = client.post(
        "/regions",
        json={
            "slug": "fake-region",
            "display_name": "Fake Region",
            "country_code": "de",
            "city": "Frankfurt",
            "agent_url": fake_region_agent,
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.9",
            "wireguard_endpoint_port": 51820,
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    region = create_resp.json()
    assert region["slug"] == "fake-region"
    assert region["country_code"] == "DE"
    assert region["health_status"] == "healthy"
    region_id = region["id"]

    list_resp = client.get("/regions", headers=admin_headers)
    slugs = [r["slug"] for r in list_resp.json()]
    assert "fake-region" in slugs

    health_resp = client.post(f"/regions/{region_id}/health-check", headers=admin_headers)
    assert health_resp.status_code == 200
    assert health_resp.json()["health_status"] == "healthy"

    delete_resp = client.delete(f"/regions/{region_id}", headers=admin_headers)
    assert delete_resp.status_code == 200

    list_resp_after = client.get("/regions", headers=admin_headers)
    slugs_after = [r["slug"] for r in list_resp_after.json()]
    assert "fake-region" not in slugs_after


def test_local_region_cannot_be_updated_or_deleted(client, admin_headers):
    regions = client.get("/regions", headers=admin_headers).json()
    local_id = next(r["id"] for r in regions if r["is_local"])

    update_resp = client.put(f"/regions/{local_id}", json={"display_name": "Hijacked"}, headers=admin_headers)
    assert update_resp.status_code == 400

    delete_resp = client.delete(f"/regions/{local_id}", headers=admin_headers)
    assert delete_resp.status_code == 400

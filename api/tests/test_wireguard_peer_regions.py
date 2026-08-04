"""Tests for the region-aware WireGuard peer routes added in Phase 3.

Two things need covering, without depending on a real `wg0` interface
(not available in a plain test environment) or Docker:

1. The default/"local" path must still call the exact same VPNManager
   methods with the exact same arguments as before this feature existed -
   verified here by monkeypatching those methods and asserting on the
   call, rather than by mocking WireGuard itself.
2. A non-local `region` must dispatch to that region's agent instead -
   verified end-to-end against a small in-process fake agent (real HTTP,
   no Docker/`wg` needed) that implements the same peer CRUD contract as
   region-agent/agent.py.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import main as main_module


class _FakePeerAgentHandler(BaseHTTPRequestHandler):
    peers = {}  # class-level: shared across requests within one fixture instance

    def log_message(self, format, *args):
        pass

    def _send_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "healthy", "wireguard_status": "running", "peer_count": len(self.peers)})
        elif self.path == "/peers":
            self._send_json(200, [{"peer_name": n, "ip": p["ip"], "public_key": "fakepub", "allowed_ips": p["allowed_ips"]} for n, p in self.peers.items()])
        elif self.path.endswith("/config"):
            name = self.path.split("/")[2]
            if name not in self.peers:
                self._send_json(404, {"detail": "not found"})
            else:
                self._send_json(200, {"peer_name": name, "config": self.peers[name]["config"]})
        elif self.path.endswith("/qrcode"):
            name = self.path.split("/")[2]
            if name not in self.peers:
                self._send_json(404, {"detail": "not found"})
            else:
                self._send_json(200, {"peer_name": name, "qr_code": "fake-qr-base64"})
        else:
            self._send_json(404, {"detail": "not found"})

    def do_POST(self):
        body = self._read_json()
        name = body["peer_name"]
        self.peers[name] = {
            "ip": f"10.13.13.{len(self.peers) + 2}",
            "allowed_ips": body.get("allowed_ips", "0.0.0.0/0"),
            "config": f"[Interface]\nPrivateKey = fake\nAddress = 10.13.13.{len(self.peers) + 2}/24\n",
        }
        self._send_json(200, {"peer_name": name, "public_key": "fakepub", "ip": self.peers[name]["ip"], "config": self.peers[name]["config"], "qr_code": "fake-qr-base64"})

    def do_PUT(self):
        old_name = self.path.split("/")[2]
        body = self._read_json()
        new_name = body["peer_name"]
        if old_name not in self.peers:
            self._send_json(404, {"detail": "not found"})
            return
        entry = self.peers.pop(old_name)
        entry["allowed_ips"] = body.get("allowed_ips", entry["allowed_ips"])
        self.peers[new_name] = entry
        self._send_json(200, {"message": f"Peer {old_name} updated successfully", "peer_name": new_name})

    def do_DELETE(self):
        name = self.path.split("/")[2]
        self.peers.pop(name, None)
        self._send_json(200, {"message": f"Peer {name} deleted successfully"})


@pytest.fixture()
def fake_peer_agent():
    _FakePeerAgentHandler.peers = {}
    server = HTTPServer(("127.0.0.1", 0), _FakePeerAgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def registered_fake_region(client, admin_headers, fake_peer_agent):
    resp = client.post(
        "/regions",
        json={
            "slug": "peer-test-region",
            "display_name": "Peer Test Region",
            "country_code": "fr",
            "agent_url": fake_peer_agent,
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.20",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    region_id = resp.json()["id"]
    yield "peer-test-region"
    client.delete(f"/regions/{region_id}", headers=admin_headers)


def test_default_region_calls_unmodified_local_vpn_manager(client, admin_headers, monkeypatch):
    """No `region` field sent at all - must reach vpn_manager.create_wireguard_peer
    with the exact same positional arguments it always received, proving the
    new branch is a transparent passthrough for the pre-existing behavior."""
    captured = {}

    async def fake_create(peer_name, user_id, allowed_ips="0.0.0.0/0"):
        captured["args"] = (peer_name, user_id, allowed_ips)
        return {"peer_name": peer_name, "user_id": user_id, "public_key": "x", "config": "fake", "qr_code": "fake"}

    monkeypatch.setattr(main_module.vpn_manager, "create_wireguard_peer", fake_create)

    resp = client.post(
        "/vpn/wireguard/peers",
        json={"peer_name": "loc1", "user_id": 1, "allowed_ips": "0.0.0.0/0"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["args"] == ("loc1", 1, "0.0.0.0/0")


def test_explicit_region_local_matches_default(client, admin_headers, monkeypatch):
    captured = {}

    async def fake_delete(peer_name):
        captured["peer_name"] = peer_name
        return {"message": "ok"}

    monkeypatch.setattr(main_module.vpn_manager, "delete_wireguard_peer", fake_delete)

    resp = client.delete("/vpn/wireguard/peers/loc1?region=local", headers=admin_headers)
    assert resp.status_code == 200
    assert captured["peer_name"] == "loc1"


def test_remote_region_full_peer_lifecycle(client, admin_headers, registered_fake_region):
    region = registered_fake_region

    create_resp = client.post(
        "/vpn/wireguard/peers",
        json={"peer_name": "rmt1", "user_id": 1, "allowed_ips": "0.0.0.0/0", "region": region},
        headers=admin_headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    assert create_resp.json()["peer_name"] == "rmt1"

    list_resp = client.get("/vpn/wireguard/peers", headers=admin_headers)
    assert list_resp.status_code == 200
    remote_peers = [p for p in list_resp.json()["peers"] if p["region"] == region]
    assert len(remote_peers) == 1
    assert remote_peers[0]["name"] == "rmt1"
    assert remote_peers[0]["region_display"] == "Peer Test Region"

    config_resp = client.get(f"/vpn/wireguard/peers/rmt1/config?region={region}", headers=admin_headers)
    assert config_resp.status_code == 200
    assert "Interface" in config_resp.text

    qr_resp = client.get(f"/vpn/wireguard/peers/rmt1/qrcode?region={region}", headers=admin_headers)
    assert qr_resp.status_code == 200
    assert qr_resp.json()["qr_code"]

    update_resp = client.put(
        f"/vpn/wireguard/peers/rmt1?region={region}",
        json={"peer_name": "rmt2", "allowed_ips": "10.0.0.0/8"},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200

    delete_resp = client.delete(f"/vpn/wireguard/peers/rmt2?region={region}", headers=admin_headers)
    assert delete_resp.status_code == 200

    final_list = client.get("/vpn/wireguard/peers", headers=admin_headers)
    remote_peers_after = [p for p in final_list.json()["peers"] if p["region"] == region]
    assert remote_peers_after == []


def test_create_peer_in_unregistered_region_404s(client, admin_headers):
    resp = client.post(
        "/vpn/wireguard/peers",
        json={"peer_name": "gho1", "user_id": 1, "allowed_ips": "0.0.0.0/0", "region": "does-not-exist"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_list_peers_degrades_gracefully_when_region_unreachable(client, admin_headers):
    """Register a region whose agent then goes offline, and confirm
    /vpn/wireguard/peers still returns 200 (with a warning) instead of
    failing the whole request."""
    import threading as _threading
    from http.server import HTTPServer as _HTTPServer

    server = _HTTPServer(("127.0.0.1", 0), _FakePeerAgentHandler)
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"

    create_resp = client.post(
        "/regions",
        json={
            "slug": "flaky-region",
            "display_name": "Flaky Region",
            "country_code": "jp",
            "agent_url": url,
            "agent_key": "0123456789abcdef",
            "wireguard_endpoint_host": "203.0.113.30",
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 200
    region_id = create_resp.json()["id"]

    # Take the agent offline, then confirm the aggregate list still succeeds.
    server.shutdown()
    thread.join(timeout=5)

    list_resp = client.get("/vpn/wireguard/peers", headers=admin_headers)
    assert list_resp.status_code == 200
    assert any("flaky-region" in w for w in list_resp.json().get("warnings", []))

    client.delete(f"/regions/{region_id}", headers=admin_headers)

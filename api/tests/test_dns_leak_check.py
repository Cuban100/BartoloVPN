"""Tests for GET /api/dns/leak-check.

Cross-checks each connected WireGuard peer / OpenVPN client against real
DNS query activity (from DnsQueryLog, the same table dns_activity.py feeds -
see test_dns_activity.py for that side). A peer that's clearly transferring
data but has no logged DNS queries is flagged "leak_suspected"; one with no
meaningful traffic is just "idle", not flagged. IKEv2 has no dedicated DNS
server or query logging in this stack, so it's always reported unavailable
rather than faking a check.
"""
import os
import time
from datetime import datetime

import pytest

import main as main_module
from database import AsyncSessionLocal, DnsQueryLog


async def _insert_dns_log(peer_ip: str, domain: str = "example.com"):
    async with AsyncSessionLocal() as db:
        db.add(DnsQueryLog(peer_ip=peer_ip, domain=domain, timestamp=datetime.utcnow()))
        await db.commit()


def _write_wg_peer_conf(peer_name: str, dns_value: str):
    peers_dir = os.path.join(os.environ["WIREGUARD_CONFIG_PATH"], "peers")
    os.makedirs(peers_dir, exist_ok=True)
    with open(os.path.join(peers_dir, f"{peer_name}.conf"), "w") as f:
        f.write(f"[Interface]\nPrivateKey = fake\nAddress = 10.13.13.5/24\nDNS = {dns_value}\n")


def test_ikev2_always_reported_unavailable(client, admin_headers):
    resp = client.get("/api/dns/leak-check", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ikev2"]["available"] is False
    assert "reason" in data["ikev2"]


def test_wireguard_peer_with_traffic_but_no_dns_activity_flagged(client, admin_headers, monkeypatch):
    _write_wg_peer_conf("lk1", "10.13.13.1")

    async def fake_wg_stats():
        return [{
            "name": "lk1", "ip": "10.13.13.5",
            "latest_handshake": int(time.time()),
            "rx_bytes": 500 * 1024, "tx_bytes": 500 * 1024,
        }]
    monkeypatch.setattr(main_module.vpn_manager, "get_wireguard_peer_stats", fake_wg_stats)

    async def fake_ovpn_stats():
        return []
    monkeypatch.setattr(main_module.vpn_manager, "get_openvpn_client_stats", fake_ovpn_stats)

    resp = client.get("/api/dns/leak-check", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    peers = resp.json()["wireguard"]["peers"]
    match = [p for p in peers if p["name"] == "lk1"]
    assert len(match) == 1
    assert match[0]["status"] == "leak_suspected"


def test_wireguard_peer_with_dns_activity_is_ok(client, admin_headers, monkeypatch):
    _write_wg_peer_conf("lk2", "10.13.13.1")

    async def fake_wg_stats():
        return [{
            "name": "lk2", "ip": "10.13.13.6",
            "latest_handshake": int(time.time()),
            "rx_bytes": 500 * 1024, "tx_bytes": 500 * 1024,
        }]
    monkeypatch.setattr(main_module.vpn_manager, "get_wireguard_peer_stats", fake_wg_stats)

    async def fake_ovpn_stats():
        return []
    monkeypatch.setattr(main_module.vpn_manager, "get_openvpn_client_stats", fake_ovpn_stats)

    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_dns_log("10.13.13.6"))

    resp = client.get("/api/dns/leak-check", headers=admin_headers)
    assert resp.status_code == 200
    match = [p for p in resp.json()["wireguard"]["peers"] if p["name"] == "lk2"]
    assert match[0]["status"] == "ok"


def test_wireguard_idle_peer_not_flagged(client, admin_headers, monkeypatch):
    _write_wg_peer_conf("lk3", "10.13.13.1")

    async def fake_wg_stats():
        return [{
            "name": "lk3", "ip": "10.13.13.7",
            "latest_handshake": int(time.time()),
            "rx_bytes": 100, "tx_bytes": 100,  # well under the traffic threshold
        }]
    monkeypatch.setattr(main_module.vpn_manager, "get_wireguard_peer_stats", fake_wg_stats)

    async def fake_ovpn_stats():
        return []
    monkeypatch.setattr(main_module.vpn_manager, "get_openvpn_client_stats", fake_ovpn_stats)

    resp = client.get("/api/dns/leak-check", headers=admin_headers)
    match = [p for p in resp.json()["wireguard"]["peers"] if p["name"] == "lk3"]
    assert match[0]["status"] == "idle"


def test_wireguard_config_dns_mismatch_flagged(client, admin_headers, monkeypatch):
    """A peer whose saved .conf has drifted from the expected local CoreDNS
    address (10.13.13.1) - e.g. hand-edited - is a config problem regardless
    of traffic or activity."""
    _write_wg_peer_conf("lk4", "8.8.8.8")

    async def fake_wg_stats():
        return [{
            "name": "lk4", "ip": "10.13.13.8",
            "latest_handshake": int(time.time()),
            "rx_bytes": 0, "tx_bytes": 0,
        }]
    monkeypatch.setattr(main_module.vpn_manager, "get_wireguard_peer_stats", fake_wg_stats)

    async def fake_ovpn_stats():
        return []
    monkeypatch.setattr(main_module.vpn_manager, "get_openvpn_client_stats", fake_ovpn_stats)

    resp = client.get("/api/dns/leak-check", headers=admin_headers)
    match = [p for p in resp.json()["wireguard"]["peers"] if p["name"] == "lk4"]
    assert match[0]["status"] == "config_mismatch"


def test_openvpn_client_leak_and_ok_paths(client, admin_headers, monkeypatch):
    async def fake_wg_stats():
        return []
    monkeypatch.setattr(main_module.vpn_manager, "get_wireguard_peer_stats", fake_wg_stats)

    async def fake_ovpn_stats():
        return [
            {"name": "ov-leak", "virtual_ip": "10.8.0.10", "rx_bytes": 500 * 1024, "tx_bytes": 500 * 1024},
            {"name": "ov-ok", "virtual_ip": "10.8.0.11", "rx_bytes": 500 * 1024, "tx_bytes": 500 * 1024},
        ]
    monkeypatch.setattr(main_module.vpn_manager, "get_openvpn_client_stats", fake_ovpn_stats)

    import asyncio
    asyncio.get_event_loop().run_until_complete(_insert_dns_log("10.8.0.11"))

    resp = client.get("/api/dns/leak-check", headers=admin_headers)
    assert resp.status_code == 200
    clients = resp.json()["openvpn"]["clients"]
    by_name = {c["name"]: c["status"] for c in clients}
    assert by_name["ov-leak"] == "leak_suspected"
    assert by_name["ov-ok"] == "ok"
    assert "note" in resp.json()["openvpn"]

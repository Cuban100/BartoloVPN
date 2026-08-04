#!/usr/bin/env python3
"""
BartoloVPN Region Agent

Runs on one remote VPS, alongside its own WireGuard container, and
exposes a minimal authenticated API for the central BartoloVPN
dashboard to manage this box's WireGuard peers. Deliberately narrow
surface: peer CRUD + health only, no shell/exec passthrough - the same
"scoped, not a general passthrough" philosophy already used for
bartolo-docker-log-proxy in the main project's docker-compose.yml.
"""

import hmac
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List

from fastapi import FastAPI, HTTPException, Header, Request, status
from pydantic import BaseModel, Field

from config import settings  # type: ignore  # Pylance: namespace collision with config dir
from wireguard_core import WireGuardCore

app = FastAPI(title="BartoloVPN Region Agent")
wg = WireGuardCore()

# Same sliding-window lockout shape as the central dashboard's own login
# rate limiting (api/main.py's _login_rate_limit_check) - 5 failed agent
# key attempts per IP within 15 minutes gets a 429, so a leaked/incorrect
# key can't be brute-forced against this box.
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 5
AUTH_RATE_LIMIT_WINDOW_MINUTES = 15
_failed_auth_attempts: Dict[str, List[datetime]] = defaultdict(list)


def _auth_rate_limit_check(client_ip: str) -> None:
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=AUTH_RATE_LIMIT_WINDOW_MINUTES)
    recent = [t for t in _failed_auth_attempts.get(client_ip, []) if t > window_start]
    _failed_auth_attempts[client_ip] = recent
    if len(recent) >= AUTH_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed agent-key attempts. Try again in {AUTH_RATE_LIMIT_WINDOW_MINUTES} minutes.",
        )


def _auth_rate_limit_record_failure(client_ip: str) -> None:
    _failed_auth_attempts[client_ip].append(datetime.utcnow())


def require_agent_key(request: Request, x_agent_key: str = Header(default="")) -> None:
    client_ip = request.client.host if request.client else "unknown"
    _auth_rate_limit_check(client_ip)
    # Never log the presented or expected key - only that a failure happened.
    if not hmac.compare_digest(x_agent_key, settings.agent_api_key):
        _auth_rate_limit_record_failure(client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing agent key")


class PeerCreate(BaseModel):
    peer_name: str = Field(..., min_length=3, max_length=4)
    allowed_ips: str = "0.0.0.0/0"


class PeerUpdate(BaseModel):
    peer_name: str = Field(..., min_length=3, max_length=4)
    allowed_ips: str = "0.0.0.0/0"


@app.get("/health")
async def health():
    """No auth required - intentionally non-sensitive (no key material,
    no peer data), so the provisioning script and the central dashboard's
    health poller can both confirm reachability without needing the key
    over a not-yet-verified TLS hop."""
    status_info = await wg.get_status()
    peers = await wg.list_peers()
    return {
        "status": "healthy",
        "wireguard_status": status_info["status"],
        "peer_count": len(peers),
    }


@app.get("/peers")
async def list_peers(request: Request, x_agent_key: str = Header(default="")):
    require_agent_key(request, x_agent_key)
    return await wg.list_peers()


@app.post("/peers")
async def create_peer(peer: PeerCreate, request: Request, x_agent_key: str = Header(default="")):
    require_agent_key(request, x_agent_key)
    return await wg.create_peer(peer.peer_name, peer.allowed_ips)


@app.put("/peers/{peer_name}")
async def update_peer(peer_name: str, peer: PeerUpdate, request: Request, x_agent_key: str = Header(default="")):
    require_agent_key(request, x_agent_key)
    return await wg.update_peer(peer_name, peer.peer_name, peer.allowed_ips)


@app.delete("/peers/{peer_name}")
async def delete_peer(peer_name: str, request: Request, x_agent_key: str = Header(default="")):
    require_agent_key(request, x_agent_key)
    return await wg.delete_peer(peer_name)


@app.get("/peers/{peer_name}/config")
async def get_peer_config(peer_name: str, request: Request, x_agent_key: str = Header(default="")):
    require_agent_key(request, x_agent_key)
    return {"peer_name": peer_name, "config": wg.get_peer_config(peer_name)}


@app.get("/peers/{peer_name}/qrcode")
async def get_peer_qrcode(peer_name: str, request: Request, x_agent_key: str = Header(default="")):
    require_agent_key(request, x_agent_key)
    return {"peer_name": peer_name, "qr_code": await wg.get_peer_qrcode(peer_name)}

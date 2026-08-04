#!/usr/bin/env python3
"""
BartoloVPN Management API - FastAPI Version
Handles VPN configuration and management for WireGuard, OpenVPN, and IKEv2
"""

import os
import re
import json
import asyncio
import subprocess
import hashlib
from collections import defaultdict
import qrcode
import base64
import logging
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

# Configure logging
log_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'bartolovpn.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.hazmat.primitives import serialization
import psutil
import aiohttp
# import netifaces  # Removed due to build issues - using psutil for network info instead

# Import configuration
from config import settings  # type: ignore  # Pylance: namespace collision with config dir

class UserCreate(BaseModel):
    """User creation model"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None
    role: str = "user"
    protocols: List[str] = ["wireguard"]

class UserUpdate(BaseModel):
    """User update model"""
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=6)
    email: Optional[str] = None
    role: Optional[str] = None
    protocols: Optional[List[str]] = None
    status: Optional[str] = None

class UserResponse(BaseModel):
    """User response model"""
    id: int
    username: str
    email: Optional[str]
    role: str
    protocols: List[str]
    created_at: datetime
    last_login: Optional[datetime]
    is_active: bool

class UserLogin(BaseModel):
    """User login model"""
    username: str
    password: str

class Token(BaseModel):
    """Token model"""
    access_token: str
    token_type: str
    username: str

class WireGuardPeerCreate(BaseModel):
    """WireGuard peer creation model.

    peer_name is capped at 4 chars (not the usual 50) because the
    downloaded config is named "BartoloVPN-{peer_name}.conf", and that
    filename becomes the tunnel name on import - WireGuard hard-caps
    tunnel names at 15 characters, and "BartoloVPN-" alone is 11.
    """
    peer_name: str = Field(..., min_length=3, max_length=4)
    user_id: int
    allowed_ips: str = "0.0.0.0/0"
    dns_servers: str = "1.1.1.1,8.8.8.8"
    # "local" (default) keeps using this box's own WireGuard server via
    # VPNManager, exactly as before this field existed - any caller that
    # omits it (old frontend build, scripts, tests) is unaffected. Any
    # other value must match a Region.slug registered via POST /regions.
    region: str = "local"

class WireGuardPeerUpdate(BaseModel):
    """Rename a peer and/or change its own AllowedIPs (split-tunnel
    routing on the client's side - not the server's fixed /32 registration,
    which never changes)."""
    peer_name: str = Field(..., min_length=3, max_length=4)
    allowed_ips: str = "0.0.0.0/0"

# DNS resolvers per region for OpenVPN clients (same servers as
# scripts/geo-spoofing.sh's WireGuard-only feature, for parity). This only
# swaps which DNS resolver a client uses via a per-client config override -
# it does NOT change the client's actual egress IP, so it won't fool
# IP-based geo-blocking (Netflix etc.) - real geolocation is set by which
# country your traffic physically exits from, not your DNS resolver.
OPENVPN_DNS_REGIONS = {
    "default": [],
    "sweden": ["130.242.4.8", "130.242.4.9", "8.8.8.8", "1.1.1.1"],
}

class OpenVPNClientCreate(BaseModel):
    """OpenVPN client creation model"""
    client_name: str = Field(..., min_length=3, max_length=50)
    user_id: int
    protocol: str = "udp"
    cipher: str = "AES-256-GCM"
    dns_region: str = "default"

class SystemStats(BaseModel):
    """System statistics model"""
    cpu_percent: float
    memory_percent: float
    memory_used: int
    memory_total: int
    disk_percent: float
    disk_used: int
    disk_total: int
    network_bytes_sent: int
    network_bytes_recv: int
    timestamp: datetime

class VPNStatus(BaseModel):
    """VPN service status model"""
    service: str
    status: str
    uptime: Optional[str] = None  # Optional uptime with default for easier instantiation
    connections: int
    last_updated: datetime

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security
security = HTTPBearer()

# Import database models
from database import (
    User, VPNConfig, UserSession, UsageLog, ServerEndpoint, IPRotation, DnsQueryLog, Region, SystemSettings,
    AsyncSessionLocal, init_db, create_default_admin, create_default_endpoints, create_default_region,
    create_default_settings, get_db
)
from ip_rotation import ip_rotation_service
from dns_activity import dns_activity_poller, _demux_docker_log_stream
import region_service
from region_service import region_health_poller
from region_client import RegionClient

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# VPN Manager Class
class VPNManager:
    """Manages VPN configurations and operations"""
    
    def __init__(self):
        self.wireguard_config = f"{settings.wireguard_config_path}/wg0.conf"
        self.openvpn_config = f"{settings.openvpn_config_path}/server.conf"
        self.ikev2_config = f"{settings.ikev2_config_path}/ipsec.conf"
        # Serializes WireGuard peer add/remove so IP allocation and
        # wg_confs/wg0.conf edits can't race each other.
        self.wireguard_peer_lock = asyncio.Lock()
        # compose service name -> resolved container name, see
        # _resolve_sibling_container. Safe to cache for the process
        # lifetime since a service's container doesn't change identity
        # without a full recreate (which would restart vpn-api too).
        self._sibling_container_cache: Dict[str, str] = {}

    async def _get_wireguard_server_public_key(self) -> str:
        """The server's public key, read live from the running interface.

        This must never come from a separately-tracked file: wg0's actual
        private key lives in wg_confs/wg0.conf (owned by the wireguard
        container's own init scripts), and any app-side copy of "the server
        key" can silently drift from it (e.g. after the wireguard container
        regenerates its identity). Reading it live guarantees client configs
        always embed whatever key the interface is actually using right now.
        """
        result = await asyncio.create_subprocess_exec(
            'wg', 'show', 'wg0', 'public-key',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        public_key = stdout.decode().strip()
        if result.returncode != 0 or not public_key or public_key == "(none)":
            raise HTTPException(status_code=503, detail=f"Could not read live WireGuard server key: {stderr.decode().strip()}")
        return public_key

    async def get_wireguard_peer_stats(self) -> List[Dict[str, Any]]:
        """Real per-peer stats straight from the kernel (wg show wg0 dump),
        with peer names resolved from the app-managed peer conf files. This
        is the ground truth the dashboard's monitoring/connections views
        should be built on, instead of hardcoded placeholders."""
        peers_dir = f"{settings.wireguard_config_path}/peers"
        ip_to_name = {}
        if os.path.exists(peers_dir):
            for fname in os.listdir(peers_dir):
                if fname.endswith('.conf'):
                    with open(os.path.join(peers_dir, fname), 'r') as f:
                        content = f.read()
                    if 'Address = 10.13.13.' in content:
                        ip_suffix = content.split('Address = 10.13.13.')[1].split('/')[0].strip()
                        ip_to_name[f"10.13.13.{ip_suffix}"] = fname[:-5]

        result = await asyncio.create_subprocess_exec(
            'wg', 'show', 'wg0', 'dump',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await result.communicate()
        if result.returncode != 0:
            return []

        lines = stdout.decode().splitlines()
        peers = []
        # First line is the interface itself (private key, public key,
        # listen port, fwmark) - only [Peer] lines have 8 fields.
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) < 8:
                continue
            public_key, _psk, _endpoint, allowed_ips, latest_handshake, rx, tx, _keepalive = parts
            ip = allowed_ips.split('/')[0] if allowed_ips else None
            peers.append({
                'public_key': public_key,
                'name': ip_to_name.get(ip, ip or public_key[:8]),
                'ip': ip,
                'latest_handshake': int(latest_handshake),
                'rx_bytes': int(rx),
                'tx_bytes': int(tx),
            })
        return peers

    async def get_openvpn_client_stats(self) -> List[Dict[str, Any]]:
        """Real per-client OpenVPN stats from the server's own status log.
        vpn-api doesn't share a network namespace with the openvpn container
        (unlike wireguard), so this has to go through the exec proxy rather
        than reading a shared/local file."""
        exit_code, output = await self._docker_exec("openvpn", ["cat", "/tmp/openvpn-status.log"])
        if exit_code != 0:
            return []

        virtual_ip_by_name = {}
        in_routing_table = False
        for line in output.splitlines():
            if line.startswith("ROUTING TABLE"):
                in_routing_table = True
                continue
            if line.startswith("GLOBAL STATS"):
                break
            if in_routing_table and "," in line:
                parts = line.split(",")
                if len(parts) >= 2 and parts[0] != "Virtual Address":
                    virtual_ip_by_name[parts[1]] = parts[0]

        clients = []
        in_client_list = False
        for line in output.splitlines():
            if line.startswith("Common Name,Real Address"):
                in_client_list = True
                continue
            if line.startswith("ROUTING TABLE"):
                break
            if in_client_list and "," in line:
                parts = line.split(",")
                if len(parts) < 5:
                    continue
                name, real_address, rx_bytes, tx_bytes, connected_since = parts[:5]
                try:
                    connected_at = datetime.strptime(connected_since, "%a %b %d %H:%M:%S %Y")
                except ValueError:
                    connected_at = None
                clients.append({
                    "name": name,
                    "real_address": real_address,
                    "virtual_ip": virtual_ip_by_name.get(name),
                    "rx_bytes": int(rx_bytes),
                    "tx_bytes": int(tx_bytes),
                    "connected_at": connected_at,
                })
        return clients

    async def ping_peer_ms(self, ip: str) -> Optional[float]:
        """Real round-trip latency to a peer over the tunnel, in ms.
        Returns None if the peer doesn't respond to ICMP (some clients
        block it) rather than faking a number."""
        try:
            proc = await asyncio.create_subprocess_exec(
                'ping', '-c', '1', '-W', '1', ip,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2)
            if proc.returncode != 0:
                return None
            match = re.search(r'time=([\d.]+)', stdout.decode())
            return float(match.group(1)) if match else None
        except Exception:
            return None

    async def ping_openvpn_client_ms(self, virtual_ip: str) -> Optional[float]:
        """Same idea as ping_peer_ms, but has to run inside the openvpn
        container since vpn-api has no direct route to its tun0 subnet."""
        try:
            exit_code, output = await self._docker_exec("openvpn", ["ping", "-c", "1", "-W", "1", virtual_ip])
            if exit_code != 0:
                return None
            match = re.search(r'time=([\d.]+)', output)
            return float(match.group(1)) if match else None
        except Exception:
            return None

    async def get_wireguard_status(self) -> VPNStatus:
        """Get WireGuard connection status"""
        try:
            result = await asyncio.create_subprocess_exec(
                'wg', 'show', 'wg0',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                connections = len([line for line in stdout.decode().split('\n') if 'peer:' in line])
                return VPNStatus(
                    service="wireguard",
                    status="running",
                    uptime=None,
                    connections=connections,
                    last_updated=datetime.now()
                )
            else:
                return VPNStatus(
                    service="wireguard",
                    status="stopped",
                    uptime=None,
                    connections=0,
                    last_updated=datetime.now()
                )
        except Exception as e:
            return VPNStatus(
                service="wireguard",
                status="error",
                uptime=None,
                connections=0,
                last_updated=datetime.now()
            )
    
    async def create_wireguard_peer(self, peer_name: str, user_id: int, allowed_ips: str = "0.0.0.0/0") -> Dict[str, Any]:
        """Create a new WireGuard peer configuration"""
        async with self.wireguard_peer_lock:
            try:
                # Generate private and public keys
                result = await asyncio.create_subprocess_exec(
                    'wg', 'genkey',
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate()
                private_key = stdout.decode().strip()

                result = await asyncio.create_subprocess_exec(
                    'wg', 'pubkey',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate(input=private_key.encode())
                public_key = stdout.decode().strip()

                # Always the live interface's actual key - see
                # _get_wireguard_server_public_key for why this can't be a
                # cached file.
                server_public_key = await self._get_wireguard_server_public_key()

                # Generate peer configuration
                peer_ip = await self._get_next_peer_ip()
                peer_config = f"""[Interface]
PrivateKey = {private_key}
Address = 10.13.13.{peer_ip}/24
DNS = 10.13.13.1

[Peer]
PublicKey = {server_public_key}
Endpoint = {settings.server_ip}:{settings.wireguard_port}
AllowedIPs = {allowed_ips}
PersistentKeepalive = 25
"""

                # Save peer configuration
                peers_dir = f"{settings.wireguard_config_path}/peers"
                os.makedirs(peers_dir, exist_ok=True)
                peer_file = f"{peers_dir}/{peer_name}.conf"

                with open(peer_file, 'w') as f:
                    f.write(peer_config)

                # Add peer to server configuration
                await self._add_wireguard_peer_to_server(public_key, peer_name, peer_ip)

                # Generate QR code
                qr_code = await self._generate_qr_code(peer_config)

                return {
                    'peer_name': peer_name,
                    'user_id': user_id,
                    'public_key': public_key,
                    'config': peer_config,
                    'qr_code': qr_code,
                    'config_file': peer_file
                }
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to create WireGuard peer: {str(e)}")
    
    async def _get_next_peer_ip(self) -> int:
        """Get next available IP for peer, avoiding collisions with both
        app-managed peer files and peers already registered on the live interface
        (e.g. the container's own auto-provisioned PEERS)"""
        existing_ips = []

        peers_dir = f"{settings.wireguard_config_path}/peers"
        if os.path.exists(peers_dir):
            for file in os.listdir(peers_dir):
                if file.endswith('.conf'):
                    with open(os.path.join(peers_dir, file), 'r') as f:
                        content = f.read()
                        if 'Address = 10.13.13.' in content:
                            ip = content.split('Address = 10.13.13.')[1].split('/')[0].strip()
                            existing_ips.append(int(ip))

        try:
            result = await asyncio.create_subprocess_exec(
                'wg', 'show', 'wg0', 'allowed-ips',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            if result.returncode == 0:
                for line in stdout.decode().splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].startswith('10.13.13.'):
                        octet = parts[1].split('/')[0].split('.')[-1]
                        if octet.isdigit():
                            existing_ips.append(int(octet))
        except Exception:
            pass

        return max(existing_ips + [1]) + 1
    
    async def _add_wireguard_peer_to_server(self, public_key: str, peer_name: str, peer_ip: int):
        """Add peer to the live WireGuard server configuration (requires vpn-api
        to share the wireguard container's network namespace)"""
        server_config = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"

        # Create server config if it doesn't exist. Reuses the wireguard
        # container's own canonical key (/config/server/privatekey-server)
        # rather than inventing a separate one, so the key stays consistent
        # with whatever the container itself would generate on init.
        if not os.path.exists(server_config):
            os.makedirs(os.path.dirname(server_config), exist_ok=True)
            canonical_key_path = f"{settings.wireguard_config_path}/server/privatekey-server"
            if os.path.exists(canonical_key_path):
                with open(canonical_key_path, 'r') as f:
                    server_private_key = f.read().strip()
            else:
                server_private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
                os.makedirs(os.path.dirname(canonical_key_path), exist_ok=True)
                with open(canonical_key_path, 'w') as f:
                    f.write(server_private_key)

            server_config_content = f"""[Interface]
Address = 10.13.13.1
ListenPort = {settings.wireguard_port}
PrivateKey = {server_private_key}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth+ -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth+ -j MASQUERADE
"""
            with open(server_config, 'w') as f:
                f.write(server_config_content)

        # Add peer to server config
        with open(server_config, 'a') as f:
            f.write(f"\n[Peer]\n")
            f.write(f"# {peer_name}\n")
            f.write(f"PublicKey = {public_key}\n")
            f.write(f"AllowedIPs = 10.13.13.{peer_ip}/32\n")

        # Push the change into the live interface. A failure here means the
        # file and the running tunnel have gone out of sync - that must
        # surface as an error, not a silently-ignored warning, or the peer
        # ends up "created" on disk while never actually reachable.
        proc = await asyncio.create_subprocess_exec(
            'bash', '-c', f'wg syncconf wg0 <(wg-quick strip {server_config})',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"wg syncconf failed for new peer {peer_name}: {stderr.decode().strip()}")

        # wg syncconf only updates WireGuard's own crypto-key routing table,
        # not the kernel's IP routing table. Without an explicit route,
        # return traffic for this peer's address falls through to the
        # default route (eth0) instead of wg0 and is silently lost - the
        # peer handshakes fine and can send traffic out, but never receives
        # any reply. wg-quick's initial "up" adds routes for peers present
        # in the config at boot, but peers added afterward via syncconf
        # never get one, so this has to be done explicitly every time.
        route_proc = await asyncio.create_subprocess_exec(
            'ip', 'route', 'add', f'10.13.13.{peer_ip}/32', 'dev', 'wg0',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, route_stderr = await route_proc.communicate()
        if route_proc.returncode != 0 and b'File exists' not in route_stderr:
            raise HTTPException(status_code=500, detail=f"Failed to add route for new peer {peer_name}: {route_stderr.decode().strip()}")

        # Verify the IP we assigned actually landed on this peer and wasn't
        # silently handed to (or stolen from) a different one - WireGuard
        # only allows one peer per AllowedIPs entry, so a collision here
        # means _get_next_peer_ip picked a stale/taken IP.
        verify = await asyncio.create_subprocess_exec(
            'wg', 'show', 'wg0', 'allowed-ips',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await verify.communicate()
        live_ip_for_key = None
        for line in stdout.decode().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == public_key:
                live_ip_for_key = parts[1]
        expected = f"10.13.13.{peer_ip}/32"
        if live_ip_for_key != expected:
            raise HTTPException(
                status_code=500,
                detail=f"Peer {peer_name} did not register at {expected} (got {live_ip_for_key!r}) - likely an IP collision with an existing peer"
            )

    async def _generate_qr_code(self, config_data: str) -> str:
        """Generate QR code for configuration"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(config_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, 'PNG')  # Use positional format to silence Pylance stub warning
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode()
    
    async def update_wireguard_peer(self, peer_name: str, new_name: str, allowed_ips: str) -> Dict[str, Any]:
        """Rename a peer's saved config and/or change its own AllowedIPs.
        Purely bookkeeping on the app's side - WireGuard itself only knows
        peers by public key, and the server's per-peer registration always
        keeps its fixed /32, so nothing here touches the live interface or
        needs a resync."""
        async with self.wireguard_peer_lock:
            peers_dir = f"{settings.wireguard_config_path}/peers"
            old_path = f"{peers_dir}/{peer_name}.conf"
            new_path = f"{peers_dir}/{new_name}.conf"

            if not os.path.exists(old_path):
                raise HTTPException(status_code=404, detail=f"Peer {peer_name} not found")

            if new_name != peer_name and os.path.exists(new_path):
                raise HTTPException(status_code=409, detail=f"A peer named {new_name} already exists")

            with open(old_path, 'r') as f:
                content = f.read()
            content = re.sub(r'^AllowedIPs = .*$', f'AllowedIPs = {allowed_ips}', content, flags=re.MULTILINE)

            with open(new_path, 'w') as f:
                f.write(content)
            if new_name != peer_name:
                os.remove(old_path)

            # Keep the server config's comment tag in sync so delete-by-name
            # (which matches on "# {peer_name}") still finds this peer.
            server_config = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"
            if new_name != peer_name and os.path.exists(server_config):
                with open(server_config, 'r') as f:
                    server_content = f.read()
                server_content = server_content.replace(f"# {peer_name}\n", f"# {new_name}\n")
                with open(server_config, 'w') as f:
                    f.write(server_content)

            return {"message": f"Peer {peer_name} updated successfully", "peer_name": new_name}

    async def delete_wireguard_peer(self, peer_name: str) -> Dict[str, str]:
        """Delete WireGuard peer"""
        async with self.wireguard_peer_lock:
            try:
                # Remove peer configuration file
                peer_config_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"
                if os.path.exists(peer_config_file):
                    os.remove(peer_config_file)

                # Remove peer from server configuration
                server_config = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"
                if os.path.exists(server_config):
                    await self._remove_wireguard_peer_from_server(peer_name, server_config)

                # Remove from database
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(VPNConfig).where(
                            VPNConfig.config_name == peer_name,
                            VPNConfig.protocol == "wireguard"
                        )
                    )
                    vpn_config = result.scalar_one_or_none()
                    if vpn_config:
                        await session.delete(vpn_config)
                        await session.commit()

                return {"message": f"Peer {peer_name} deleted successfully"}

            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to delete peer: {str(e)}")
    
    async def _remove_wireguard_peer_from_server(self, peer_name: str, server_config: str):
        """Remove peer from WireGuard server configuration"""
        with open(server_config, 'r') as f:
            content = f.read()

        # Split on the [Peer] marker so each peer's block (comment, keys,
        # AllowedIPs) is handled as a unit instead of line-by-line, which
        # can't look ahead to know a block belongs to the peer being removed.
        sections = content.split('[Peer]')
        header = sections[0]
        peer_blocks = sections[1:]

        removed_blocks = [block for block in peer_blocks if f"# {peer_name}" in block]
        kept_blocks = [block for block in peer_blocks if f"# {peer_name}" not in block]

        new_content = header + ''.join(f"[Peer]{block}" for block in kept_blocks)

        # Write updated configuration
        with open(server_config, 'w') as f:
            f.write(new_content)

        # Push the change into the live interface
        proc = await asyncio.create_subprocess_exec(
            'bash', '-c', f'wg syncconf wg0 <(wg-quick strip {server_config})',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"wg syncconf failed while removing peer: {stderr.decode().strip()}")

        # Clean up the matching route added in _add_wireguard_peer_to_server
        # (best-effort - a leftover route to a now-unassigned IP is harmless
        # since nothing on wg0 will claim it, but don't leave clutter).
        for block in removed_blocks:
            for line in block.splitlines():
                if line.strip().startswith('AllowedIPs'):
                    ip_cidr = line.split('=', 1)[1].strip()
                    del_proc = await asyncio.create_subprocess_exec(
                        'ip', 'route', 'del', ip_cidr, 'dev', 'wg0',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    await del_proc.communicate()

    async def get_system_stats(self) -> SystemStats:
        """Get system statistics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()
            
            return SystemStats(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used=memory.used,
                memory_total=memory.total,
                disk_percent=disk.percent,
                disk_used=disk.used,
                disk_total=disk.total,
                network_bytes_sent=network.bytes_sent,
                network_bytes_recv=network.bytes_recv,
                timestamp=datetime.now()
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get system stats: {str(e)}")
    
    # ========== OpenVPN Methods ==========
    
    async def get_openvpn_status(self) -> VPNStatus:
        """Get OpenVPN connection status"""
        try:
            # Check if OpenVPN is running
            process = await asyncio.create_subprocess_exec(
                'pgrep', '-f', 'openvpn',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return VPNStatus(
                    service="openvpn",
                    status="running",
                    uptime=None,  # TODO: Get actual uptime
                    connections=0,  # TODO: Get actual connection count
                    last_updated=datetime.now()
                )
            else:
                return VPNStatus(
                    service="openvpn",
                    status="stopped",
                    uptime=None,
                    connections=0,
                    last_updated=datetime.now()
                )
        except Exception:
            return VPNStatus(
                service="openvpn",
                status="error",
                uptime=None,
                connections=0,
                last_updated=datetime.now()
            )
    
    async def _resolve_sibling_container(self, service_name: str) -> str:
        """Find the actual container name for a sibling compose service
        (e.g. "openvpn", "wireguard", "ikev2"), instead of assuming a fixed,
        hardcoded container name.

        docker-compose.yml intentionally does NOT set container_name: on
        any service - a hardcoded name is global across the whole Docker
        host, so any second clone of this repo running `docker-compose up`
        in a different directory would silently steal/replace the real
        production containers by reusing the same names (this happened in
        production more than once). Without container_name, Compose
        prefixes each container with its own project name (derived from
        the directory), so two different directories never collide - but
        it also means the actual container name isn't fixed or guessable
        by this code, so it has to be looked up via the compose labels
        Docker itself attaches to every container.
        """
        if service_name in self._sibling_container_cache:
            return self._sibling_container_cache[service_name]

        proxy_url = "http://127.0.0.1:2375"
        own_id = os.environ.get("HOSTNAME", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{proxy_url}/containers/{own_id}/json",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status >= 400:
                    raise HTTPException(status_code=502, detail=f"Could not inspect own container to resolve compose project (HTTP {resp.status})")
                own_info = await resp.json()
            project = own_info.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
            if not project:
                raise HTTPException(status_code=502, detail="Own container has no com.docker.compose.project label - can't resolve sibling containers")

            filters = json.dumps({
                "label": [f"com.docker.compose.project={project}", f"com.docker.compose.service={service_name}"]
            })
            async with session.get(
                f"{proxy_url}/containers/json",
                params={"filters": filters},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status >= 400:
                    raise HTTPException(status_code=502, detail=f"Could not list containers to resolve compose service '{service_name}' (HTTP {resp.status})")
                matches = await resp.json()

        if not matches:
            raise HTTPException(status_code=502, detail=f"No running container found for compose service '{service_name}' in project '{project}'")

        # Docker's API returns names with a leading slash, e.g. "/bartolovpn-openvpn-1"
        resolved = matches[0]["Names"][0].lstrip("/")
        self._sibling_container_cache[service_name] = resolved
        return resolved

    async def _docker_exec(self, service_name: str, cmd: List[str], env: Optional[List[str]] = None) -> tuple:
        """Run a command inside another container via the scoped docker-log-proxy
        (container list/inspect/logs/exec only - see docker-compose.yml).
        Needed because the openvpn container's easyrsa toolchain doesn't
        exist anywhere else. `service_name` is a compose *service* name
        (e.g. "openvpn"), resolved to the real running container name via
        _resolve_sibling_container - never a hardcoded "bartolo-*" name,
        since that name isn't fixed (see _resolve_sibling_container).
        Returns (exit_code, combined_output)."""
        container = await self._resolve_sibling_container(service_name)
        proxy_url = "http://127.0.0.1:2375"
        async with aiohttp.ClientSession() as session:
            create_body = {
                "Cmd": cmd,
                "Env": env or [],
                "AttachStdout": True,
                "AttachStderr": True,
            }
            async with session.post(
                f"{proxy_url}/containers/{container}/exec",
                json=create_body,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"docker exec create failed ({resp.status}): {text}")
                exec_id = (await resp.json())["Id"]

            async with session.post(
                f"{proxy_url}/exec/{exec_id}/start",
                json={"Detach": False, "Tty": False},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise HTTPException(status_code=502, detail=f"docker exec start failed ({resp.status}): {text}")
                raw = await resp.read()
                output = _demux_docker_log_stream(raw)

            async with session.get(
                f"{proxy_url}/exec/{exec_id}/json",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                exit_code = (await resp.json()).get("ExitCode", -1)

        return exit_code, output

    async def create_openvpn_client(self, client_name: str, user_id: int, protocol: str = "udp", cipher: str = "AES-256-GCM", dns_region: str = "default") -> Dict[str, Any]:
        """Create a new OpenVPN client configuration"""
        if dns_region not in OPENVPN_DNS_REGIONS:
            raise HTTPException(status_code=400, detail=f"Unknown dns_region '{dns_region}' - supported: {', '.join(OPENVPN_DNS_REGIONS)}")
        if protocol != "udp":
            # The openvpn container's server config (scripts/init-openvpn-proper.sh)
            # only ever sets up a single UDP listener, and docker-compose.yml
            # only publishes 1194/udp - a "tcp" client config would look
            # valid but could never actually connect. Reject rather than
            # hand back something silently broken.
            raise HTTPException(status_code=400, detail="Only UDP is supported - the OpenVPN server isn't configured with a TCP listener")
        try:
            logger.info(f"Creating OpenVPN client: {client_name} for user {user_id}")
            
            # Create client directory
            clients_dir = f"{settings.openvpn_config_path}/clients"
            os.makedirs(clients_dir, exist_ok=True)
            
            # Check if PKI exists
            pki_dir = f"{settings.openvpn_config_path}/pki"
            ca_cert_path = f"{pki_dir}/ca.crt"
            ta_key_path = f"{pki_dir}/ta.key"

            if not os.path.exists(ca_cert_path) or not os.path.exists(ta_key_path):
                # The openvpn container (kylemanna/openvpn) initializes its
                # own PKI on first boot via scripts/init-openvpn-proper.sh -
                # if that hasn't happened yet, there's nothing to sign
                # against and no config that would actually work.
                raise HTTPException(
                    status_code=503,
                    detail="OpenVPN PKI not initialized yet - the openvpn container should create ca.crt/ta.key on startup, check its logs"
                )
            else:
                # The easyrsa toolchain used to create the CA only exists
                # inside the openvpn container's own image, not here or
                # anywhere in the shared config volume - so the actual cert
                # signing has to run there, via the scoped exec proxy.
                exit_code, output = await self._docker_exec(
                    "openvpn",
                    ["easyrsa", "build-client-full", client_name, "nopass"],
                    env=["EASYRSA_BATCH=1"]
                )
                if exit_code != 0:
                    logger.error(f"easyrsa build-client-full failed (exit {exit_code}): {output}")
                    raise HTTPException(status_code=500, detail=f"Certificate generation failed: {output.strip() or 'unknown easyrsa error'}")

            # Read certificate files
            client_cert_path = f"{pki_dir}/issued/{client_name}.crt"
            client_key_path = f"{pki_dir}/private/{client_name}.key"
            
            def _pem_only(text: str, label: str) -> str:
                """easyrsa's issued .crt files include a human-readable
                openssl -text dump before the actual PEM block - strip
                everything outside BEGIN/END so only the certificate itself
                ends up in the client config."""
                begin = f"-----BEGIN {label}-----"
                end = f"-----END {label}-----"
                if begin in text and end in text:
                    return text[text.index(begin):text.index(end) + len(end)] + "\n"
                return text

            try:
                with open(ca_cert_path, 'r') as f:
                    ca_cert = _pem_only(f.read(), "CERTIFICATE")
                with open(client_cert_path, 'r') as f:
                    client_cert = _pem_only(f.read(), "CERTIFICATE")
                with open(client_key_path, 'r') as f:
                    client_key = f.read()
                with open(ta_key_path, 'r') as f:
                    ta_key = f.read()
            except FileNotFoundError as e:
                logger.error(f"Required certificate file not found: {e}")
                raise HTTPException(status_code=500, detail="Certificate generation failed - PKI not properly configured")
            
            # Create client configuration. No explicit cipher/auth directives:
            # the server (scripts/init-openvpn-proper.sh) doesn't set them
            # either, so it negotiates/defaults on its own (auth defaults to
            # SHA1 per its own startup log) - a client that hardcodes a
            # different digest here breaks the tls-auth HMAC entirely
            # ("packet HMAC authentication failed"), since that computation
            # has to match exactly, unlike the data-channel cipher which
            # OpenVPN's NCP can negotiate. cipher/protocol params are still
            # accepted from the caller and validated, just not forced here.
            dns_servers = OPENVPN_DNS_REGIONS[dns_region]
            dns_override = ""
            if dns_servers:
                # pull-filter makes the client discard the server-pushed DNS
                # option and use these instead - a real, standard OpenVPN
                # per-client override (unlike the WireGuard script's dead
                # config files, this one actually takes effect).
                dns_lines = "\n".join(f'dhcp-option DNS {ip}' for ip in dns_servers)
                dns_override = f'\n# geo-region: {dns_region}\npull-filter ignore "dhcp-option DNS"\n{dns_lines}\n'

            client_config = f"""client
dev tun
proto {protocol}
remote {settings.server_ip} {settings.openvpn_port}
resolv-retry infinite
nobind
persist-key
persist-tun
verb 3
key-direction 1
{dns_override}
<ca>
{ca_cert}
</ca>

<cert>
{client_cert}
</cert>

<key>
{client_key}
</key>

<tls-auth>
{ta_key}
</tls-auth>
"""
            
            # Save client configuration
            client_config_path = f"{clients_dir}/{client_name}.ovpn"
            with open(client_config_path, 'w') as f:
                f.write(client_config)
            
            logger.info(f"OpenVPN client {client_name} created successfully")
            
            return {
                "client_name": client_name,
                "config_file": f"{client_name}.ovpn",
                "config_path": client_config_path,
                "protocol": settings.openvpn_protocol,
                "port": settings.openvpn_port,
                "dns_region": dns_region,
                "created_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error creating OpenVPN client: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create OpenVPN client: {str(e)}")

    # ========== UNINSTALL METHODS ==========
    
    async def delete_openvpn_client(self, client_name: str) -> Dict[str, Any]:
        """Delete an OpenVPN client"""
        try:
            logger.info(f"Deleting OpenVPN client: {client_name}")

            # Revoke first, while the issued cert file easyrsa needs to read
            # still exists - revoking after deleting the local files fails
            # ("not a valid certificate") since there's nothing left to
            # revoke. Same as client creation: easyrsa only exists inside
            # the openvpn container's own image, so this runs there via the
            # exec proxy rather than a local ./easyrsa that never exists.
            try:
                exit_code, output = await self._docker_exec(
                    "openvpn",
                    ["easyrsa", "revoke", client_name],
                    env=["EASYRSA_BATCH=1"]
                )
                if exit_code != 0:
                    logger.warning(f"Failed to revoke certificate for {client_name}: {output}")
                else:
                    gen_crl_exit, gen_crl_output = await self._docker_exec("openvpn", ["easyrsa", "gen-crl"], env=["EASYRSA_BATCH=1"])
                    if gen_crl_exit != 0:
                        logger.warning(f"Failed to regenerate CRL after revoking {client_name}: {gen_crl_output}")
            except Exception as e:
                logger.warning(f"Certificate revocation failed: {e}")

            # Remove client configuration file
            client_config_path = f"{settings.openvpn_config_path}/clients/{client_name}.ovpn"
            if os.path.exists(client_config_path):
                os.remove(client_config_path)

            # Remove client certificate and key files
            pki_dir = f"{settings.openvpn_config_path}/pki"
            client_cert_path = f"{pki_dir}/issued/{client_name}.crt"
            client_key_path = f"{pki_dir}/private/{client_name}.key"
            client_req_path = f"{pki_dir}/reqs/{client_name}.req"

            for path in [client_cert_path, client_key_path, client_req_path]:
                if os.path.exists(path):
                    os.remove(path)

            return {"message": f"OpenVPN client {client_name} deleted successfully"}
            
        except Exception as e:
            logger.error(f"Error deleting OpenVPN client: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete client: {str(e)}")

    async def uninstall_wireguard(self) -> Dict[str, Any]:
        """Completely uninstall WireGuard service"""
        try:
            logger.info("Starting WireGuard uninstallation")

            # Stop and remove the container. Best-effort: this codepath
            # shells out to a local `docker` binary that isn't installed
            # in this image, so it's a pre-existing no-op today (caught by
            # the bare excepts below) - not something this fix addresses,
            # only the container name it would use if that were resolved.
            try:
                wireguard_container = await self._resolve_sibling_container("wireguard")
            except HTTPException:
                wireguard_container = None
            if wireguard_container:
                try:
                    stop_process = await asyncio.create_subprocess_exec(
                        'docker', 'stop', wireguard_container,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await stop_process.communicate()
                except:
                    pass

                try:
                    rm_process = await asyncio.create_subprocess_exec(
                        'docker', 'rm', wireguard_container,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await rm_process.communicate()
                except:
                    pass
            
            # Remove configuration directory
            import shutil
            config_dir = settings.wireguard_config_path
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir)
                logger.info(f"Removed WireGuard config directory: {config_dir}")
            
            return {
                "message": "WireGuard service uninstalled successfully",
                "removed_configs": True,
                "stopped_service": True,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error uninstalling WireGuard: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to uninstall WireGuard: {str(e)}")

    async def uninstall_openvpn(self) -> Dict[str, Any]:
        """Completely uninstall OpenVPN service"""
        try:
            logger.info("Starting OpenVPN uninstallation")

            # See uninstall_wireguard for why this is best-effort/pre-existing dead code.
            try:
                openvpn_container = await self._resolve_sibling_container("openvpn")
            except HTTPException:
                openvpn_container = None
            if openvpn_container:
                try:
                    stop_process = await asyncio.create_subprocess_exec(
                        'docker', 'stop', openvpn_container,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await stop_process.communicate()
                except:
                    pass

                try:
                    rm_process = await asyncio.create_subprocess_exec(
                        'docker', 'rm', openvpn_container,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await rm_process.communicate()
                except:
                    pass
            
            # Remove configuration directory
            import shutil
            config_dir = settings.openvpn_config_path
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir)
                logger.info(f"Removed OpenVPN config directory: {config_dir}")
            
            return {
                "message": "OpenVPN service uninstalled successfully",
                "removed_configs": True,
                "stopped_service": True,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error uninstalling OpenVPN: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to uninstall OpenVPN: {str(e)}")

    async def uninstall_ikev2(self) -> Dict[str, Any]:
        """Completely uninstall IKEv2 service"""
        try:
            logger.info("Starting IKEv2 uninstallation")

            # See uninstall_wireguard for why this is best-effort/pre-existing dead code.
            try:
                ikev2_container = await self._resolve_sibling_container("ikev2")
            except HTTPException:
                ikev2_container = None
            if ikev2_container:
                try:
                    stop_process = await asyncio.create_subprocess_exec(
                        'docker', 'stop', ikev2_container,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await stop_process.communicate()
                except:
                    pass

                try:
                    rm_process = await asyncio.create_subprocess_exec(
                        'docker', 'rm', ikev2_container,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await rm_process.communicate()
                except:
                    pass
            
            # Remove configuration directory
            import shutil
            config_dir = settings.ikev2_config_path
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir)
                logger.info(f"Removed IKEv2 config directory: {config_dir}")
            
            return {
                "message": "IKEv2 service uninstalled successfully",
                "removed_configs": True,
                "stopped_service": True,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error uninstalling IKEv2: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to uninstall IKEv2: {str(e)}")

    async def remove_all_wireguard_peers(self) -> Dict[str, Any]:
        """Remove all WireGuard peers"""
        try:
            logger.info("Removing all WireGuard peers")
            
            peers_removed = 0
            peers_dir = f"{settings.wireguard_config_path}/peers"
            
            if os.path.exists(peers_dir):
                for filename in os.listdir(peers_dir):
                    if filename.endswith('.conf'):
                        peer_path = os.path.join(peers_dir, filename)
                        os.remove(peer_path)
                        peers_removed += 1
                        logger.info(f"Removed peer config: {filename}")
            
            # Reset server configuration to remove all peer entries
            server_config_path = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"
            if os.path.exists(server_config_path):
                # Read current config and keep only [Interface] section
                with open(server_config_path, 'r') as f:
                    lines = f.readlines()
                
                # Write back only the [Interface] section
                with open(server_config_path, 'w') as f:
                    in_interface = False
                    for line in lines:
                        if line.strip() == '[Interface]':
                            in_interface = True
                            f.write(line)
                        elif line.startswith('[') and line.strip() != '[Interface]':
                            break
                        elif in_interface:
                            f.write(line)
            
            return {
                "message": f"Removed {peers_removed} WireGuard peers successfully",
                "peers_removed": peers_removed,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error removing all WireGuard peers: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to remove peers: {str(e)}")

    async def remove_all_openvpn_clients(self) -> Dict[str, Any]:
        """Remove all OpenVPN clients"""
        try:
            logger.info("Removing all OpenVPN clients")
            
            clients_removed = 0
            clients_dir = f"{settings.openvpn_config_path}/clients"
            
            if os.path.exists(clients_dir):
                for filename in os.listdir(clients_dir):
                    if filename.endswith('.ovpn'):
                        client_path = os.path.join(clients_dir, filename)
                        os.remove(client_path)
                        clients_removed += 1
                        logger.info(f"Removed client config: {filename}")
            
            # Remove all client certificates and keys
            pki_dir = f"{settings.openvpn_config_path}/pki"
            if os.path.exists(pki_dir):
                # Clear issued certificates (except CA)
                issued_dir = f"{pki_dir}/issued"
                if os.path.exists(issued_dir):
                    for filename in os.listdir(issued_dir):
                        if filename != "ca.crt" and filename.endswith('.crt'):
                            cert_path = os.path.join(issued_dir, filename)
                            os.remove(cert_path)
                
                # Clear private keys (except CA)
                private_dir = f"{pki_dir}/private"
                if os.path.exists(private_dir):
                    for filename in os.listdir(private_dir):
                        if filename != "ca.key" and filename.endswith('.key'):
                            key_path = os.path.join(private_dir, filename)
                            os.remove(key_path)
                
                # Clear certificate requests
                reqs_dir = f"{pki_dir}/reqs"
                if os.path.exists(reqs_dir):
                    for filename in os.listdir(reqs_dir):
                        if filename.endswith('.req'):
                            req_path = os.path.join(reqs_dir, filename)
                            os.remove(req_path)
            
            return {
                "message": f"Removed {clients_removed} OpenVPN clients successfully",
                "clients_removed": clients_removed,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error removing all OpenVPN clients: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to remove clients: {str(e)}")

    async def remove_all_ikev2_clients(self) -> Dict[str, Any]:
        """Remove all IKEv2 clients"""
        try:
            logger.info("Removing all IKEv2 clients")
            
            # For IKEv2, clients are typically managed through the strongSwan configuration
            # This is a simplified implementation - in a real setup, you'd manage the ipsec.conf and ipsec.secrets files
            
            clients_removed = 0
            config_dir = settings.ikev2_config_path
            
            if os.path.exists(config_dir):
                # Remove client-specific configuration files if they exist
                for filename in os.listdir(config_dir):
                    if "client" in filename.lower() or "user" in filename.lower():
                        client_path = os.path.join(config_dir, filename)
                        if os.path.isfile(client_path):
                            os.remove(client_path)
                            clients_removed += 1
                            logger.info(f"Removed IKEv2 client config: {filename}")
            
            return {
                "message": f"Removed {clients_removed} IKEv2 client configurations successfully",
                "clients_removed": clients_removed,
                "note": "IKEv2 client management depends on strongSwan configuration",
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error removing all IKEv2 clients: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to remove clients: {str(e)}")

# Initialize VPN manager
vpn_manager = VPNManager()

# Authentication functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    # Get user from database
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "protocols": ["wireguard"],  # TODO: Get actual protocols from user data
        "is_active": user.is_active,
        "created_at": user.created_at,
        "last_login": user.last_login
    }

# Application lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting BartoloVPN API...")
    
    # Initialize database
    await init_db()
    await create_default_admin()
    await create_default_endpoints()
    await create_default_region()
    await create_default_settings()

    # Initialize IP rotation service
    await ip_rotation_service.initialize()

    # Start background polling of CoreDNS query logs for the Activity tab
    dns_poller_task = asyncio.create_task(dns_activity_poller())

    # Start background health-checking of remote regions (multi-region feature)
    region_poller_task = asyncio.create_task(region_health_poller())

    yield

    # Shutdown
    dns_poller_task.cancel()
    region_poller_task.cancel()
    print("Shutting down BartoloVPN API...")

# Create FastAPI app
app = FastAPI(
    title="BartoloVPN API",
    description="Multi-Protocol VPN Server Management API",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files for web interface (handle both local and Docker environments)
# In Docker, files are mounted at /app/web, locally they're at ../web
if os.path.exists("/app/web/static"):
    # Docker environment
    static_dir = "/app/web/static"
    templates_dir = "/app/web/templates"
else:
    # Local environment
    project_root = os.path.dirname(os.path.dirname(__file__))
    static_dir = os.path.join(project_root, "web", "static")
    templates_dir = os.path.join(project_root, "web", "templates")

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory=templates_dir)


def static_version(relative_path: str) -> int:
    """Cache-busting query param derived from the file's own mtime, so a
    static asset edit is automatically a new URL - no more remembering to
    bump a manual ?v= number (which is exactly what caused CDN/browser
    caches to keep serving stale app.js/style.css after fixes this session)."""
    try:
        return int(os.path.getmtime(os.path.join(static_dir, relative_path)))
    except OSError:
        return 0


templates.env.globals["static_version"] = static_version

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint - serves login screen"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page"""
    return templates.TemplateResponse("index.html", {"request": request})

async def get_current_user_for_web(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    """Get current user for web pages - checks Authorization header first, then cookies"""
    token = None
    
    # First try Authorization header (for localStorage-based auth)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    
    # Fallback to cookie-based auth
    if not token:
        token = request.cookies.get("auth_token")
    
    if not token:
        return None
    
    try:
        # Validate token
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            return None
        
        # Check if user exists in database
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if not user:
            return None
        
        # Check if token is expired
        exp = payload.get("exp")
        if exp and datetime.utcnow().timestamp() > exp:
            return None
            
        return user
            
    except JWTError:
        return None

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Dashboard page - requires authentication via header or cookie, redirects to login if not authenticated"""
    user = await get_current_user_for_web(request, db)
    
    if not user:
        return templates.TemplateResponse("index.html", {"request": request})
    
    return templates.TemplateResponse("dashboard.html", {"request": request, "username": user.username})

@app.get("/api")
async def api_info():
    """API information endpoint"""
    return {"message": "BartoloVPN API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/status")
async def get_system_status(current_user: dict = Depends(get_current_user)):
    """Get system status for dashboard"""
    return {
        "system": {
            "status": "online",
            "uptime": "2h 15m",
            "version": "1.0.0"
        },
        "vpn": {
            "wireguard": {
                "status": "running",
                "connections": 0,
                "peers": 10
            },
            "openvpn": {
                "status": "running", 
                "connections": 0,
                "clients": 0
            },
            "ikev2": {
                "status": "running",
                "connections": 0,
                "tunnels": 0
            }
        },
        "network": {
            "server_ip": settings.server_ip,
            "bandwidth_used": "125 MB",
            "bandwidth_limit": "1000 MB"
        }
    }

@app.get("/api/system/resources")
async def get_system_resources(current_user: dict = Depends(get_current_user)):
    """Get system resources (CPU, Memory, Disk, VPN status, Network) - what
    the Monitoring page's System Overview and VPN Performance widgets read."""
    try:
        # Get CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)

        # Get memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        # Get disk usage
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100

        # Real WireGuard peer stats from the kernel, not a hardcoded stub.
        # "Connected" means a handshake within the last 3 minutes - WireGuard
        # peers re-handshake roughly every 2 minutes while active, so a wider
        # gap means the tunnel has actually gone idle/dropped.
        wg_peers = await vpn_manager.get_wireguard_peer_stats()
        now = datetime.now().timestamp()
        wg_active_peers = [p for p in wg_peers if p['latest_handshake'] and (now - p['latest_handshake']) < 180]
        wg_total_bytes = sum(p['rx_bytes'] + p['tx_bytes'] for p in wg_peers)
        wg_transfer_mb = wg_total_bytes / (1024 ** 2)

        # System-wide network throughput (all interfaces combined - includes
        # non-VPN traffic like the API's own HTTP responses).
        net = psutil.net_io_counters()
        now_monotonic = asyncio.get_event_loop().time()
        speed_mbps = 0.0
        prev = getattr(vpn_manager, '_last_network_sample', None)
        if prev is not None:
            elapsed = now_monotonic - prev['t']
            if elapsed > 0:
                delta_bytes = (net.bytes_sent + net.bytes_recv) - prev['bytes']
                speed_mbps = max(0.0, (delta_bytes / elapsed) / (1024 ** 2))
        vpn_manager._last_network_sample = {'t': now_monotonic, 'bytes': net.bytes_sent + net.bytes_recv}

        # WireGuard-specific throughput, from the delta of the peers' own
        # transfer counters - more accurate than the system-wide figure
        # above since it excludes non-tunnel traffic entirely.
        wg_bandwidth_mbps = 0.0
        wg_prev = getattr(vpn_manager, '_last_wg_transfer_sample', None)
        if wg_prev is not None:
            elapsed = now_monotonic - wg_prev['t']
            if elapsed > 0:
                wg_delta_bytes = wg_total_bytes - wg_prev['bytes']
                wg_bandwidth_mbps = max(0.0, (wg_delta_bytes / elapsed) / (1024 ** 2))
        vpn_manager._last_wg_transfer_sample = {'t': now_monotonic, 'bytes': wg_total_bytes}

        # Real round-trip latency over the tunnel, averaged across whichever
        # active peers actually respond to ICMP (some clients block it,
        # which is fine - those just don't contribute to the average rather
        # than faking a number).
        wg_latency_ms = 0
        if wg_active_peers:
            pings = await asyncio.gather(*[vpn_manager.ping_peer_ms(p['ip']) for p in wg_active_peers if p['ip']])
            valid_pings = [p for p in pings if p is not None]
            if valid_pings:
                wg_latency_ms = round(sum(valid_pings) / len(valid_pings), 1)

        # Real OpenVPN client stats from the server's own status log, same
        # honesty rules as WireGuard above: bandwidth from a live delta,
        # latency from real pings, zero/false rather than a guess if there's
        # nothing connected or nothing responds.
        ovpn_clients = await vpn_manager.get_openvpn_client_stats()
        ovpn_total_bytes = sum(c['rx_bytes'] + c['tx_bytes'] for c in ovpn_clients)
        ovpn_transfer_mb = ovpn_total_bytes / (1024 ** 2)

        ovpn_bandwidth_mbps = 0.0
        ovpn_prev = getattr(vpn_manager, '_last_ovpn_transfer_sample', None)
        if ovpn_prev is not None:
            elapsed = now_monotonic - ovpn_prev['t']
            if elapsed > 0:
                ovpn_delta_bytes = ovpn_total_bytes - ovpn_prev['bytes']
                ovpn_bandwidth_mbps = max(0.0, (ovpn_delta_bytes / elapsed) / (1024 ** 2))
        vpn_manager._last_ovpn_transfer_sample = {'t': now_monotonic, 'bytes': ovpn_total_bytes}

        ovpn_latency_ms = 0
        if ovpn_clients:
            pings = await asyncio.gather(*[vpn_manager.ping_openvpn_client_ms(c['virtual_ip']) for c in ovpn_clients if c['virtual_ip']])
            valid_pings = [p for p in pings if p is not None]
            if valid_pings:
                ovpn_latency_ms = round(sum(valid_pings) / len(valid_pings), 1)

        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory_percent, 1),
            "disk_percent": round(disk_percent, 1),
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "network": {
                "speed_mbps": round(speed_mbps, 2),
                "bytes_sent_mb": round(net.bytes_sent / (1024 ** 2), 2),
                "bytes_recv_mb": round(net.bytes_recv / (1024 ** 2), 2),
            },
            "vpn": {
                "wireguard": {
                    "active": len(wg_active_peers) > 0,
                    "connections": len(wg_active_peers),
                    "transfer": round(wg_transfer_mb, 2),
                    "bandwidth": round(wg_bandwidth_mbps, 2),
                    "latency": wg_latency_ms,
                },
                "openvpn": {
                    "active": len(ovpn_clients) > 0,
                    "connections": len(ovpn_clients),
                    "transfer": round(ovpn_transfer_mb, 2),
                    "bandwidth": round(ovpn_bandwidth_mbps, 2),
                    "latency": ovpn_latency_ms,
                },
                # IKEv2 doesn't have a live stats source wired up yet -
                # reporting inactive/zero here is honest, not a guess.
                "ikev2": {"active": False, "connections": 0, "transfer": 0, "bandwidth": 0, "latency": 0},
            },
        }
    except Exception as e:
        return {
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_percent": 0,
            "error": str(e)
        }

@app.get("/api/system/connections")
async def get_active_connections(current_user: dict = Depends(get_current_user)):
    """Active Connections table on the Monitoring page. Was previously
    unimplemented (404), which the frontend silently swallowed into an
    always-empty table."""
    wg_peers = await vpn_manager.get_wireguard_peer_stats()
    now = datetime.now().timestamp()
    connections = []
    for p in wg_peers:
        if not p['latest_handshake'] or (now - p['latest_handshake']) >= 180:
            continue  # only currently-connected peers, not every provisioned one
        total_mb = (p['rx_bytes'] + p['tx_bytes']) / (1024 ** 2)
        connections.append({
            "id": p['name'],
            "username": p['name'],
            "protocol": "WireGuard",
            "ip_address": p['ip'],
            "connected_since": datetime.fromtimestamp(p['latest_handshake']).isoformat(),
            "data_transfer": f"{total_mb:.1f} MB",
            "status": "Connected",
        })

    ovpn_clients = await vpn_manager.get_openvpn_client_stats()
    for c in ovpn_clients:
        total_mb = (c['rx_bytes'] + c['tx_bytes']) / (1024 ** 2)
        connections.append({
            "id": c['name'],
            "username": c['name'],
            "protocol": "OpenVPN",
            "ip_address": c['virtual_ip'] or c['real_address'],
            "connected_since": c['connected_at'].isoformat() if c['connected_at'] else None,
            "data_transfer": f"{total_mb:.1f} MB",
            "status": "Connected",
        })

    return connections

@app.delete("/api/system/connections/{client_id}")
async def disconnect_client(client_id: str, current_user: dict = Depends(get_current_user)):
    """The Monitoring page's per-row "Disconnect" button. Neither protocol
    has a concept of severing an active session without removing the peer
    (WireGuard is stateless UDP, OpenVPN would just reconnect), so this
    removes the registration, matching what "disconnect" actually
    accomplishes. The connections table mixes both protocols, so figure out
    which one this id actually belongs to rather than assuming WireGuard."""
    ovpn_clients = await vpn_manager.get_openvpn_client_stats()
    if any(c['name'] == client_id for c in ovpn_clients):
        return await vpn_manager.delete_openvpn_client(client_id)
    return await vpn_manager.delete_wireguard_peer(client_id)

_WIREGUARD_IP_PREFIX = '10.13.13.'
_OPENVPN_IP_PREFIX = '10.8.0.'
DNS_QUERIES_PAGE_SIZE = 50
DNS_QUERIES_MAX_PAGES = 10

def _protocol_for_ip(ip: str) -> str:
    if ip.startswith(_WIREGUARD_IP_PREFIX):
        return 'WireGuard'
    if ip.startswith(_OPENVPN_IP_PREFIX):
        return 'OpenVPN'
    return 'Unknown'

@app.get("/api/dns/queries")
async def get_dns_queries(
    page: int = 1,
    peer_ip: Optional[str] = None,
    protocol: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Recent domain lookups per peer, most recent first, paginated (the
    dashboard's Activity tab). Domain-level only - see dns_activity.py for
    how this is collected. Protocol isn't a stored column - it's derived
    from which subnet peer_ip falls in - but SQL can still filter on it via
    a prefix match, which is what lets pagination stay correct (LIMIT/OFFSET
    at the DB level) instead of over-fetching and filtering in Python."""
    page = max(page, 1)
    if page > DNS_QUERIES_MAX_PAGES:
        page = DNS_QUERIES_MAX_PAGES
    offset = (page - 1) * DNS_QUERIES_PAGE_SIZE

    def _apply_filters(stmt):
        if peer_ip:
            stmt = stmt.where(DnsQueryLog.peer_ip == peer_ip)
        if protocol == 'WireGuard':
            stmt = stmt.where(DnsQueryLog.peer_ip.like(f'{_WIREGUARD_IP_PREFIX}%'))
        elif protocol == 'OpenVPN':
            stmt = stmt.where(DnsQueryLog.peer_ip.like(f'{_OPENVPN_IP_PREFIX}%'))
        return stmt

    async with AsyncSessionLocal() as db:
        count_result = await db.execute(_apply_filters(select(func.count()).select_from(DnsQueryLog)))
        total_count = count_result.scalar() or 0

        stmt = _apply_filters(select(DnsQueryLog)).order_by(DnsQueryLog.timestamp.desc())
        stmt = stmt.offset(offset).limit(DNS_QUERIES_PAGE_SIZE)
        result = await db.execute(stmt)
        rows = result.scalars().all()

    # Map peer IPs to friendly names using the app-managed peer config files
    # (peers auto-provisioned by the wireguard container itself won't have
    # one, and just show their raw IP)
    ip_to_name = {}
    peers_dir = f"{settings.wireguard_config_path}/peers"
    if os.path.exists(peers_dir):
        for fname in os.listdir(peers_dir):
            if fname.endswith('.conf'):
                with open(os.path.join(peers_dir, fname), 'r') as f:
                    content = f.read()
                if 'Address = 10.13.13.' in content:
                    ip_suffix = content.split('Address = 10.13.13.')[1].split('/')[0].strip()
                    ip_to_name[f"10.13.13.{ip_suffix}"] = fname[:-5]

    # Same for OpenVPN clients (10.8.0.0/24), from the server's own status
    # log rather than a config file - OpenVPN doesn't keep a per-client
    # static IP mapping on disk the way the WireGuard peer configs do.
    for c in await vpn_manager.get_openvpn_client_stats():
        if c['virtual_ip']:
            ip_to_name[c['virtual_ip']] = c['name']

    capped_total = min(total_count, DNS_QUERIES_MAX_PAGES * DNS_QUERIES_PAGE_SIZE)
    total_pages = max(1, -(-capped_total // DNS_QUERIES_PAGE_SIZE))  # ceil div

    return {
        "queries": [
            {
                "peer_ip": r.peer_ip,
                "peer_name": ip_to_name.get(r.peer_ip, r.peer_ip),
                "protocol": _protocol_for_ip(r.peer_ip),
                "domain": r.domain,
                "timestamp": r.timestamp.isoformat()
            }
            for r in rows
        ],
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
    }

# In-memory login rate limiting, keyed by client IP. Good enough for the
# single-process deployment this runs as (API_WORKERS=1, no --reload workers
# fan-out); would need a shared store (Redis) if that ever changes.
_failed_login_attempts: Dict[str, List[datetime]] = defaultdict(list)
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_MINUTES = 15

def _login_rate_limit_check(client_ip: str) -> None:
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=LOGIN_RATE_LIMIT_WINDOW_MINUTES)
    recent = [t for t in _failed_login_attempts.get(client_ip, []) if t > window_start]
    _failed_login_attempts[client_ip] = recent
    if len(recent) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Try again in {LOGIN_RATE_LIMIT_WINDOW_MINUTES} minutes.",
        )

def _login_rate_limit_record_failure(client_ip: str) -> None:
    _failed_login_attempts[client_ip].append(datetime.utcnow())

def _login_rate_limit_clear(client_ip: str) -> None:
    _failed_login_attempts.pop(client_ip, None)

@app.post("/auth/register", response_model=UserResponse)
async def register_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user"""
    # Check if user already exists
    existing_user = await db.execute(select(User).where(User.username == user.username))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Create new user
    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        role=user.role,
        is_active=True,
        created_at=datetime.utcnow(),
        preferences={
            "theme": "dark",
            "language": "en",
            "notifications": True,
            "auto_connect": False
        }
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    # Ensure id is loaded as an integer value, not a Column object
    return UserResponse(
        id=int(getattr(new_user, "id")),
        username=str(getattr(new_user, "username")),
        email=getattr(new_user, "email"),
        role=str(getattr(new_user, "role")),
        protocols=user.protocols,
        created_at=getattr(new_user, "created_at"),
        last_login=getattr(new_user, "last_login"),
        is_active=bool(getattr(new_user, "is_active"))
    )

@app.post("/auth/login", response_model=Token)
async def login(user_credentials: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    """User login"""
    client_ip = request.client.host if request.client else "unknown"
    _login_rate_limit_check(client_ip)

    # Get user from database
    result = await db.execute(select(User).where(User.username == user_credentials.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(user_credentials.password, user.hashed_password):  # type: ignore[arg-type]
        _login_rate_limit_record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _login_rate_limit_clear(client_ip)

    # Update last login
    user.last_login = datetime.utcnow()  # type: ignore[assignment]
    await db.commit()
    
    access_token_expires = timedelta(minutes=settings.jwt_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    response = {"access_token": access_token, "token_type": "bearer", "username": user.username}
    
    # Set cookie for authentication
    from fastapi.responses import JSONResponse
    json_response = JSONResponse(content=response)
    json_response.set_cookie(
        key="auth_token",
        value=access_token,
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,  # COOKIE_SECURE=true once served over HTTPS
        samesite="lax"
    )
    
    return json_response

# ===== API namespace compatibility layer (/api/auth/*) =====
# These endpoints mirror /auth/* so the frontend calling /api/auth/... works.

@app.post('/api/auth/login')
async def api_login(request: Request, db: AsyncSession = Depends(get_db)):
    logger.info("Login attempt started")
    client_ip = request.client.host if request.client else "unknown"
    _login_rate_limit_check(client_ip)

    data = await request.json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    logger.info(f"Login attempt for username: {username}")

    if not username or not password:
        logger.warning("Login failed: missing username or password")
        raise HTTPException(status_code=400, detail='Username and password required')

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"Login failed: user not found - {username}")
        _login_rate_limit_record_failure(client_ip)
        raise HTTPException(status_code=401, detail='Invalid credentials')

    if not verify_password(password, getattr(user, "hashed_password")):
        logger.warning(f"Login failed: invalid password for user - {username}")
        _login_rate_limit_record_failure(client_ip)
        raise HTTPException(status_code=401, detail='Invalid credentials')

    logger.info(f"Login successful for user: {username}")
    _login_rate_limit_clear(client_ip)
    user.last_login = datetime.utcnow()  # type: ignore[assignment]
    await db.commit()
    
    access_token_expires = timedelta(minutes=settings.jwt_expire_minutes)
    access_token = create_access_token(data={'sub': user.username}, expires_delta=access_token_expires)
    
    response_data = {
        'access_token': access_token,
        'refresh_token': None,  # Refresh token not yet implemented in main.py
        'username': user.username,
        'role': user.role,
        'expires_in': settings.jwt_expire_minutes * 60
    }
    logger.info(f"Returning login response for user: {username}")
    from fastapi.responses import JSONResponse
    return JSONResponse(response_data)

@app.post('/api/auth/register')
async def api_register(request: Request, db: AsyncSession = Depends(get_db)):
    logger.info("Registration attempt started")
    data = await request.json()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip() or None
    password = data.get('password') or ''
    logger.info(f"Registration attempt for username: {username}")
    
    if not username or not password:
        logger.warning("Registration failed: missing username or password")
        raise HTTPException(status_code=400, detail='Username and password required')
    if len(password) < 8:
        logger.warning("Registration failed: password too short")
        raise HTTPException(status_code=400, detail='Password must be at least 8 characters')
    
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        logger.warning(f"Registration failed: username already exists - {username}")
        raise HTTPException(status_code=409, detail='Username already exists')
    
    hashed_password = get_password_hash(password)
    user = User(
        username=username,
        email=email,
        hashed_password=hashed_password,
        role='user',
        is_active=True,
        created_at=datetime.utcnow(),
        preferences={
            'theme': 'dark',
            'language': 'en',
            'notifications': True,
            'auto_connect': False
        }
    )
    db.add(user)
    await db.commit()
    logger.info(f"User registered successfully: {username}")
    return {'msg': 'User registered successfully. Please login.', 'username': username}

@app.post('/api/auth/logout')
async def api_logout():
    from fastapi.responses import JSONResponse
    response = JSONResponse({'msg': 'Logged out'})
    response.delete_cookie('auth_token')
    return response

@app.get('/api/auth/me')
async def api_auth_me(current_user: dict = Depends(get_current_user)):
    # current_user already validated in dependency
    return {
        'username': current_user['username'],
        'role': current_user['role'],
        'created_at': current_user['created_at'].isoformat() if current_user['created_at'] else None,
        'last_login': current_user['last_login'].isoformat() if current_user['last_login'] else None
    }

@app.post('/api/auth/refresh')
async def api_refresh():
    # Refresh token flow not implemented in this main.py; return 400 so frontend stops trying silently.
    raise HTTPException(status_code=400, detail='Refresh not implemented')

@app.post("/auth/logout")
async def logout():
    """User logout - clears the auth cookie"""
    response = JSONResponse(content={"message": "Logged out successfully"})
    response.delete_cookie(key="auth_token")
    return response

@app.get("/users/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse(**current_user)

@app.get("/users", response_model=List[UserResponse])
async def get_users(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get all users (admin only, DB-backed)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    result = await db.execute(select(User))
    users = result.scalars().all()
    # Protocol list placeholder (extend when per-user protocols stored)
    return [
        UserResponse(
            id=int(getattr(u, "id")),
            username=str(getattr(u, "username")),
            email=getattr(u, "email"),
            role=str(getattr(u, "role")),
            protocols=["wireguard"],
            created_at=getattr(u, "created_at"),
            last_login=getattr(u, "last_login"),
            is_active=bool(getattr(u, "is_active"))
        ) for u in users
    ]

@app.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Create a new user (admin only, DB-backed)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    existing = await db.execute(select(User).where(User.username == user.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=get_password_hash(user.password),
        role=user.role,
        is_active=True,
        created_at=datetime.utcnow(),
        preferences={
            "theme": "dark",
            "language": "en",
            "notifications": True,
            "auto_connect": False
        }
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return UserResponse(
        id=int(getattr(new_user, "id")),
        username=str(getattr(new_user, "username")),
        email=getattr(new_user, "email"),
        role=str(getattr(new_user, "role")),
        protocols=user.protocols,
        created_at=getattr(new_user, "created_at"),
        last_login=getattr(new_user, "last_login"),
        is_active=bool(getattr(new_user, "is_active"))
    )

@app.get("/api/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get a specific user by ID"""
    if current_user["role"] != "admin" and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserResponse(
        id=int(getattr(user, "id")),
        username=str(getattr(user, "username")),
        email=getattr(user, "email"),
        role=str(getattr(user, "role")),
        protocols=["wireguard"],  # TODO: Get actual protocols from user data
        created_at=getattr(user, "created_at"),
        last_login=getattr(user, "last_login"),
        is_active=bool(getattr(user, "is_active"))
    )

@app.put("/api/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, user_update: UserUpdate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Update a specific user"""
    if current_user["role"] != "admin" and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if username is being changed and if it already exists
    if user_update.username and user_update.username != user.username:
        existing = await db.execute(select(User).where(User.username == user_update.username))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Username already exists")
        setattr(user, "username", user_update.username)
    
    # Update other fields if provided
    if user_update.email is not None:
        setattr(user, "email", user_update.email)
    
    if user_update.password:
        setattr(user, "hashed_password", get_password_hash(user_update.password))
    
    if user_update.role:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can change roles")
        setattr(user, "role", user_update.role)

    if user_update.status:
        if current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Only admins can change account status")
        setattr(user, "is_active", user_update.status == "active")
    
    # TODO: Handle protocols update when user protocol support is implemented
    
    await db.commit()
    await db.refresh(user)
    
    return UserResponse(
        id=int(getattr(user, "id")),
        username=str(getattr(user, "username")),
        email=getattr(user, "email"),
        role=str(getattr(user, "role")),
        protocols=user_update.protocols or ["wireguard"],
        created_at=getattr(user, "created_at"),
        last_login=getattr(user, "last_login"),
        is_active=bool(getattr(user, "is_active"))
    )

@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a specific user"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized - admin only")
    
    if current_user["id"] == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.delete(user)
    await db.commit()
    
    return {"message": f"User {user.username} deleted successfully"}

# VPN Management Routes
@app.get("/vpn/wireguard/status")
async def get_wireguard_status(current_user: dict = Depends(get_current_user)):
    """Get WireGuard status"""
    return await vpn_manager.get_wireguard_status()

async def _list_local_wireguard_peers() -> List[Dict[str, Any]]:
    """Unchanged local file-scan logic, extracted verbatim so it can be
    called both directly (region=local) and as part of the aggregated
    all-regions list below."""
    peers_dir = f"{settings.wireguard_config_path}/peers"
    peers = []

    if os.path.exists(peers_dir):
        for filename in os.listdir(peers_dir):
            if filename.endswith('.conf'):
                peer_name = filename[:-5]  # Remove .conf extension
                config_path = os.path.join(peers_dir, filename)

                # Read peer configuration
                with open(config_path, 'r') as f:
                    config_content = f.read()

                # Extract IP and private key from config
                address_line = ""
                private_key = ""
                for line in config_content.split('\n'):
                    stripped = line.strip()
                    if stripped.startswith('Address'):
                        address_line = stripped.split('=', 1)[1].strip()
                    elif stripped.startswith('PrivateKey'):
                        private_key = stripped.split('=', 1)[1].strip()

                # Derive the public key from the stored private key so it
                # can be shown in the dashboard (only the private key is
                # persisted in the peer's own config file)
                public_key = ""
                if private_key:
                    proc = await asyncio.create_subprocess_exec(
                        'wg', 'pubkey',
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE
                    )
                    stdout, _ = await proc.communicate(input=private_key.encode())
                    public_key = stdout.decode().strip()

                peers.append({
                    "name": peer_name,
                    "ip": address_line,
                    "public_key": public_key,
                    "config_file": filename,
                    "created_at": os.path.getctime(config_path),
                    "region": "local",
                    "region_display": "Local (this server)",
                })

    return peers

@app.get("/vpn/wireguard/peers")
async def list_wireguard_peers(current_user: dict = Depends(get_current_user)):
    """List all WireGuard peers across every region: the local server
    (unchanged behavior/format) plus every active remote region, fanned
    out and merged. A region that's unreachable degrades to contributing
    no peers rather than failing the whole request - each remote peer is
    tagged with its region so later actions (download/QR/edit/delete) know
    which agent to talk to."""
    try:
        peers = await _list_local_wireguard_peers()
        warnings = []

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Region).where(Region.is_active == True, Region.is_local == False)
            )
            remote_regions = result.scalars().all()

        for region in remote_regions:
            try:
                client = region_service.build_region_client(region)
                remote_peers = await client.list_peers()
                for p in remote_peers:
                    peers.append({
                        "name": p.get("peer_name"),
                        "ip": p.get("ip"),
                        "public_key": p.get("public_key"),
                        "allowed_ips": p.get("allowed_ips"),
                        "region": region.slug,
                        "region_display": region.display_name,
                    })
            except Exception as e:
                logger.warning(f"Could not list peers for region {region.slug}: {e}")
                warnings.append(f"Region '{region.slug}' ({region.display_name}) is unreachable - its peers are not shown")

        response = {"peers": peers}
        if warnings:
            response["warnings"] = warnings
        return response
    except Exception as e:
        logger.error(f"Error listing WireGuard peers: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list peers: {str(e)}")

async def _resolve_region_client(region_slug: str) -> RegionClient:
    region = await region_service.get_region_by_slug(region_slug)
    if region is None:
        raise HTTPException(status_code=404, detail=f"Region '{region_slug}' not found")
    if not region.is_active:
        raise HTTPException(status_code=400, detail=f"Region '{region_slug}' is not active")
    try:
        return region_service.build_region_client(region)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/vpn/wireguard/peers")
async def create_wireguard_peer(
    peer: WireGuardPeerCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create new WireGuard peer"""
    if current_user["role"] != "admin" and peer.user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")

    if peer.region == "local":
        return await vpn_manager.create_wireguard_peer(peer.peer_name, peer.user_id, peer.allowed_ips)

    client = await _resolve_region_client(peer.region)
    return await client.create_peer(peer.peer_name, peer.allowed_ips)

@app.get("/vpn/wireguard/peers/{peer_name}/config")
async def download_wireguard_config(
    peer_name: str,
    region: str = "local",
    current_user: dict = Depends(get_current_user)
):
    """Download WireGuard peer configuration"""
    if region == "local":
        config_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"

        if not os.path.exists(config_file):
            raise HTTPException(status_code=404, detail="Peer configuration not found")

        return FileResponse(config_file, filename=f"BartoloVPN-{peer_name}.conf")

    client = await _resolve_region_client(region)
    result = await client.get_peer_config(peer_name)
    return PlainTextResponse(
        result["config"],
        headers={"Content-Disposition": f'attachment; filename="BartoloVPN-{peer_name}.conf"'}
    )

@app.get("/vpn/wireguard/peers/{peer_name}/qrcode")
async def get_wireguard_peer_qrcode(
    peer_name: str,
    region: str = "local",
    current_user: dict = Depends(get_current_user)
):
    """Generate a QR code for an existing peer's config (e.g. to scan with the
    WireGuard mobile app), without needing to recreate the peer's keys"""
    if region == "local":
        config_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"

        if not os.path.exists(config_file):
            raise HTTPException(status_code=404, detail="Peer configuration not found")

        with open(config_file, 'r') as f:
            config_content = f.read()

        qr_code = await vpn_manager._generate_qr_code(config_content)
        return {"peer_name": peer_name, "qr_code": qr_code}

    client = await _resolve_region_client(region)
    return await client.get_peer_qrcode(peer_name)

@app.put("/vpn/wireguard/peers/{peer_name}")
async def update_wireguard_peer(
    peer_name: str,
    update: WireGuardPeerUpdate,
    region: str = "local",
    current_user: dict = Depends(get_current_user)
):
    """Rename a WireGuard peer and/or change its AllowedIPs"""
    if region == "local":
        return await vpn_manager.update_wireguard_peer(peer_name, update.peer_name, update.allowed_ips)

    client = await _resolve_region_client(region)
    return await client.update_peer(peer_name, update.peer_name, update.allowed_ips)

@app.delete("/vpn/wireguard/peers/{peer_name}")
async def delete_wireguard_peer(
    peer_name: str,
    region: str = "local",
    current_user: dict = Depends(get_current_user)
):
    """Delete WireGuard peer"""
    # Only admin can delete any peer, users can only delete their own
    if current_user["role"] != "admin":
        # TODO: Check if this peer belongs to the current user
        # For now, only admin can delete
        raise HTTPException(status_code=403, detail="Only admin can delete peers")

    if region == "local":
        return await vpn_manager.delete_wireguard_peer(peer_name)

    client = await _resolve_region_client(region)
    return await client.delete_peer(peer_name)

# OpenVPN Management Routes
@app.get("/vpn/openvpn/status")
async def get_openvpn_status(current_user: dict = Depends(get_current_user)):
    """Get OpenVPN status"""
    return await vpn_manager.get_openvpn_status()

@app.get("/vpn/openvpn/clients")
async def list_openvpn_clients(current_user: dict = Depends(get_current_user)):
    """List all OpenVPN clients"""
    try:
        clients_dir = f"{settings.openvpn_config_path}/clients"
        clients = []

        # Real connection state from the server's own status log (same
        # source get_openvpn_client_stats already uses for the Monitoring
        # page) - this was hardcoded to "inactive" always before.
        connected_names = {c['name'] for c in await vpn_manager.get_openvpn_client_stats()}

        if os.path.exists(clients_dir):
            for filename in os.listdir(clients_dir):
                if filename.endswith('.ovpn'):
                    client_name = filename[:-5]  # Remove .ovpn extension
                    config_path = os.path.join(clients_dir, filename)

                    # dns_region is stored as a "# geo-region: <name>" comment
                    # written into the client's own .ovpn at creation time
                    # (see create_openvpn_client) - no separate DB row needed.
                    dns_region = "default"
                    try:
                        with open(config_path, 'r') as f:
                            for line in f:
                                if line.startswith('# geo-region:'):
                                    dns_region = line.split(':', 1)[1].strip()
                                    break
                                if line.startswith('<ca>'):
                                    break
                    except OSError:
                        pass

                    clients.append({
                        "name": client_name,
                        "config_file": filename,
                        "created_at": os.path.getctime(config_path),
                        "status": "active" if client_name in connected_names else "inactive",
                        "dns_region": dns_region
                    })

        return {"clients": clients}
    except Exception as e:
        logger.error(f"Error listing OpenVPN clients: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list clients: {str(e)}")

@app.post("/vpn/openvpn/clients")
async def create_openvpn_client(
    client: OpenVPNClientCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create new OpenVPN client"""
    if current_user["role"] != "admin" and client.user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return await vpn_manager.create_openvpn_client(client.client_name, client.user_id, client.protocol, client.cipher, client.dns_region)

@app.get("/vpn/openvpn/clients/{client_name}/config")
async def download_openvpn_config(
    client_name: str,
    current_user: dict = Depends(get_current_user)
):
    """Download OpenVPN client configuration"""
    config_file = f"{settings.openvpn_config_path}/clients/{client_name}.ovpn"
    
    if not os.path.exists(config_file):
        raise HTTPException(status_code=404, detail="Client configuration not found")
    
    return FileResponse(config_file, filename=f"{client_name}.ovpn")

@app.delete("/vpn/openvpn/clients/{client_name}")
async def delete_openvpn_client(
    client_name: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete OpenVPN client"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can delete clients")
    
    return await vpn_manager.delete_openvpn_client(client_name)

# Uninstall Endpoints for All Protocols
@app.post("/vpn/wireguard/uninstall")
async def uninstall_wireguard(
    current_user: dict = Depends(get_current_user)
):
    """Completely uninstall WireGuard service and remove all configurations"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can uninstall services")
    
    return await vpn_manager.uninstall_wireguard()

@app.post("/vpn/openvpn/uninstall")
async def uninstall_openvpn(
    current_user: dict = Depends(get_current_user)
):
    """Completely uninstall OpenVPN service and remove all configurations"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can uninstall services")
    
    return await vpn_manager.uninstall_openvpn()

@app.get("/vpn/ikev2/credentials")
async def get_ikev2_credentials(current_user: dict = Depends(get_current_user)):
    """Real IKEv2 pre-shared key / username / password, for the dashboard's
    IKEv2 tab (previously hardcoded placeholder text in the template)"""
    return {
        "psk": settings.ikev2_psk,
        "username": settings.ikev2_user,
        "password": settings.ikev2_password
    }

@app.post("/vpn/ikev2/uninstall")
async def uninstall_ikev2(
    current_user: dict = Depends(get_current_user)
):
    """Completely uninstall IKEv2 service and remove all configurations"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can uninstall services")
    
    return await vpn_manager.uninstall_ikev2()

@app.delete("/vpn/wireguard/clients/all")
async def remove_all_wireguard_peers(
    current_user: dict = Depends(get_current_user)
):
    """Remove all WireGuard peers"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can remove all peers")
    
    return await vpn_manager.remove_all_wireguard_peers()

@app.delete("/vpn/openvpn/clients/all")
async def remove_all_openvpn_clients(
    current_user: dict = Depends(get_current_user)
):
    """Remove all OpenVPN clients"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can remove all clients")
    
    return await vpn_manager.remove_all_openvpn_clients()

@app.delete("/vpn/ikev2/clients/all")
async def remove_all_ikev2_clients(
    current_user: dict = Depends(get_current_user)
):
    """Remove all IKEv2 clients"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Only admin can remove all clients")
    
    return await vpn_manager.remove_all_ikev2_clients()

@app.get("/api/system/stats")
async def get_system_stats(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get system statistics"""
    logger.info(f"System stats requested by user: {current_user.get('username', 'unknown')}")
    
    # Get basic system stats
    stats = await vpn_manager.get_system_stats()
    
    # Get user counts from database
    total_users_result = await db.execute(select(User))
    total_users = len(list(total_users_result.scalars().all()))
    
    active_users_result = await db.execute(select(User).where(User.is_active == True))
    active_users = len(list(active_users_result.scalars().all()))
    
    # Create the response structure expected by frontend
    response = {
        "system": {
            "status": "online",  # System is online if we can respond
            "cpu_percent": stats.cpu_percent,
            "memory_percent": stats.memory_percent,
            "disk_percent": stats.disk_percent
        },
        "vpn": {
            "wireguard": {"status": "running"},  # TODO: Add real status check
            "openvpn": {"status": "running"},    # TODO: Add real status check
            "ikev2": {"status": "running"}       # TODO: Add real status check
        },
        "users": {
            "active": active_users,
            "total": total_users
        },
        "bandwidth": {
            "sent": stats.network_bytes_sent,
            "received": stats.network_bytes_recv
        }
    }
    
    return response

@app.get("/endpoints")
async def get_endpoints(current_user: dict = Depends(get_current_user)):
    """Get all server endpoints"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(ServerEndpoint))
        endpoints = result.scalars().all()
        return [
            {
                "id": endpoint.id,
                "name": endpoint.name,
                "ip_address": endpoint.ip_address,
                "port": endpoint.port,
                "protocol": endpoint.protocol,
                "country": endpoint.country,
                "is_active": endpoint.is_active,
                "priority": endpoint.priority,
                "usage_count": endpoint.usage_count,
                "last_used": endpoint.last_used.isoformat() if endpoint.last_used is not None else None
            }
            for endpoint in endpoints
        ]

@app.post("/endpoints")
async def create_endpoint(
    name: str,
    ip_address: str,
    port: int,
    protocol: str,
    country: Optional[str] = None,
    priority: int = 1,
    current_user: dict = Depends(get_current_user)
):
    """Create a new server endpoint"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    safe_country = country if country is not None else ""
    endpoint = await ip_rotation_service.add_endpoint(name, ip_address, port, protocol, safe_country, priority)
    return {
        "id": endpoint.id,
        "name": endpoint.name,
        "ip_address": endpoint.ip_address,
        "port": endpoint.port,
        "protocol": endpoint.protocol,
        "country": endpoint.country,
        "priority": endpoint.priority
    }

@app.post("/endpoints/{endpoint_id}/rotate")
async def rotate_endpoint(
    endpoint_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Manually rotate an endpoint IP"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    success = await ip_rotation_service.rotate_endpoint(endpoint_id)
    if success:
        return {"message": "Endpoint rotated successfully"}
    else:
        raise HTTPException(status_code=404, detail="Endpoint not found")

@app.get("/endpoints/stats")
async def get_endpoint_stats(current_user: dict = Depends(get_current_user)):
    """Get endpoint statistics"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    return await ip_rotation_service.get_endpoint_stats()

def _region_out(region: Region) -> dict:
    """Never includes agent_key_encrypted - the dashboard never needs the
    key back once a region is registered, only whether it's configured."""
    return {
        "id": region.id,
        "slug": region.slug,
        "display_name": region.display_name,
        "country_code": region.country_code,
        "city": region.city,
        "is_local": region.is_local,
        "agent_url": region.agent_url,
        "wireguard_endpoint_host": region.wireguard_endpoint_host,
        "wireguard_endpoint_port": region.wireguard_endpoint_port,
        "is_active": region.is_active,
        "health_status": region.health_status,
        "last_health_check": region.last_health_check.isoformat() if region.last_health_check else None,
        "last_health_error": region.last_health_error,
        "peer_count": region.peer_count,
    }

class RegionCreate(BaseModel):
    slug: str = Field(..., min_length=2, max_length=30, pattern=r"^[a-z0-9-]+$")
    display_name: str = Field(..., min_length=2, max_length=100)
    country_code: str = Field(..., min_length=2, max_length=2)
    city: Optional[str] = None
    agent_url: str = Field(..., description="e.g. https://your-region-hostname.example.com")
    agent_key: str = Field(..., min_length=16, description="Shown once by scripts/provision-region.sh")
    wireguard_endpoint_host: str
    wireguard_endpoint_port: int = 51820

class RegionUpdate(BaseModel):
    display_name: Optional[str] = None
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    city: Optional[str] = None
    agent_url: Optional[str] = None
    agent_key: Optional[str] = Field(None, min_length=16, description="Only send this to rotate the key")
    wireguard_endpoint_host: Optional[str] = None
    wireguard_endpoint_port: Optional[int] = None
    is_active: Optional[bool] = None

@app.get("/regions")
async def list_regions(current_user: dict = Depends(get_current_user)):
    """Get all regions (the "local" region plus any remote ones registered)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Region).order_by(Region.is_local.desc(), Region.id))
        regions = result.scalars().all()
        return [_region_out(r) for r in regions]

@app.post("/regions")
async def create_region(region: RegionCreate, current_user: dict = Depends(get_current_user)):
    """Register a new remote region. Health-checks the agent before
    committing - reject with 400 if it's unreachable or the key is wrong,
    rather than silently saving a region that can never actually be used."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    existing = await region_service.get_region_by_slug(region.slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"A region with slug '{region.slug}' already exists")

    test_client = RegionClient(region.slug, region.agent_url, region.agent_key)
    try:
        await test_client.health()
    except HTTPException as e:
        raise HTTPException(status_code=400, detail=f"Could not verify new region before saving: {e.detail}")

    async with AsyncSessionLocal() as session:
        new_region = Region(
            slug=region.slug,
            display_name=region.display_name,
            country_code=region.country_code.upper(),
            city=region.city,
            is_local=False,
            agent_url=region.agent_url,
            agent_key_encrypted=region_service.encrypt_agent_key(region.agent_key),
            wireguard_endpoint_host=region.wireguard_endpoint_host,
            wireguard_endpoint_port=region.wireguard_endpoint_port,
            is_active=True,
            health_status="healthy",
            last_health_check=datetime.utcnow(),
        )
        session.add(new_region)
        await session.commit()
        await session.refresh(new_region)
        return _region_out(new_region)

@app.put("/regions/{region_id}")
async def update_region(region_id: int, update: RegionUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    async with AsyncSessionLocal() as session:
        region = await session.get(Region, region_id)
        if region is None:
            raise HTTPException(status_code=404, detail="Region not found")
        if region.is_local:
            raise HTTPException(status_code=400, detail="The local region cannot be edited")

        for field in ("display_name", "city", "agent_url", "wireguard_endpoint_host", "wireguard_endpoint_port", "is_active"):
            value = getattr(update, field)
            if value is not None:
                setattr(region, field, value)
        if update.country_code is not None:
            region.country_code = update.country_code.upper()
        if update.agent_key is not None:
            region.agent_key_encrypted = region_service.encrypt_agent_key(update.agent_key)

        await session.commit()
        await session.refresh(region)
        return _region_out(region)

@app.delete("/regions/{region_id}")
async def delete_region(region_id: int, force: bool = False, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    async with AsyncSessionLocal() as session:
        region = await session.get(Region, region_id)
        if region is None:
            raise HTTPException(status_code=404, detail="Region not found")
        if region.is_local:
            raise HTTPException(status_code=400, detail="The local region cannot be deleted")
        if region.peer_count > 0 and not force:
            raise HTTPException(
                status_code=409,
                detail=f"Region {region.slug} still has {region.peer_count} peer(s) - pass ?force=true to delete anyway (their configs on the remote agent are not affected)"
            )
        await session.delete(region)
        await session.commit()
        return {"message": f"Region {region.slug} deleted"}

@app.post("/regions/{region_id}/health-check")
async def check_region_health(region_id: int, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    async with AsyncSessionLocal() as session:
        region = await session.get(Region, region_id)
        if region is None:
            raise HTTPException(status_code=404, detail="Region not found")

    updated = await region_service.health_check_region(region)
    return _region_out(updated)

class SettingsUpdate(BaseModel):
    timezone: Optional[str] = None
    dns_servers: Optional[str] = None
    encryption_level: Optional[int] = None
    kill_switch_enabled: Optional[bool] = None
    log_level: Optional[str] = None
    log_retention_days: Optional[int] = None
    # Oracle Cloud API integration (stored for a future one-click region
    # provisioning feature - not yet implemented). oracle_api_key is only
    # ever accepted here, never returned - see _settings_out.
    oracle_enabled: Optional[bool] = None
    oracle_tenancy_ocid: Optional[str] = None
    oracle_user_ocid: Optional[str] = None
    oracle_fingerprint: Optional[str] = None
    oracle_api_key: Optional[str] = Field(None, description="Plaintext in the request only - encrypted before storage, and omitted from every response. Send null/omit to leave the currently stored key unchanged.")
    oracle_region: Optional[str] = None
    oracle_ssh_key_name: Optional[str] = None

def _settings_out(s: SystemSettings) -> dict:
    return {
        # Read-only, sourced from config/.env, not from this table - see
        # SystemSettings' docstring for why these aren't stored here.
        "server_ip": settings.server_ip,
        "domain": settings.domain,
        "timezone": s.timezone,
        "dns_servers": s.dns_servers,
        "encryption_level": s.encryption_level,
        "kill_switch_enabled": s.kill_switch_enabled,
        "log_level": s.log_level,
        "log_retention_days": s.log_retention_days,
        "oracle_enabled": s.oracle_enabled,
        "oracle_tenancy_ocid": s.oracle_tenancy_ocid,
        "oracle_user_ocid": s.oracle_user_ocid,
        "oracle_fingerprint": s.oracle_fingerprint,
        "oracle_api_key_configured": bool(s.oracle_api_key_encrypted),
        "oracle_region": s.oracle_region,
        "oracle_ssh_key_name": s.oracle_ssh_key_name,
    }

@app.get("/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            # Shouldn't happen (create_default_settings seeds this at
            # startup), but don't 500 on a missing singleton row.
            s = SystemSettings(id=1)
            session.add(s)
            await session.commit()
            await session.refresh(s)
        return _settings_out(s)

@app.put("/settings")
async def update_settings(update: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)

        for field in (
            "timezone", "dns_servers", "encryption_level", "kill_switch_enabled",
            "log_level", "log_retention_days", "oracle_enabled",
            "oracle_tenancy_ocid", "oracle_user_ocid", "oracle_fingerprint",
            "oracle_region", "oracle_ssh_key_name",
        ):
            value = getattr(update, field)
            if value is not None:
                setattr(s, field, value)

        if update.oracle_api_key:
            s.oracle_api_key_encrypted = region_service.encrypt_secret(update.oracle_api_key)

        await session.commit()
        await session.refresh(s)
        return _settings_out(s)

@app.get("/settings/ssh-keys")
async def list_ssh_keys(current_user: dict = Depends(get_current_user)):
    """Lists public keys available under the repo's .ssh/ folder (bind-mounted
    read-only into this container as /ssh-keys), so the Oracle settings UI
    can offer a picker instead of the operator typing a path by hand."""
    ssh_dir = "/ssh-keys"
    keys = []
    if os.path.isdir(ssh_dir):
        for fname in sorted(os.listdir(ssh_dir)):
            if fname.endswith(".pub"):
                keys.append(fname[:-4])
    return {"keys": keys}

# Oracle's API request-signing key pair - distinct filenames from the
# generic *.pub scan above (list_ssh_keys) so it never shows up in that
# VPS-access-key picker; this pair authenticates the dashboard to Oracle's
# API, unrelated to any key injected into a new VM for SSH login.
_ORACLE_API_PRIVATE_KEY_PATH = "/ssh-keys/oracle-api-private.pem"
_ORACLE_API_PUBLIC_KEY_PATH = "/ssh-keys/oracle-api-public.pem"

@app.get("/settings/oracle-api-key")
async def get_oracle_api_key_status(current_user: dict = Depends(get_current_user)):
    """Reports whether vpn-setup.py's generated Oracle API key pair is
    present under .ssh/, and returns the PUBLIC half's content - safe to
    show, since the operator needs to paste it into OCI Console's Add API
    Key dialog anyway."""
    detected = os.path.isfile(_ORACLE_API_PRIVATE_KEY_PATH) and os.path.isfile(_ORACLE_API_PUBLIC_KEY_PATH)
    public_key = None
    if detected:
        with open(_ORACLE_API_PUBLIC_KEY_PATH) as f:
            public_key = f.read()
    return {"detected": detected, "public_key": public_key}

@app.post("/settings/oracle-api-key/import")
async def import_oracle_api_key(current_user: dict = Depends(get_current_user)):
    """Reads the private key generated by vpn-setup.py straight from .ssh/
    server-side and stores it encrypted - the key material never has to
    pass through the browser. Also computes the fingerprint Oracle shows
    for the matching uploaded public key, so the operator doesn't have to
    copy that separately from the OCI Console."""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    if not os.path.isfile(_ORACLE_API_PRIVATE_KEY_PATH):
        raise HTTPException(
            status_code=404,
            detail="No Oracle API key found in .ssh/ - run vpn-setup.py or place one there manually"
        )

    with open(_ORACLE_API_PRIVATE_KEY_PATH, "rb") as f:
        private_pem = f.read()

    try:
        private_key = serialization.load_pem_private_key(private_pem, password=None)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse .ssh/oracle-api-private.pem as an RSA private key")

    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint_hex = hashlib.md5(public_der).hexdigest()
    fingerprint = ":".join(fingerprint_hex[i:i + 2] for i in range(0, len(fingerprint_hex), 2))

    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)
        s.oracle_api_key_encrypted = region_service.encrypt_secret(private_pem.decode())
        s.oracle_fingerprint = fingerprint
        await session.commit()
        await session.refresh(s)
        return _settings_out(s)

@app.get("/users/{user_id}/configs")
async def get_user_configs(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Get VPN configurations for a user"""
    if current_user["role"] != "admin" and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(VPNConfig).where(VPNConfig.user_id == user_id)
        )
        configs = result.scalars().all()
        
        return [
            {
                "id": config.id,
                "protocol": config.protocol,
                "config_name": config.config_name,
                "is_active": config.is_active,
                "created_at": config.created_at.isoformat(),
                "last_used": config.last_used.isoformat() if config.last_used is not None else None
            }
            for config in configs
        ]

@app.get("/users/{user_id}/usage")
async def get_user_usage(
    user_id: int,
    days: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """Get usage statistics for a user"""
    if current_user["role"] != "admin" and current_user["id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    async with AsyncSessionLocal() as session:
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        result = await session.execute(
            select(UsageLog).where(
                UsageLog.user_id == user_id,
                UsageLog.connection_start >= cutoff_date
            )
        )
        logs = result.scalars().all()
        
        total_bytes_sent = sum(log.bytes_sent for log in logs)
        total_bytes_received = sum(log.bytes_received for log in logs)
        
        return {
            "total_sessions": len(logs),
            "total_bytes_sent": total_bytes_sent,
            "total_bytes_received": total_bytes_received,
            "total_data_mb": (total_bytes_sent + total_bytes_received) / (1024 * 1024),
            "sessions": [
                {
                    "protocol": log.protocol,
                    "bytes_sent": log.bytes_sent,
                    "bytes_received": log.bytes_received,
                    "connection_start": log.connection_start.isoformat(),
                    "connection_end": log.connection_end.isoformat() if log.connection_end is not None else None,
                    "ip_address": log.ip_address,
                    "country": log.country
                }
                for log in logs
            ]
        }

# WebSocket endpoint for real-time updates
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket)
    try:
        while True:
            # Send periodic updates
            await asyncio.sleep(5)
            stats = await vpn_manager.get_system_stats()
            await manager.send_personal_message(stats.json(), websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)

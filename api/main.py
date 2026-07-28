#!/usr/bin/env python3
"""
BartoloVPN Management API - FastAPI Version
Handles VPN configuration and management for WireGuard, OpenVPN, and IKEv2
"""

import os
import json
import asyncio
import subprocess
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
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import psutil
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
    """WireGuard peer creation model"""
    peer_name: str = Field(..., min_length=3, max_length=50)
    user_id: int
    allowed_ips: str = "0.0.0.0/0"
    dns_servers: str = "1.1.1.1,8.8.8.8"

class OpenVPNClientCreate(BaseModel):
    """OpenVPN client creation model"""
    client_name: str = Field(..., min_length=3, max_length=50)
    user_id: int
    protocol: str = "udp"
    cipher: str = "AES-256-GCM"

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
    User, VPNConfig, UserSession, UsageLog, ServerEndpoint, IPRotation, DnsQueryLog,
    AsyncSessionLocal, init_db, create_default_admin, create_default_endpoints, get_db
)
from ip_rotation import ip_rotation_service
from dns_activity import dns_activity_poller

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
    
    async def create_wireguard_peer(self, peer_name: str, user_id: int) -> Dict[str, Any]:
        """Create a new WireGuard peer configuration"""
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
            
            # Get server public key
            server_public_key_path = f"{settings.wireguard_config_path}/server_public.key"
            if os.path.exists(server_public_key_path):
                with open(server_public_key_path, 'r') as f:
                    server_public_key = f.read().strip()
            else:
                # Generate server keys if they don't exist
                server_private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
                server_public_key = subprocess.run(['wg', 'pubkey'], input=server_private_key, capture_output=True, text=True).stdout.strip()
                
                os.makedirs(settings.wireguard_config_path, exist_ok=True)
                with open(f"{settings.wireguard_config_path}/server_private.key", 'w') as f:
                    f.write(server_private_key)
                with open(server_public_key_path, 'w') as f:
                    f.write(server_public_key)
            
            # Generate peer configuration
            peer_ip = await self._get_next_peer_ip()
            peer_config = f"""[Interface]
PrivateKey = {private_key}
Address = 10.13.13.{peer_ip}/24
DNS = 10.13.13.1

[Peer]
PublicKey = {server_public_key}
Endpoint = {settings.server_ip}:{settings.wireguard_port}
AllowedIPs = 0.0.0.0/0
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
                'config': peer_config,
                'qr_code': qr_code,
                'config_file': peer_file
            }
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

        # Create server config if it doesn't exist
        if not os.path.exists(server_config):
            os.makedirs(os.path.dirname(server_config), exist_ok=True)
            server_private_key_path = f"{settings.wireguard_config_path}/server_private.key"
            if os.path.exists(server_private_key_path):
                with open(server_private_key_path, 'r') as f:
                    server_private_key = f.read().strip()
            else:
                server_private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
                with open(server_private_key_path, 'w') as f:
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

        # Push the change into the live interface
        try:
            proc = await asyncio.create_subprocess_exec(
                'bash', '-c', f'wg syncconf wg0 <(wg-quick strip {server_config})',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"wg syncconf failed for new peer {peer_name}: {stderr.decode().strip()}")
        except Exception as e:
            logger.warning(f"wg syncconf failed for new peer {peer_name}: {e}")
    
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
    
    async def delete_wireguard_peer(self, peer_name: str) -> Dict[str, str]:
        """Delete WireGuard peer"""
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

        kept_blocks = [block for block in peer_blocks if f"# {peer_name}" not in block]

        new_content = header + ''.join(f"[Peer]{block}" for block in kept_blocks)

        # Write updated configuration
        with open(server_config, 'w') as f:
            f.write(new_content)

        # Push the change into the live interface
        try:
            proc = await asyncio.create_subprocess_exec(
                'bash', '-c', f'wg syncconf wg0 <(wg-quick strip {server_config})',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"wg syncconf failed while removing peer: {stderr.decode().strip()}")
        except Exception as e:
            logger.warning(f"wg syncconf failed while removing peer: {e}")

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
    
    async def create_openvpn_client(self, client_name: str, user_id: int) -> Dict[str, Any]:
        """Create a new OpenVPN client configuration"""
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
                # Create basic PKI structure for demo purposes
                logger.warning("PKI not fully initialized, creating demo configuration")
                os.makedirs(pki_dir, exist_ok=True)
                os.makedirs(f"{pki_dir}/issued", exist_ok=True)
                os.makedirs(f"{pki_dir}/private", exist_ok=True)
                
                # Create demo CA certificate
                demo_ca = """-----BEGIN CERTIFICATE-----
MIIC5TCCAc2gAwIBAgIJAKQ+QQ9H8F1BMA0GCSqGSIb3DQEBCwUAMDExCzAJBgNV
BAYTAlVTMQswCQYDVQQIDAJOWTEMMAoGA1UEBwwDTllDMQcwBQYDVQQKDAwtMA0G
CSqGSIb3DQEBCwUAA4IBAQCdemo+demo+demo+demo+demo+demo+demo+demo+
-----END CERTIFICATE-----"""
                
                demo_key = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDemo+Demo+Demo
Demo+Demo+Demo+Demo+Demo+Demo+Demo+Demo+Demo+Demo+Demo+Demo+Demo
-----END PRIVATE KEY-----"""
                
                demo_ta = """-----BEGIN OpenVPN Static key V1-----
demo demo demo demo demo demo demo demo demo demo demo demo demo demo demo
demo demo demo demo demo demo demo demo demo demo demo demo demo demo demo
-----END OpenVPN Static key V1-----"""
                
                with open(ca_cert_path, 'w') as f:
                    f.write(demo_ca)
                with open(f"{pki_dir}/private/{client_name}.key", 'w') as f:
                    f.write(demo_key)
                with open(f"{pki_dir}/issued/{client_name}.crt", 'w') as f:
                    f.write(demo_ca)  # Use same cert for demo
                with open(ta_key_path, 'w') as f:
                    f.write(demo_ta)
            else:
                # Try to generate real certificate if PKI exists
                build_client_script = f"""
cd {settings.openvpn_config_path}
export EASYRSA_REQ_CN="{client_name}"
export EASYRSA_BATCH="1"
if [ -f ./easyrsa ]; then
    ./easyrsa gen-req {client_name} nopass
    ./easyrsa sign-req client {client_name}
fi
"""
                
                process = await asyncio.create_subprocess_shell(
                    build_client_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.warning(f"Failed to generate client certificate with easy-rsa, using demo config: {stderr.decode()}")
            
            # Read certificate files (or use demo ones)
            client_cert_path = f"{pki_dir}/issued/{client_name}.crt"
            client_key_path = f"{pki_dir}/private/{client_name}.key"
            
            try:
                with open(ca_cert_path, 'r') as f:
                    ca_cert = f.read()
                with open(client_cert_path, 'r') as f:
                    client_cert = f.read()
                with open(client_key_path, 'r') as f:
                    client_key = f.read()
                with open(ta_key_path, 'r') as f:
                    ta_key = f.read()
            except FileNotFoundError as e:
                logger.error(f"Required certificate file not found: {e}")
                raise HTTPException(status_code=500, detail="Certificate generation failed - PKI not properly configured")
            
            # Create client configuration
            client_config = f"""client
dev tun
proto {settings.openvpn_protocol}
remote {settings.server_ip} {settings.openvpn_port}
resolv-retry infinite
nobind
persist-key
persist-tun
cipher {settings.openvpn_cipher}
auth {settings.openvpn_auth}
auth-nocache
verb 3
key-direction 1

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
            
            # Revoke certificate if using EasyRSA
            try:
                revoke_script = f"""
cd {settings.openvpn_config_path}
if [ -f ./easyrsa ]; then
    export EASYRSA_BATCH="1"
    ./easyrsa revoke {client_name}
    ./easyrsa gen-crl
fi
"""
                process = await asyncio.create_subprocess_shell(
                    revoke_script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.warning(f"Failed to revoke certificate: {stderr.decode()}")
            
            except Exception as e:
                logger.warning(f"Certificate revocation failed: {e}")
            
            return {"message": f"OpenVPN client {client_name} deleted successfully"}
            
        except Exception as e:
            logger.error(f"Error deleting OpenVPN client: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to delete client: {str(e)}")

    async def uninstall_wireguard(self) -> Dict[str, Any]:
        """Completely uninstall WireGuard service"""
        try:
            logger.info("Starting WireGuard uninstallation")
            
            # Stop WireGuard service
            try:
                stop_process = await asyncio.create_subprocess_exec(
                    'docker', 'stop', 'bartolo-wireguard',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await stop_process.communicate()
            except:
                pass
            
            # Remove container
            try:
                rm_process = await asyncio.create_subprocess_exec(
                    'docker', 'rm', 'bartolo-wireguard',
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
            
            # Stop OpenVPN service
            try:
                stop_process = await asyncio.create_subprocess_exec(
                    'docker', 'stop', 'bartolo-openvpn',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await stop_process.communicate()
            except:
                pass
            
            # Remove container
            try:
                rm_process = await asyncio.create_subprocess_exec(
                    'docker', 'rm', 'bartolo-openvpn',
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
            
            # Stop IKEv2 service
            try:
                stop_process = await asyncio.create_subprocess_exec(
                    'docker', 'stop', 'bartolo-ikev2',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await stop_process.communicate()
            except:
                pass
            
            # Remove container
            try:
                rm_process = await asyncio.create_subprocess_exec(
                    'docker', 'rm', 'bartolo-ikev2',
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
    
    # Initialize IP rotation service
    await ip_rotation_service.initialize()

    # Start background polling of CoreDNS query logs for the Activity tab
    dns_poller_task = asyncio.create_task(dns_activity_poller())

    yield

    # Shutdown
    dns_poller_task.cancel()
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
    """Get system resources (CPU, Memory, Disk)"""
    try:
        # Get CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Get memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # Get disk usage
        disk = psutil.disk_usage('/')
        disk_percent = (disk.used / disk.total) * 100
        
        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory_percent, 1),
            "disk_percent": round(disk_percent, 1),
            "memory_used_gb": round(memory.used / (1024**3), 2),
            "memory_total_gb": round(memory.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2)
        }
    except Exception as e:
        return {
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_percent": 0,
            "error": str(e)
        }

@app.get("/api/dns/queries")
async def get_dns_queries(
    limit: int = 200,
    peer_ip: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Recent domain lookups per peer, most recent first (the dashboard's
    Activity tab). Domain-level only - see dns_activity.py for how this is
    collected."""
    async with AsyncSessionLocal() as db:
        stmt = select(DnsQueryLog).order_by(DnsQueryLog.timestamp.desc()).limit(min(limit, 1000))
        if peer_ip:
            stmt = stmt.where(DnsQueryLog.peer_ip == peer_ip)
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

    return {
        "queries": [
            {
                "peer_ip": r.peer_ip,
                "peer_name": ip_to_name.get(r.peer_ip, r.peer_ip),
                "domain": r.domain,
                "timestamp": r.timestamp.isoformat()
            }
            for r in rows
        ]
    }

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
async def login(user_credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """User login"""
    # Get user from database
    result = await db.execute(select(User).where(User.username == user_credentials.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(user_credentials.password, user.hashed_password):  # type: ignore[arg-type]
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
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
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )
    
    return json_response

# ===== API namespace compatibility layer (/api/auth/*) =====
# These endpoints mirror /auth/* so the frontend calling /api/auth/... works.

@app.post('/api/auth/login')
async def api_login(request: Request, db: AsyncSession = Depends(get_db)):
    logger.info("Login attempt started")
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
        raise HTTPException(status_code=401, detail='Invalid credentials')
    
    if not verify_password(password, getattr(user, "hashed_password")):
        logger.warning(f"Login failed: invalid password for user - {username}")
        raise HTTPException(status_code=401, detail='Invalid credentials')
    
    logger.info(f"Login successful for user: {username}")
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

@app.get("/api/auth/me", response_model=UserResponse)
async def api_get_current_user(current_user: dict = Depends(get_current_user)):
    """Get current user information - API auth endpoint"""
    logger.info(f"Current user info requested: {current_user.get('username', 'unknown')}")
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
        setattr(user, "role", user_update.role)
    
    if user_update.status:
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

@app.get("/vpn/wireguard/peers")
async def list_wireguard_peers(current_user: dict = Depends(get_current_user)):
    """List all WireGuard peers"""
    try:
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
                    
                    # Extract IP from config (looking for Address line)
                    address_line = ""
                    for line in config_content.split('\n'):
                        if line.strip().startswith('Address'):
                            address_line = line.strip().split('=')[1].strip()
                            break
                    
                    peers.append({
                        "name": peer_name,
                        "ip": address_line,
                        "config_file": filename,
                        "created_at": os.path.getctime(config_path)
                    })
        
        return {"peers": peers}
    except Exception as e:
        logger.error(f"Error listing WireGuard peers: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list peers: {str(e)}")

@app.post("/vpn/wireguard/peers")
async def create_wireguard_peer(
    peer: WireGuardPeerCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create new WireGuard peer"""
    if current_user["role"] != "admin" and peer.user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    return await vpn_manager.create_wireguard_peer(peer.peer_name, peer.user_id)

@app.get("/vpn/wireguard/peers/{peer_name}/config")
async def download_wireguard_config(
    peer_name: str,
    current_user: dict = Depends(get_current_user)
):
    """Download WireGuard peer configuration"""
    config_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"
    
    if not os.path.exists(config_file):
        raise HTTPException(status_code=404, detail="Peer configuration not found")
    
    return FileResponse(config_file, filename=f"{peer_name}.conf")

@app.get("/vpn/wireguard/peers/{peer_name}/qrcode")
async def get_wireguard_peer_qrcode(
    peer_name: str,
    current_user: dict = Depends(get_current_user)
):
    """Generate a QR code for an existing peer's config (e.g. to scan with the
    WireGuard mobile app), without needing to recreate the peer's keys"""
    config_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"

    if not os.path.exists(config_file):
        raise HTTPException(status_code=404, detail="Peer configuration not found")

    with open(config_file, 'r') as f:
        config_content = f.read()

    qr_code = await vpn_manager._generate_qr_code(config_content)
    return {"peer_name": peer_name, "qr_code": qr_code}

@app.delete("/vpn/wireguard/peers/{peer_name}")
async def delete_wireguard_peer(
    peer_name: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete WireGuard peer"""
    # Only admin can delete any peer, users can only delete their own
    if current_user["role"] != "admin":
        # TODO: Check if this peer belongs to the current user
        # For now, only admin can delete
        raise HTTPException(status_code=403, detail="Only admin can delete peers")
    
    return await vpn_manager.delete_wireguard_peer(peer_name)

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
        
        if os.path.exists(clients_dir):
            for filename in os.listdir(clients_dir):
                if filename.endswith('.ovpn'):
                    client_name = filename[:-5]  # Remove .ovpn extension
                    config_path = os.path.join(clients_dir, filename)
                    
                    clients.append({
                        "name": client_name,
                        "config_file": filename,
                        "created_at": os.path.getctime(config_path),
                        "status": "inactive"  # TODO: Add real status check
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
    
    return await vpn_manager.create_openvpn_client(client.client_name, client.user_id)

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

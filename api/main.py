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
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, status, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
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
from config import settings

class UserCreate(BaseModel):
    """User creation model"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None
    role: str = "user"
    protocols: List[str] = ["wireguard"]

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
    uptime: Optional[str]
    connections: int
    last_updated: datetime

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security
security = HTTPBearer()

# Import database models
from database import (
    User, VPNConfig, UserSession, UsageLog, ServerEndpoint, IPRotation,
    AsyncSessionLocal, init_db, create_default_admin, create_default_endpoints, get_db
)
from ip_rotation import ip_rotation_service

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
                'wg', 'show',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await result.communicate()
            
            if result.returncode == 0:
                connections = len([line for line in stdout.decode().split('\n') if 'peer:' in line])
                return VPNStatus(
                    service="wireguard",
                    status="running",
                    connections=connections,
                    last_updated=datetime.now()
                )
            else:
                return VPNStatus(
                    service="wireguard",
                    status="stopped",
                    connections=0,
                    last_updated=datetime.now()
                )
        except Exception as e:
            return VPNStatus(
                service="wireguard",
                status="error",
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
DNS = {settings.dns_servers}

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
        """Get next available IP for peer"""
        peers_dir = f"{settings.wireguard_config_path}/peers"
        if not os.path.exists(peers_dir):
            return 2
        
        existing_ips = []
        for file in os.listdir(peers_dir):
            if file.endswith('.conf'):
                with open(os.path.join(peers_dir, file), 'r') as f:
                    content = f.read()
                    if 'Address = 10.13.13.' in content:
                        ip = content.split('Address = 10.13.13.')[1].split('/')[0]
                        existing_ips.append(int(ip))
        
        return max(existing_ips + [1]) + 1
    
    async def _add_wireguard_peer_to_server(self, public_key: str, peer_name: str, peer_ip: int):
        """Add peer to WireGuard server configuration"""
        server_config = f"{settings.wireguard_config_path}/wg0.conf"
        
        # Create server config if it doesn't exist
        if not os.path.exists(server_config):
            server_private_key_path = f"{settings.wireguard_config_path}/server_private.key"
            if os.path.exists(server_private_key_path):
                with open(server_private_key_path, 'r') as f:
                    server_private_key = f.read().strip()
            else:
                server_private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
                with open(server_private_key_path, 'w') as f:
                    f.write(server_private_key)
            
            server_config_content = f"""[Interface]
PrivateKey = {server_private_key}
Address = 10.13.13.1/24
ListenPort = {settings.wireguard_port}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
"""
            with open(server_config, 'w') as f:
                f.write(server_config_content)
        
        # Add peer to server config
        with open(server_config, 'a') as f:
            f.write(f"\n[Peer]\n")
            f.write(f"# {peer_name}\n")
            f.write(f"PublicKey = {public_key}\n")
            f.write(f"AllowedIPs = 10.13.13.{peer_ip}/32\n")
        
        # Reload WireGuard configuration
        try:
            await asyncio.create_subprocess_exec('wg', 'syncconf', 'wg0', server_config)
        except:
            pass  # WireGuard might not be running yet
    
    async def _generate_qr_code(self, config_data: str) -> str:
        """Generate QR code for configuration"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(config_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        return base64.b64encode(buffer.getvalue()).decode()
    
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

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = users_db.get(username)
    if user is None:
        raise credentials_exception
    return user

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
    
    yield
    
    # Shutdown
    print("Shutting down BartoloVPN API...")

# Create FastAPI app
app = FastAPI(
    title="BartoloVPN API",
    description="Multi-Protocol VPN Server Management API",
    version="1.0.0",
    lifespan=lifespan
)

# Mount static files for web interface
app.mount("/static", StaticFiles(directory="/app/web/static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="/app/web/templates")

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
    """Root endpoint - serves web interface"""
    return templates.TemplateResponse("index.html", {"request": request})

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
    
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        email=new_user.email,
        role=new_user.role,
        protocols=user.protocols,
        created_at=new_user.created_at,
        last_login=new_user.last_login,
        is_active=new_user.is_active
    )

@app.post("/auth/login", response_model=Token)
async def login(user_credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """User login"""
    # Get user from database
    result = await db.execute(select(User).where(User.username == user_credentials.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(user_credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()
    
    access_token_expires = timedelta(minutes=settings.jwt_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer", "username": user.username}

@app.get("/users/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """Get current user information"""
    return UserResponse(**current_user)

@app.get("/users", response_model=List[UserResponse])
async def get_users(current_user: dict = Depends(get_current_user)):
    """Get all users (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return [UserResponse(**user) for user in users_db.values()]

@app.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, current_user: dict = Depends(get_current_user)):
    """Create a new user (admin only)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if user.username in users_db:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    global user_id_counter
    user_id_counter += 1
    
    hashed_password = get_password_hash(user.password)
    users_db[user.username] = {
        "id": user_id_counter,
        "username": user.username,
        "email": user.email,
        "hashed_password": hashed_password,
        "role": user.role,
        "protocols": user.protocols,
        "created_at": datetime.now(),
        "last_login": None,
        "is_active": True
    }
    
    return UserResponse(**users_db[user.username])

# VPN Management Routes
@app.get("/vpn/wireguard/status")
async def get_wireguard_status(current_user: dict = Depends(get_current_user)):
    """Get WireGuard status"""
    return await vpn_manager.get_wireguard_status()

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

@app.get("/system/stats")
async def get_system_stats(current_user: dict = Depends(get_current_user)):
    """Get system statistics"""
    return await vpn_manager.get_system_stats()

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
                "last_used": endpoint.last_used.isoformat() if endpoint.last_used else None
            }
            for endpoint in endpoints
        ]

@app.post("/endpoints")
async def create_endpoint(
    name: str,
    ip_address: str,
    port: int,
    protocol: str,
    country: str = None,
    priority: int = 1,
    current_user: dict = Depends(get_current_user)
):
    """Create a new server endpoint"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    
    endpoint = await ip_rotation_service.add_endpoint(name, ip_address, port, protocol, country, priority)
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
                "last_used": config.last_used.isoformat() if config.last_used else None
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
                    "connection_end": log.connection_end.isoformat() if log.connection_end else None,
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

#!/usr/bin/env python3
"""
BartoloVPN Management API
Handles VPN configuration and management for WireGuard, OpenVPN, and IKEv2
"""

import os
import json
import subprocess
import qrcode
import base64
from io import BytesIO
from datetime import datetime, timedelta
from uuid import uuid4
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import psutil
from sqlalchemy import select
from passlib.context import CryptContext
from config import settings  # type: ignore  # Pylance: workspace root has a directory named 'config' (namespace) overshadowing file api/config.py inside container
from database import (
    get_db,
    init_db,
    create_default_admin,
    create_default_endpoints,
    User,
    UserSession
)
# import netifaces  # Removed due to build issues - using psutil for network info instead

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = settings.jwt_secret_key
ALGORITHM = settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.jwt_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
templates = Jinja2Templates(directory="web/templates")

# Configuration paths
WIREGUARD_CONFIG_PATH = os.getenv('WIREGUARD_CONFIG_PATH', '/config/wireguard')
OPENVPN_CONFIG_PATH = os.getenv('OPENVPN_CONFIG_PATH', '/config/openvpn')
IKEV2_CONFIG_PATH = os.getenv('IKEV2_CONFIG_PATH', '/config/ikev2')

# ...existing code...
# ...existing code...

class VPNManager:
    """Manages VPN configurations and operations"""
    
    def __init__(self):
        self.wireguard_config = f"{WIREGUARD_CONFIG_PATH}/wg0.conf"
        self.openvpn_config = f"{OPENVPN_CONFIG_PATH}/server.conf"
        self.ikev2_config = f"{IKEV2_CONFIG_PATH}/ipsec.conf"
    
    def get_wireguard_status(self):
        """Get WireGuard connection status"""
        try:
            result = subprocess.run(['wg', 'show'], capture_output=True, text=True)
            if result.returncode == 0:
                return {'status': 'running', 'output': result.stdout}
            else:
                return {'status': 'stopped', 'output': result.stderr}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def create_wireguard_peer(self, peer_name):
        """Create a new WireGuard peer configuration"""
        try:
            # Generate private and public keys
            private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
            public_key = subprocess.run(['wg', 'pubkey'], input=private_key, capture_output=True, text=True).stdout.strip()
            
            # Get server public key
            with open(f"{WIREGUARD_CONFIG_PATH}/server_public.key", 'r') as f:
                server_public_key = f.read().strip()
            
            # Generate peer configuration
            peer_config = f"""[Interface]
PrivateKey = {private_key}
Address = 10.13.13.{self._get_next_peer_ip()}/24
DNS = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey = {server_public_key}
Endpoint = {os.getenv('SERVER_IP', 'your-server-ip')}:{os.getenv('WIREGUARD_PORT', '51820')}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""
            
            # Save peer configuration
            peer_file = f"{WIREGUARD_CONFIG_PATH}/peers/{peer_name}.conf"
            os.makedirs(os.path.dirname(peer_file), exist_ok=True)
            with open(peer_file, 'w') as f:
                f.write(peer_config)
            
            # Add peer to server configuration
            self._add_wireguard_peer_to_server(public_key, peer_name)
            
            return {
                'peer_name': peer_name,
                'config': peer_config,
                'qr_code': self._generate_qr_code(peer_config)
            }
        except Exception as e:
            return {'error': str(e)}
    
    def _get_next_peer_ip(self):
        """Get next available IP for peer"""
        peers_dir = f"{WIREGUARD_CONFIG_PATH}/peers"
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
    
    def _add_wireguard_peer_to_server(self, public_key, peer_name):
        """Add peer to WireGuard server configuration"""
        server_config = f"{WIREGUARD_CONFIG_PATH}/wg0.conf"
        
        with open(server_config, 'a') as f:
            f.write(f"\n[Peer]\n")
            f.write(f"# {peer_name}\n")
            f.write(f"PublicKey = {public_key}\n")
            f.write(f"AllowedIPs = 10.13.13.{self._get_next_peer_ip() - 1}/32\n")
        
        # Reload WireGuard configuration
        subprocess.run(['wg', 'syncconf', 'wg0', server_config])
    
    def _generate_qr_code(self, config_data):
        """Generate QR code for configuration"""
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(config_data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer)
        buffer.seek(0)
        
        return base64.b64encode(buffer.getvalue()).decode()
    
    def get_openvpn_status(self):
        """Get OpenVPN server status"""
        try:
            result = subprocess.run(['systemctl', 'status', 'openvpn@server'], capture_output=True, text=True)
            if result.returncode == 0:
                return {'status': 'running', 'output': result.stdout}
            else:
                return {'status': 'stopped', 'output': result.stderr}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def create_openvpn_client(self, client_name):
        """Create OpenVPN client configuration"""
        try:
            # Generate client certificate and key
            client_config = f"""[client]
dev tun
proto udp
remote {os.getenv('SERVER_IP', 'your-server-ip')} {os.getenv('OPENVPN_PORT', '1194')}
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
cipher AES-256-GCM
auth SHA256
key-direction 1
verb 3
"""
            
            # Save client configuration
            client_file = f"{OPENVPN_CONFIG_PATH}/clients/{client_name}.ovpn"
            os.makedirs(os.path.dirname(client_file), exist_ok=True)
            with open(client_file, 'w') as f:
                f.write(client_config)
            
            return {
                'client_name': client_name,
                'config_file': client_file
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_ikev2_status(self):
        """Get IKEv2 server status"""
        try:
            result = subprocess.run(['systemctl', 'status', 'strongswan'], capture_output=True, text=True)
            if result.returncode == 0:
                return {'status': 'running', 'output': result.stdout}
            else:
                return {'status': 'stopped', 'output': result.stderr}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def get_system_stats(self):
        """Get system statistics"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()
            
            return {
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used': memory.used,
                'memory_total': memory.total,
                'disk_percent': disk.percent,
                'disk_used': disk.used,
                'disk_total': disk.total,
                'network_bytes_sent': network.bytes_sent,
                'network_bytes_recv': network.bytes_recv
            }
        except Exception as e:
            return {'error': str(e)}

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire, "type": "access"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(session_id: str, username: str) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": username, "sid": session_id, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

# Initialize VPN manager
vpn_manager = VPNManager()

@app.on_event("startup")
async def on_startup():
    await init_db()
    await create_default_admin()
    await create_default_endpoints()

# Public routes for initial landing and login (serve combined index including login screen)
@app.get('/')
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get('/login')
async def login_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get('/api/health')
async def health_check():
    from datetime import datetime
    return JSONResponse({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.post('/api/auth/login')
async def login(request: Request, db=Depends(get_db)):
    data = await request.json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return JSONResponse({'error': 'Username and password required'}, status_code=400)
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user or not verify_password(password, user.hashed_password) or not user.is_active:
        return JSONResponse({'error': 'Invalid credentials'}, status_code=401)
    # Update last_login
    user.last_login = datetime.utcnow()
    # Create session
    session_id = uuid4().hex
    refresh_token = create_refresh_token(session_id, user.username)
    refresh_expires = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    user_session = UserSession(
        user_id=user.id,
        session_token=session_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get('user-agent'),
        created_at=datetime.utcnow(),
        expires_at=refresh_expires,
        is_active=True
    )
    db.add(user_session)
    await db.commit()
    access_token = create_access_token(user.username)
    return JSONResponse({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'username': user.username,
        'role': user.role,
        'expires_in': ACCESS_TOKEN_EXPIRE_MINUTES * 60
    })



# FastAPI logout endpoint
@app.post('/api/auth/logout')
async def logout(request: Request, db=Depends(get_db), token: str = Depends(oauth2_scheme)):
    # Best-effort: deactivate session if refresh token provided in body or Authorization contains access token referencing session id
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    refresh_token = body.get('refresh_token') if isinstance(body, dict) else None
    # Decode refresh token to get session id
    if refresh_token:
        try:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            sid = payload.get('sid')
            if sid:
                result = await db.execute(select(UserSession).where(UserSession.session_token == sid))
                session_obj = result.scalars().first()
                if session_obj:
                    session_obj.is_active = False
                    await db.commit()
        except JWTError:
            pass
    return JSONResponse({'msg': 'Logged out'})

@app.post('/api/auth/refresh')
async def refresh(request: Request, db=Depends(get_db)):
    data = await request.json()
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return JSONResponse({'error': 'Refresh token required'}, status_code=400)
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get('type') != 'refresh':
            raise JWTError('Invalid token type')
        username = payload.get('sub')
        sid = payload.get('sid')
        if not username or not sid:
            raise JWTError('Invalid payload')
        # Validate session
        result = await db.execute(select(UserSession).where(UserSession.session_token == sid, UserSession.is_active == True))
        session_obj = result.scalars().first()
        if not session_obj or session_obj.expires_at < datetime.utcnow():
            return JSONResponse({'error': 'Session expired'}, status_code=401)
        # Issue new access token
        access_token = create_access_token(username)
        return JSONResponse({'access_token': access_token, 'expires_in': ACCESS_TOKEN_EXPIRE_MINUTES * 60})
    except JWTError:
        return JSONResponse({'error': 'Invalid refresh token'}, status_code=401)

# Dependency to get current user from JWT
def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception

# FastAPI dashboard route (template public; data fetched via APIs with auth)
@app.get('/dashboard')
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get('/api/auth/me')
async def auth_me(username: str = Depends(get_current_user), db=Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        'username': user.username,
        'role': user.role,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'last_login': user.last_login.isoformat() if user.last_login else None
    }

@app.get('/api/vpn/wireguard/status')
async def wireguard_status(username: str = Depends(get_current_user)):
    return JSONResponse(vpn_manager.get_wireguard_status())

@app.post('/api/vpn/wireguard/peers')
async def create_wireguard_peer(request: Request, username: str = Depends(get_current_user)):
    data = await request.json()
    peer_name = data.get('peer_name')
    if not peer_name:
        return JSONResponse({'error': 'Peer name is required'}, status_code=400)
    result = vpn_manager.create_wireguard_peer(peer_name)
    return JSONResponse(result)

@app.get('/api/vpn/wireguard/peers/{peer_name}/config')
async def download_wireguard_config(peer_name: str, username: str = Depends(get_current_user)):
    config_file = f"{WIREGUARD_CONFIG_PATH}/peers/{peer_name}.conf"
    if not os.path.exists(config_file):
        return JSONResponse({'error': 'Peer configuration not found'}, status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(config_file, media_type='application/octet-stream', filename=f"{peer_name}.conf")

@app.get('/api/vpn/openvpn/status')
async def openvpn_status(username: str = Depends(get_current_user)):
    return JSONResponse(vpn_manager.get_openvpn_status())

@app.post('/api/vpn/openvpn/clients')
async def create_openvpn_client(request: Request, username: str = Depends(get_current_user)):
    data = await request.json()
    client_name = data.get('client_name')
    if not client_name:
        return JSONResponse({'error': 'Client name is required'}, status_code=400)
    result = vpn_manager.create_openvpn_client(client_name)
    return JSONResponse(result)

@app.get('/api/vpn/ikev2/status')
async def ikev2_status(username: str = Depends(get_current_user)):
    return JSONResponse(vpn_manager.get_ikev2_status())

@app.get('/api/system/stats')
async def system_stats(username: str = Depends(get_current_user)):
    return JSONResponse(vpn_manager.get_system_stats())

@app.get('/api/system/resources')
async def system_resources(username: str = Depends(get_current_user)):
    return JSONResponse(vpn_manager.get_system_stats())

@app.post('/api/auth/register')
async def register(request: Request, db=Depends(get_db)):
    data = await request.json()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip() or None
    password = data.get('password') or ''
    if not username or not password:
        return JSONResponse({'error': 'Username and password required'}, status_code=400)
    if len(password) < 8:
        return JSONResponse({'error': 'Password must be at least 8 characters'}, status_code=400)
    # Check existing user
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalars().first():
        return JSONResponse({'error': 'Username already exists'}, status_code=409)
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role='user',
        is_active=True,
        created_at=datetime.utcnow()
    )
    db.add(user)
    await db.commit()
    return JSONResponse({'msg': 'User registered successfully. Please login.', 'username': username})

@app.get('/api/vpn/peers')
async def list_peers(username: str = Depends(get_current_user)):
    peers = {
        'wireguard': [],
        'openvpn': [],
        'ikev2': []
    }
    # List WireGuard peers
    wireguard_peers_dir = f"{WIREGUARD_CONFIG_PATH}/peers"
    if os.path.exists(wireguard_peers_dir):
        for file in os.listdir(wireguard_peers_dir):
            if file.endswith('.conf'):
                peers['wireguard'].append(file.replace('.conf', ''))
    # List OpenVPN clients
    openvpn_clients_dir = f"{OPENVPN_CONFIG_PATH}/clients"
    if os.path.exists(openvpn_clients_dir):
        for file in os.listdir(openvpn_clients_dir):
            if file.endswith('.ovpn'):
                peers['openvpn'].append(file.replace('.ovpn', ''))
    return JSONResponse(peers)

## FastAPI does not use app.run; use uvicorn to start the server

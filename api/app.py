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
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import psutil
# import netifaces  # Removed due to build issues - using psutil for network info instead

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'your-secret-key-change-this')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)

jwt = JWTManager(app)
CORS(app)

# Configuration paths
WIREGUARD_CONFIG_PATH = os.getenv('WIREGUARD_CONFIG_PATH', '/config/wireguard')
OPENVPN_CONFIG_PATH = os.getenv('OPENVPN_CONFIG_PATH', '/config/openvpn')
IKEV2_CONFIG_PATH = os.getenv('IKEV2_CONFIG_PATH', '/config/ikev2')

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
        img.save(buffer, format='PNG')
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

# Initialize VPN manager
vpn_manager = VPNManager()

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/api/auth/login', methods=['POST'])
def login():
    """User authentication"""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    # Simple authentication (in production, use proper authentication)
    if username == os.getenv('WEB_USERNAME', 'admin') and password == os.getenv('WEB_PASSWORD', 'admin'):
        access_token = create_access_token(identity=username)
        return jsonify({'access_token': access_token, 'username': username})
    else:
        return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/vpn/wireguard/status', methods=['GET'])
@jwt_required()
def wireguard_status():
    """Get WireGuard status"""
    return jsonify(vpn_manager.get_wireguard_status())

@app.route('/api/vpn/wireguard/peers', methods=['POST'])
@jwt_required()
def create_wireguard_peer():
    """Create new WireGuard peer"""
    data = request.get_json()
    peer_name = data.get('peer_name')
    
    if not peer_name:
        return jsonify({'error': 'Peer name is required'}), 400
    
    result = vpn_manager.create_wireguard_peer(peer_name)
    return jsonify(result)

@app.route('/api/vpn/wireguard/peers/<peer_name>/config', methods=['GET'])
@jwt_required()
def download_wireguard_config(peer_name):
    """Download WireGuard peer configuration"""
    config_file = f"{WIREGUARD_CONFIG_PATH}/peers/{peer_name}.conf"
    
    if not os.path.exists(config_file):
        return jsonify({'error': 'Peer configuration not found'}), 404
    
    return send_file(config_file, as_attachment=True, download_name=f"{peer_name}.conf")

@app.route('/api/vpn/openvpn/status', methods=['GET'])
@jwt_required()
def openvpn_status():
    """Get OpenVPN status"""
    return jsonify(vpn_manager.get_openvpn_status())

@app.route('/api/vpn/openvpn/clients', methods=['POST'])
@jwt_required()
def create_openvpn_client():
    """Create new OpenVPN client"""
    data = request.get_json()
    client_name = data.get('client_name')
    
    if not client_name:
        return jsonify({'error': 'Client name is required'}), 400
    
    result = vpn_manager.create_openvpn_client(client_name)
    return jsonify(result)

@app.route('/api/vpn/ikev2/status', methods=['GET'])
@jwt_required()
def ikev2_status():
    """Get IKEv2 status"""
    return jsonify(vpn_manager.get_ikev2_status())

@app.route('/api/system/stats', methods=['GET'])
@jwt_required()
def system_stats():
    """Get system statistics"""
    return jsonify(vpn_manager.get_system_stats())

@app.route('/api/vpn/peers', methods=['GET'])
@jwt_required()
def list_peers():
    """List all VPN peers"""
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
    
    return jsonify(peers)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

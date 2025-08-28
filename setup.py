#!/usr/bin/env python3
"""
BartoloVPN Setup Script
Helps configure and deploy the VPN server
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def print_banner():
    """Print setup banner"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                    BartoloVPN Setup                          ║
║              Multi-Protocol VPN Server                       ║
╚══════════════════════════════════════════════════════════════╝
    """)

def check_requirements():
    """Check if required tools are installed"""
    print("🔍 Checking requirements...")
    
    requirements = {
        'docker': 'Docker',
        'docker-compose': 'Docker Compose',
        'python3': 'Python 3.8+'
    }
    
    missing = []
    for cmd, name in requirements.items():
        if shutil.which(cmd) is None:
            missing.append(name)
        else:
            print(f"✅ {name} found")
    
    if missing:
        print(f"❌ Missing requirements: {', '.join(missing)}")
        print("Please install the missing tools and run setup again.")
        return False
    
    return True

def get_user_input():
    """Get configuration from user"""
    print("\n📝 Configuration Setup")
    print("Please provide the following information:")
    
    config = {}
    
    # Server configuration
    config['server_ip'] = input("🌐 Server Public IP: ").strip()
    if not config['server_ip']:
        print("❌ Server IP is required!")
        return None
    
    config['domain'] = input("🌍 Domain (optional): ").strip()
    
    # Web interface
    config['web_port'] = input("🌐 Web Interface Port (default: 8080): ").strip() or "8080"
    config['web_username'] = input("👤 Admin Username (default: admin): ").strip() or "admin"
    config['web_password'] = input("🔒 Admin Password: ").strip()
    if not config['web_password']:
        print("❌ Admin password is required!")
        return None
    
    # VPN protocols
    print("\n🔧 VPN Protocols:")
    config['wireguard_enabled'] = input("Enable WireGuard? (y/n, default: y): ").strip().lower() != 'n'
    config['openvpn_enabled'] = input("Enable OpenVPN? (y/n, default: y): ").strip().lower() != 'n'
    config['ikev2_enabled'] = input("Enable IKEv2? (y/n, default: y): ").strip().lower() != 'n'
    
    # Security
    config['encryption_level'] = input("🔐 Encryption Level (128/256, default: 256): ").strip() or "256"
    config['dns_servers'] = input("📡 DNS Servers (default: 1.1.1.1,8.8.8.8): ").strip() or "1.1.1.1,8.8.8.8"
    
    return config

def create_env_file(config):
    """Create .env file from configuration"""
    print("\n📄 Creating .env file...")
    
    env_content = f"""# BartoloVPN Configuration

# Server Configuration
SERVER_IP={config['server_ip']}
DOMAIN={config['domain']}

# Web Interface
WEB_PORT={config['web_port']}
WEB_USERNAME={config['web_username']}
WEB_PASSWORD={config['web_password']}

# WireGuard Configuration
WIREGUARD_ENABLED={'true' if config['wireguard_enabled'] else 'false'}
WIREGUARD_PORT=51820
WIREGUARD_PEERS=10
WIREGUARD_DNS={config['dns_servers']}
WIREGUARD_SUBNET=10.13.13.0
WIREGUARD_ALLOWED_IPS=0.0.0.0/0

# OpenVPN Configuration
OPENVPN_ENABLED={'true' if config['openvpn_enabled'] else 'false'}
OPENVPN_PORT=1194
OPENVPN_PROTOCOL=udp
OPENVPN_CIPHER=AES-{config['encryption_level']}-GCM
OPENVPN_AUTH=SHA256

# IKEv2 Configuration
IKEV2_ENABLED={'true' if config['ikev2_enabled'] else 'false'}
IKEV2_PSK=your-ikev2-pre-shared-key
IKEV2_USER=vpnuser
IKEV2_PASSWORD=vpnpass

# Security Settings
ENCRYPTION_LEVEL={config['encryption_level']}
DNS_SERVERS={config['dns_servers']}
KILL_SWITCH_ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_RETENTION_DAYS=30

# Monitoring
MONITORING_ENABLED=true
BANDWIDTH_LIMIT_MB=1000

# JWT Secret (change this in production!)
JWT_SECRET_KEY=your-super-secret-jwt-key-change-this-in-production
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ .env file created successfully")

def create_directories():
    """Create necessary directories"""
    print("\n📁 Creating directories...")
    
    directories = [
        'config/wireguard/peers',
        'config/openvpn/clients',
        'config/ikev2',
        'logs',
        'data'
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✅ Created {directory}/")

def setup_firewall():
    """Setup firewall rules"""
    print("\n🔥 Setting up firewall rules...")
    
    # Check if ufw is available
    if shutil.which('ufw'):
        try:
            # Allow SSH
            subprocess.run(['ufw', 'allow', 'ssh'], check=True)
            
            # Allow web interface
            subprocess.run(['ufw', 'allow', '8080/tcp'], check=True)
            
            # Allow VPN ports
            subprocess.run(['ufw', 'allow', '51820/udp'], check=True)  # WireGuard
            subprocess.run(['ufw', 'allow', '1194/udp'], check=True)   # OpenVPN
            subprocess.run(['ufw', 'allow', '500/udp'], check=True)    # IKEv2
            subprocess.run(['ufw', 'allow', '4500/udp'], check=True)   # IKEv2 NAT
            
            # Enable firewall
            subprocess.run(['ufw', '--force', 'enable'], check=True)
            
            print("✅ Firewall configured successfully")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Firewall setup failed: {e}")
    else:
        print("⚠️  UFW not found. Please configure firewall manually.")

def build_and_start():
    """Build and start the services"""
    print("\n🚀 Building and starting services...")
    
    try:
        # Build images
        print("📦 Building Docker images...")
        subprocess.run(['docker-compose', 'build'], check=True)
        
        # Start services
        print("▶️  Starting services...")
        subprocess.run(['docker-compose', 'up', '-d'], check=True)
        
        print("✅ Services started successfully!")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start services: {e}")
        return False
    
    return True

def show_status():
    """Show service status"""
    print("\n📊 Service Status:")
    
    try:
        result = subprocess.run(['docker-compose', 'ps'], capture_output=True, text=True)
        print(result.stdout)
    except subprocess.CalledProcessError:
        print("❌ Failed to get service status")

def show_next_steps():
    """Show next steps for the user"""
    print("""
🎉 Setup Complete!

Next Steps:
1. 🌐 Access the web interface: http://your-server-ip:8080
2. 👤 Login with the admin credentials you provided
3. 🔧 Configure additional endpoints and users
4. 📱 Generate client configurations for your friends
5. 🔄 Set up IP rotation to avoid detection

Important Notes:
- 🔒 Change default passwords immediately
- 🌍 Configure your domain DNS if you have one
- 📊 Monitor usage and performance
- 🔄 Regularly rotate IP addresses
- 📝 Keep backups of configurations

For support and documentation:
- 📖 Read the README.md file
- 🐛 Check logs: docker-compose logs
- 🔧 Restart services: docker-compose restart

Happy VPN-ing! 🚀
    """)

def main():
    """Main setup function"""
    print_banner()
    
    # Check requirements
    if not check_requirements():
        sys.exit(1)
    
    # Get user configuration
    config = get_user_input()
    if not config:
        sys.exit(1)
    
    # Create .env file
    create_env_file(config)
    
    # Create directories
    create_directories()
    
    # Setup firewall
    setup_firewall()
    
    # Build and start services
    if build_and_start():
        show_status()
        show_next_steps()
    else:
        print("❌ Setup failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()

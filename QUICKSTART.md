# BartoloVPN Quick Start Guide

Get your multi-protocol VPN server running in minutes!

## 🚀 Quick Setup

### 1. Prerequisites
- Linux, macOS, or Windows
- That's it — Python, Docker, Docker Compose, and the VPN protocol tools are all detected and auto-installed by the installer below if missing.

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN

# Linux / macOS
./install.sh

# Windows (CMD)
install.bat
```

The installer will:
- 🖥️ Detect your OS and auto-install Python if it isn't already present (falling back to compiling from source on Linux if no package is available)
- 🔍 Then hand off to `vpn-setup.py`, which:
  - ✅ Detects your OS again and auto-installs Docker, Docker Compose, and the WireGuard/OpenVPN/IKEv2 CLI tools if missing
  - 📝 Guides you through configuration (auto-detecting your external IP, auto-generating the JWT secret and IKEv2 pre-shared key)
  - 🔧 Creates necessary directories
  - 🔥 Configures firewall rules
  - 🚀 Builds and starts all services

If you already have Python 3.8+ installed, you can skip straight to `python3 vpn-setup.py` instead.

### 3. Access the Web Interface

After setup completes:
1. Open your browser to `http://your-server-ip:8080`
2. Login with the admin credentials you provided
3. Start managing your VPN!

## 🔧 Manual Setup (Alternative)

If you prefer manual setup:

```bash
# 1. Copy environment template
cp env.example .env

# 2. Edit configuration
nano .env

# 3. Create directories
mkdir -p config/{wireguard,openvpn,ikev2} logs data

# 4. Start services
docker-compose up -d
```

## 📱 Adding Users

### Via Web Interface (Recommended)
1. Login as admin
2. Go to "Users" tab
3. Click "Add New User"
4. Fill in user details
5. Generate VPN configurations

### Via API
```bash
# Create a new user
curl -X POST "http://your-server-ip:5000/users" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "friend1",
    "password": "secure_password",
    "email": "friend@example.com",
    "role": "user",
    "protocols": ["wireguard"]
  }'
```

## 🔄 Docker Network IP Rotation

BartoloVPN leverages Docker's advanced networking for automatic IP rotation and load balancing:

### 1. Docker Network Architecture
- **vpn-network** (172.20.0.0/16): Internal communication between services
- **vpn-external** (10.13.13.0/24): VPN client traffic and IP rotation
- **HAProxy**: Load balancer with health checks and automatic failover

### 2. Automatic IP Rotation
```bash
# Manual rotation
./scripts/docker-network-rotation.sh rotate

# Continuous rotation (every hour)
./scripts/docker-network-rotation.sh continuous

# Check current status
./scripts/docker-network-rotation.sh status
```

### 3. Load Balancing Features
- **Round-robin** distribution across VPN servers
- **Health checks** for automatic failover
- **Backup servers** for high availability
- **Real-time monitoring** via HAProxy stats

### 4. Network Isolation
- VPN traffic isolated in `vpn-external` network
- Internal services in `vpn-network` network
- Automatic IP assignment and rotation
- No conflicts with host network

## 📊 Monitoring

### System Health
- Real-time system statistics
- VPN service status
- User connection monitoring
- Bandwidth usage tracking

### Usage Analytics
- Per-user usage statistics
- Protocol performance metrics
- Geographic distribution
- Connection history

## 🔒 Security Features

- **Strong Encryption**: AES-256-GCM
- **Perfect Forward Secrecy**: All protocols
- **DNS Leak Protection**: Built-in
- **Kill Switch**: Automatic traffic blocking
- **No Logging**: Zero traffic logging
- **Multi-Factor Auth**: JWT-based sessions

## 🌍 Multi-Protocol Support

### WireGuard (Recommended)
- **Port**: 51820/UDP
- **Speed**: Fastest
- **Security**: Modern cryptography
- **Setup**: QR code or config file

### OpenVPN
- **Port**: 1194/UDP
- **Compatibility**: Widest support
- **Security**: Battle-tested
- **Setup**: .ovpn file

### IKEv2
- **Ports**: 500/UDP, 4500/UDP
- **Mobile**: Excellent for phones
- **Enterprise**: Advanced features
- **Setup**: Built-in clients

## 🛠️ Troubleshooting

### Common Issues

**Services won't start:**
```bash
# Check logs
docker-compose logs

# Restart services
docker-compose restart
```

**Can't connect to VPN:**
```bash
# Check firewall
sudo ufw status

# Verify ports are open
sudo netstat -tulpn | grep :51820
```

**Web interface not accessible:**
```bash
# Check if service is running
docker-compose ps

# Check web interface logs
docker-compose logs web-ui
```

### Useful Commands

```bash
# View all logs
docker-compose logs -f

# Restart specific service
docker-compose restart wireguard

# Update configurations
docker-compose down && docker-compose up -d

# Backup configurations
tar -czf vpn-backup-$(date +%Y%m%d).tar.gz config/

# Check system resources
docker stats
```

## 📞 Support

- 📖 **Documentation**: README.md
- 🐛 **Issues**: GitHub Issues
- 💬 **Community**: GitHub Discussions
- 📧 **Email**: support@bartolovpn.com

## 🔄 Updates

```bash
# Update to latest version
git pull origin main
docker-compose down
docker-compose up -d --build
```

## 🎯 Next Steps

1. **Secure Your Server**
   - Change default passwords
   - Configure SSL/TLS certificates
   - Set up monitoring alerts

2. **Scale Your VPN**
   - Add more server locations
   - Configure load balancing
   - Set up automated backups

3. **Optimize Performance**
   - Monitor usage patterns
   - Adjust bandwidth limits
   - Fine-tune protocols

4. **User Management**
   - Create user groups
   - Set usage quotas
   - Configure access policies

---

**Happy VPN-ing! 🚀**

Remember: This VPN server is for personal use and sharing with friends. Please respect local laws and regulations regarding VPN usage.

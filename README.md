# 🛡️ BartoloVPN

**Multi-Protocol VPN Server with Web Management Interface**

![Login Demo](web/static/img/docs/login-demo.png)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Do## 🔒 Security Features

- **JWT Authentication** - Secure API access
- **Password Hashing** - bcrypt for user passwords
- **SSL/TLS** - Encrypted communications
- **Network Isolation** - Docker network segmentation
- **Privileged Containers** - Minimal required permissions
- **Cloudflare Tunnel** - Zero-trust remote access

## 📚 Documentation

### Setup Guides
- **[Cloudflare Tunnel Setup](cloudflare-tunnel-setup.md)** - Secure remote access configuration
- **[Geo-spoofing Guide](GEO-SPOOFING.md)** - Location spoofing configuration

### Quick Reference
- **[Quick Start Guide](QUICKSTART.md)** - Get up and running in 5 minutes
- **[Contributing Guidelines](CONTRIBUTING.md)** - How to contribute to the project
- **[Changelog](CHANGELOG.md)** - Project version history

## 🔧 Developmentimg.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-red.svg)](https://fastapi.tiangolo.com/)

A comprehensive VPN server solution supporting **WireGuard**, **OpenVPN**, and **IKEv2** protocols with a modern web-based management interface. Built with Docker for easy deployment and management.

## 🌟 Features

### 🔐 VPN Protocols
- **WireGuard** - Modern, fast, and secure VPN protocol
- **OpenVPN** - Industry-standard VPN protocol with wide compatibility
- **IKEv2** - Enterprise-grade VPN protocol for mobile devices
- **Multi-protocol Support** - Run multiple VPN protocols simultaneously

### 🖥️ Web Management Interface
- **Real-time Dashboard** - Monitor system status and VPN connections
- **User Management** - Create, manage, and monitor VPN users with JWT authentication
- **Configuration Management** - One-click VPN client configuration generation
- **System Monitoring** - Real-time CPU, memory, disk, and network usage
- **Multi-user Support** - Secure user registration and authentication system
- **Mobile Support** - QR code generation for easy mobile client setup

### 🚀 Advanced Features
- **Load Balancing** - HAProxy integration for high availability
- **IP Rotation** - Dynamic IP address rotation to avoid detection
- **Geo-spoofing** - Configure VPN to appear in different countries
- **Cloudflare Tunnel** - Secure remote access without port forwarding
- **Docker Networking** - Advanced container networking for scalability

## 🆕 What's New

### Latest Updates
- **User Authentication** - Secure JWT-based authentication system
- **FastAPI Backend** - Migrated from Flask for better performance
- **Enhanced Security** - Improved password hashing and security practices
- **Modern UI** - Responsive design with real-time updates
- **Comprehensive Logging** - Detailed system and VPN logs

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web Interface │    │   FastAPI       │    │   VPN Services  │
│   (Port 5000)   │◄──►│   Backend       │◄──►│   WireGuard     │
│                 │    │   (Port 5000)   │    │   OpenVPN       │
└─────────────────┘    └─────────────────┘    │   IKEv2         │
                                             └─────────────────┘
┌─────────────────┐    ┌─────────────────┐
│   HAProxy       │    │   SQLite        │
│   Load Balancer │    │   Database      │
│   (Port 8081)   │    │                 │
└─────────────────┘    └─────────────────┘
```

## 🚀 Quick Start

### Prerequisites
- Docker and Docker Compose
- Linux system with kernel modules support
- Port 5000, 51820, 1194, 500, 4500 available

### 1. Clone the Repository
```bash
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN
```

### 2. Configure Environment
```bash
# Copy and edit the environment file
cp env.example .env
nano .env
```

Make sure to set strong credentials for:
- `WEB_USERNAME`
- `WEB_PASSWORD`
- `JWT_SECRET_KEY`
- `IKEV2_PSK`

### 3. Start the Services
```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps
```

### 4. Access the Web Interface
- **Local Access**: http://localhost:5000
- **Remote Access**: http://your-server-ip:5000
- **Default Admin**: Use credentials from your `.env` file (WEB_USERNAME/WEB_PASSWORD)

## 📋 Configuration

### Environment Variables
```bash
# Server Configuration
SERVER_IP=your-server-ip
DOMAIN=your-domain.com

# Web Interface
WEB_USERNAME=admin
WEB_PASSWORD=your-secure-password

# VPN Protocols
WIREGUARD_PORT=51820
OPENVPN_PORT=1194
IKEV2_PSK=your-ikev2-pre-shared-key

# Security
JWT_SECRET_KEY=your-super-secret-jwt-key
```

### VPN Client Setup

#### WireGuard
1. Access web interface → WireGuard tab
2. Click "Add Peer" to create new configuration
3. Download QR code or configuration file
4. Import into WireGuard client

#### OpenVPN
1. Access web interface → OpenVPN tab
2. Click "Add Client" to generate configuration
3. Download .ovpn file
4. Import into OpenVPN client

#### IKEv2
1. Access web interface → IKEv2 tab
2. Create user credentials with username/password
3. Configure client with server IP and credentials
4. Connect using native VPN clients

## 🔧 Advanced Features

### IP Rotation
```bash
# Manual rotation
./scripts/docker-network-rotation.sh rotate

# Continuous rotation (every hour)
./scripts/docker-network-rotation.sh continuous
```

### Geo-spoofing
```bash
# Configure for Sweden
./scripts/geo-spoofing.sh sweden

# Configure for other countries
./scripts/geo-spoofing.sh germany
./scripts/geo-spoofing.sh japan
```

### Cloudflare Tunnel Setup
```bash
# Setup secure remote access
./scripts/setup-cloudflare-tunnel.sh
```

## 📊 Monitoring

### System Status
- **Real-time Metrics**: CPU, memory, and disk usage
- **VPN Statistics**: Active connections and bandwidth usage
- **Network Monitoring**: Real-time traffic analysis
- **Service Health**: Automatic status checks and alerts
- **Audit Logs**: Detailed access and configuration logs

### Logs
```bash
# View all logs
docker-compose logs

# View specific service logs
docker-compose logs vpn-api
docker-compose logs wireguard
docker-compose logs openvpn
docker-compose logs ikev2
```

## � Documentation

### Setup Guides
- **[Cloudflare Tunnel Setup](cloudflare-tunnel-setup.md)** - Secure remote access configuration
- **[Geo-spoofing Guide](GEO-SPOOFING.md)** - Location spoofing configuration

### Quick Reference
- **[Quick Start Guide](QUICKSTART.md)** - Get up and running in 5 minutes
- **[Contributing Guidelines](CONTRIBUTING.md)** - How to contribute to the project
- **[Changelog](CHANGELOG.md)** - Project version history

## 🔧 Development

- **JWT Authentication** - Secure API access
- **Password Hashing** - bcrypt for user passwords
- **SSL/TLS** - Encrypted communications
- **Network Isolation** - Docker network segmentation
- **Privileged Containers** - Minimal required permissions
- **Cloudflare Tunnel** - Zero-trust remote access

## 🛠️ Development

### Project Structure
```
BartoloVPN/
├── api/                    # FastAPI backend
│   ├── main.py            # Main application
│   ├── database.py        # Database models
│   ├── config.py          # Configuration
│   └── requirements.txt   # Python dependencies
├── web/                   # Frontend
│   ├── templates/         # Jinja2 templates
│   └── static/           # CSS, JS, images
├── scripts/              # Utility scripts
├── config/               # VPN configurations
├── docker-compose.yml    # Service orchestration
└── README.md            # This file
```

### API Endpoints
- `GET /` - Web interface
- `GET /api` - API information
- `GET /health` - Health check
- `POST /auth/register` - User registration
- `POST /auth/login` - User authentication
- `GET /vpn/wireguard/status` - WireGuard status
- `POST /vpn/wireguard/peers` - Create WireGuard peer

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 👨‍💻 Developer

**Erick Vladimir Salgado**
- GitHub: [@Cuban100](https://github.com/Cuban100)
- Email: pctechservices.llc@gmail.com

## 🙏 Acknowledgments

- [WireGuard](https://www.wireguard.com/) - Modern VPN protocol
- [OpenVPN](https://openvpn.net/) - Industry-standard VPN
- [strongSwan](https://www.strongswan.org/) - IKEv2 implementation
- [FastAPI](https://fastapi.tiangolo.com/) - Modern web framework
- [Docker](https://www.docker.com/) - Container platform

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/Cuban100/BartoloVPN/issues)
- **Documentation**: [Wiki](https://github.com/Cuban100/BartoloVPN/wiki)
- **Discussions**: [GitHub Discussions](https://github.com/Cuban100/BartoloVPN/discussions)

---

**Made with ❤️ by Erick Vladimir Salgado**

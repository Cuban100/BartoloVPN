# BartoloVPN Docker Image

[![Docker Pulls](https://img.shields.io/docker/pulls/cuban100/bartolovpn.svg)](https://hub.docker.com/r/cuban100/bartolovpn)
[![Docker Stars](https://img.shields.io/docker/stars/cuban100/bartolovpn.svg)](https://hub.docker.com/r/cuban100/bartolovpn)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive multi-protocol VPN server with web management interface, supporting WireGuard, OpenVPN, and IKEv2 protocols.

## 🚀 Quick Start

### Using Docker Compose (Recommended)

```bash
# Clone the repository
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN

# Copy and configure environment
cp env.example .env
nano .env

# Start all services
docker-compose up -d

# Access web interface
open http://localhost:5000
```

### Using Docker Run

```bash
# Pull the image
docker pull cuban100/bartolovpn:latest

# Run the container
docker run -d \
  --name bartolovpn \
  --privileged \
  -p 5000:5000 \
  -p 51820:51820/udp \
  -p 1194:1194/udp \
  -p 500:500/udp \
  -p 4500:4500/udp \
  -v $(pwd)/config:/config \
  -v $(pwd)/data:/data \
  cuban100/bartolovpn:latest
```

## 🔧 Configuration

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

### Volumes

- `/config` - VPN configuration files
- `/data` - Database and logs
- `/scripts` - Utility scripts

### Ports

- `5000` - Web interface and API
- `51820/udp` - WireGuard VPN
- `1194/udp` - OpenVPN
- `500/udp` - IKEv2 (IKE)
- `4500/udp` - IKEv2 (NAT-T)

## 🌟 Features

### VPN Protocols
- **WireGuard** - Modern, fast VPN protocol
- **OpenVPN** - Industry-standard VPN
- **IKEv2** - Enterprise-grade VPN

### Management Interface
- Real-time dashboard
- User management
- Configuration generation
- System monitoring
- Load balancing

### Advanced Features
- IP rotation
- Geo-spoofing
- Cloudflare Tunnel support
- Multi-user authentication
- JWT-based security

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:5000/health
```

### Logs
```bash
# View all logs
docker logs bartolovpn

# Follow logs
docker logs -f bartolovpn
```

## 🔒 Security

- JWT authentication
- Password hashing with bcrypt
- Network isolation
- Privileged container management
- SSL/TLS encryption

## 🛠️ Development

### Building from Source
```bash
# Clone repository
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN

# Build image
docker build -t cuban100/bartolovpn:latest .

# Run container
docker run -d --name bartolovpn -p 5000:5000 cuban100/bartolovpn:latest
```

### Development Environment
```bash
# Start development stack
docker-compose -f docker-compose.dev.yml up -d

# Run tests
docker-compose exec vpn-api python -m pytest
```

## 📚 Documentation

- [Full Documentation](https://github.com/Cuban100/BartoloVPN)
- [API Reference](https://github.com/Cuban100/BartoloVPN/wiki/API)
- [Troubleshooting](https://github.com/Cuban100/BartoloVPN/wiki/Troubleshooting)

## 🆘 Support

- [GitHub Issues](https://github.com/Cuban100/BartoloVPN/issues)
- [GitHub Discussions](https://github.com/Cuban100/BartoloVPN/discussions)
- Email: admin@bartolovpn.com

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/Cuban100/BartoloVPN/blob/main/LICENSE) file for details.

## 👨‍💻 Developer

**Erick Vladimir Salgado**
- GitHub: [@Cuban100](https://github.com/Cuban100)
- Email: admin@bartolovpn.com

---

**Made with ❤️ by Erick Vladimir Salgado**

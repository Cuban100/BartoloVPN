# BartoloVPN Docker Image

[![Docker Pulls](https://img.shields.io/docker/pulls/cuban100/bartolovpn.svg)](https://hub.docker.com/r/cuban100/bartolovpn)
[![Docker Stars](https://img.shields.io/docker/stars/cuban100/bartolovpn.svg)](https://hub.docker.com/r/cuban100/bartolovpn)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A comprehensive multi-protocol VPN server with web management interface, supporting WireGuard, OpenVPN, and IKEv2 protocols.

## ⚠️ This image is one component of a multi-container stack

`cuban100/bartolovpn` is the **vpn-api** service only - the FastAPI backend and web
dashboard. It is not a standalone all-in-one VPN server: it shares the WireGuard
container's network namespace, reads/writes VPN config through a shared volume,
and talks to sibling containers (WireGuard, OpenVPN, IKEv2, HAProxy, CoreDNS) that
are defined in the project's `docker-compose.yml`. A bare `docker run` of this
image on its own will not give you a working VPN server - use Docker Compose.

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN

# Copy and configure environment
cp env.example .env
nano .env

# Pull/build every service and start the full stack
docker-compose up -d

# Access the web interface (see docker-compose.yml for the ports HAProxy
# publishes on your host)
```

Default credentials come from `WEB_USERNAME`/`WEB_PASSWORD` in your `.env` file.

## 🔧 Configuration

### Key environment variables (set in `.env`, loaded by docker-compose.yml)

```bash
# Server Configuration
SERVER_IP=your-server-ip

# Web Interface
WEB_USERNAME=admin
WEB_PASSWORD=your-secure-password

# VPN Protocols
WIREGUARD_PORT=51820
OPENVPN_PORT=1194
IKEV2_PSK=your-ikev2-pre-shared-key

# Security
JWT_SECRET_KEY=your-super-secret-jwt-key
JWT_EXPIRE_MINUTES=10080
```

### Volumes (as mounted by docker-compose.yml)

- `./config:/config` - shared VPN configuration (WireGuard/OpenVPN/IKEv2), used by vpn-api and the protocol containers
- `./api:/app` - application source
- `./web:/app/web` - Jinja2 templates and static assets for the dashboard

## 🌟 Features

### VPN Protocols
- **WireGuard** - Modern, fast VPN protocol
- **OpenVPN** - Industry-standard VPN
- **IKEv2** - Enterprise-grade VPN

### Management Interface
- Real-time dashboard (WireGuard + OpenVPN monitoring, live stats)
- Per-protocol client/peer management, including WireGuard peer rename
- DNS activity logging per peer/client, with pagination and protocol filtering
- Load balancing via HAProxy

### Advanced Features
- Per-client DNS-region override for OpenVPN clients (changes DNS resolver only, not egress IP)
- Multi-user authentication with JWT-based sessions

## 🛠️ Development

### Building the vpn-api image from source

```bash
git clone https://github.com/Cuban100/BartoloVPN.git
cd BartoloVPN

# Build just this image
docker-compose build vpn-api

# Or manually
docker build -t cuban100/bartolovpn:latest ./api
```

## 📚 Documentation

- [Full Documentation](https://github.com/Cuban100/BartoloVPN)

## 🆘 Support

- [GitHub Issues](https://github.com/Cuban100/BartoloVPN/issues)
- [GitHub Discussions](https://github.com/Cuban100/BartoloVPN/discussions)

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](https://github.com/Cuban100/BartoloVPN/blob/main/LICENSE) file for details.

## 👨‍💻 Developer

**Erick Vladimir Salgado**
- GitHub: [@Cuban100](https://github.com/Cuban100)

---

**Made with ❤️ by Erick Vladimir Salgado**

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

## 📄 docker-compose.yml

For reference, this is the full stack this image is designed to run in (also in the
repo as `docker-compose.yml`). It references a few sibling files from the repo
(`haproxy.cfg`, `scripts/init-openvpn-proper.sh`, `config/openvpn-dns/Corefile`), so
cloning the repo is still the easiest way to run it - this is here so you can see
exactly what you're deploying before you do.

```yaml
services:
  # WireGuard VPN Server
  wireguard:
    image: linuxserver/wireguard:latest
    container_name: bartolo-wireguard
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Etc/UTC
      - SERVERURL=${SERVER_IP}
      - SERVERPORT=${WIREGUARD_PORT:-51820}
      - PEERS=${WIREGUARD_PEERS:-10}
      - PEERDNS=auto
      - INTERNAL_SUBNET=${WIREGUARD_SUBNET:-10.13.13.0}
      - ALLOWEDIPS=${WIREGUARD_ALLOWED_IPS:-0.0.0.0/0}
      - LOG_CONFS=true
    volumes:
      - ./config/wireguard:/config
      - /lib/modules:/lib/modules
    ports:
      - "${WIREGUARD_PORT:-51820}:51820/udp"
      - "${API_PORT:-5000}:5000"
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv4.ip_forward=1
    restart: unless-stopped
    network_mode: bridge

  # OpenVPN Server
  openvpn:
    image: kylemanna/openvpn:latest
    container_name: bartolo-openvpn
    privileged: true
    cap_add:
      - NET_ADMIN
    environment:
      - PUID=1000
      - PGID=1000
    volumes:
      - ./config/openvpn:/etc/openvpn
      - ./scripts:/scripts
    ports:
      - "${OPENVPN_PORT:-1194}:1194/udp"
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv6.conf.all.forwarding=1
      - net.ipv6.conf.default.forwarding=1
    restart: unless-stopped
    networks:
      - vpn-network
      - vpn-external
    depends_on:
      - wireguard
      - openvpn-dns
    command: /scripts/init-openvpn-proper.sh

  # CoreDNS for OpenVPN clients only
  openvpn-dns:
    image: coredns/coredns:latest
    container_name: bartolo-openvpn-dns
    volumes:
      - ./config/openvpn-dns/Corefile:/Corefile:ro
    command: -conf /Corefile
    restart: unless-stopped
    networks:
      vpn-network:
        ipv4_address: 172.27.0.10

  # IKEv2 VPN Server (using strongSwan)
  ikev2:
    image: hwdsl2/ipsec-vpn-server:latest
    container_name: bartolo-ikev2
    privileged: true
    environment:
      - VPN_IPSEC_PSK=${IKEV2_PSK:-your-ikev2-psk}
      - VPN_USER=${IKEV2_USER:-vpnuser}
      - VPN_PASSWORD=${IKEV2_PASSWORD:-vpnpass}
    ports:
      - "500:500/udp"
      - "4500:4500/udp"
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv4.conf.all.accept_redirects=0
      - net.ipv4.conf.all.send_redirects=0
      - net.ipv4.conf.all.rp_filter=1
      - net.ipv4.conf.default.accept_redirects=0
      - net.ipv4.conf.default.send_redirects=0
      - net.ipv4.conf.default.rp_filter=1
    restart: unless-stopped
    networks:
      - vpn-network
      - vpn-external
    depends_on:
      - wireguard

  # Scoped Docker API access for vpn-api: container log fetching (DNS
  # Activity tab) and exec (OpenVPN client certs need the openvpn
  # container's own easyrsa toolchain). Only container list/inspect/logs/exec
  # are enabled - not a general docker socket passthrough.
  docker-log-proxy:
    image: tecnativa/docker-socket-proxy:latest
    container_name: bartolo-docker-log-proxy
    environment:
      - CONTAINERS=1
      - POST=1
      - EXEC=1
      - EVENTS=0
      - INFO=0
      - NETWORKS=0
      - IMAGES=0
      - VOLUMES=0
      - SERVICES=0
      - SWARM=0
      - SYSTEM=0
      - TASKS=0
      - NODES=0
      - PLUGINS=0
      - SECRETS=0
      - CONFIGS=0
      - BUILD=0
      - COMMIT=0
      - DISTRIBUTION=0
      - AUTH=0
      - SESSION=0
      - GRPC=0
      - ALLOW_RESTARTS=0
    volumes:
      - /run/user/1000/docker.sock:/var/run/docker.sock:ro
    network_mode: "service:wireguard"
    depends_on:
      - wireguard
    restart: unless-stopped

  # VPN Management API (this image)
  vpn-api:
    image: cuban100/bartolovpn:latest
    container_name: bartolo-vpn-api
    cap_add:
      - NET_ADMIN
    env_file:
      - .env
    volumes:
      - ./config:/config
    restart: unless-stopped
    network_mode: "service:wireguard"
    depends_on:
      - wireguard
      - openvpn
      - ikev2

  # Load Balancer
  haproxy:
    image: haproxy:alpine
    container_name: bartolo-haproxy
    ports:
      - "8082:80"
      - "8443:443"
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro
    restart: unless-stopped
    networks:
      - vpn-network
      - vpn-external
    depends_on:
      - wireguard
      - openvpn
      - ikev2

networks:
  vpn-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.27.0.0/16
          gateway: 172.27.0.1
  vpn-external:
    driver: bridge
    ipam:
      config:
        - subnet: 10.15.15.0/24
          gateway: 10.15.15.1
```

The full `docker-compose.yml` in the repo builds `vpn-api` from source instead of
pulling this image directly; swap in `image: cuban100/bartolovpn:latest` (as above)
if you'd rather pull the prebuilt image than build it yourself.

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

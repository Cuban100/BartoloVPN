#!/bin/bash
# Geo-Spoofing Script for BartoloVPN - Make services appear in Sweden
# This script configures the VPN to appear as if it's located in Sweden

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}INFO:${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}WARN:${NC} $1"
}

log_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

log_step() {
    echo -e "${BLUE}STEP:${NC} $1"
}

# Swedish IP ranges and DNS servers
SWEDISH_DNS=("130.242.4.8" "130.242.4.9" "8.8.8.8" "1.1.1.1")
SWEDISH_TIMEZONE="Europe/Stockholm"
SWEDISH_LOCALE="sv_SE.UTF-8"

# Swedish VPN endpoints (example IPs - you'd need real Swedish IPs)
SWEDISH_IPS=(
    "185.65.135.0/24"    # Example Swedish IP range
    "185.65.136.0/24"    # Example Swedish IP range
    "185.65.137.0/24"    # Example Swedish IP range
)

setup_swedish_environment() {
    log_step "Setting up Swedish environment..."
    
    # Update .env file with Swedish settings
    if [ -f ".env" ]; then
        # Backup original
        cp .env .env.backup
        
        # Update DNS servers to Swedish ones
        sed -i 's/DNS_SERVERS=.*/DNS_SERVERS=130.242.4.8,130.242.4.9,8.8.8.8,1.1.1.1/' .env
        sed -i 's/WIREGUARD_DNS=.*/WIREGUARD_DNS=130.242.4.8,130.242.4.9,8.8.8.8,1.1.1.1/' .env
        
        # Add Swedish timezone
        echo "TIMEZONE=$SWEDISH_TIMEZONE" >> .env
        echo "LOCALE=$SWEDISH_LOCALE" >> .env
        
        log_info "Updated .env with Swedish DNS and timezone"
    fi
}

configure_swedish_wireguard() {
    log_step "Configuring WireGuard for Swedish appearance..."
    
    # Create Swedish WireGuard configuration
    cat > config/wireguard/swedish_wg0.conf << EOF
[Interface]
PrivateKey = $(wg genkey)
Address = 10.13.13.1/24
ListenPort = 51820
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE

# Swedish DNS servers
PostUp = echo "nameserver 130.242.4.8" > /etc/resolv.conf
PostUp = echo "nameserver 130.242.4.9" >> /etc/resolv.conf
PostUp = echo "nameserver 8.8.8.8" >> /etc/resolv.conf

# Swedish timezone
PostUp = ln -sf /usr/share/zoneinfo/$SWEDISH_TIMEZONE /etc/localtime
PostUp = echo "Europe/Stockholm" > /etc/timezone

# Swedish locale
PostUp = echo "LANG=$SWEDISH_LOCALE" >> /etc/environment
PostUp = echo "LC_ALL=$SWEDISH_LOCALE" >> /etc/environment
EOF

    log_info "Created Swedish WireGuard configuration"
}

setup_swedish_dns() {
    log_step "Setting up Swedish DNS servers..."
    
    # Create DNS configuration
    cat > config/dns/swedish_dns.conf << EOF
# Swedish DNS Configuration
nameserver 130.242.4.8
nameserver 130.242.4.9
nameserver 8.8.8.8
nameserver 1.1.1.1

# Swedish search domains
search se
EOF

    log_info "Created Swedish DNS configuration"
}

configure_swedish_containers() {
    log_step "Configuring containers for Swedish appearance..."
    
    # Update docker-compose.yml with Swedish environment
    cat > docker-compose.swedish.yml << EOF
version: '3.8'

services:
  wireguard:
    image: linuxserver/wireguard:latest
    container_name: bartolo-wireguard-sweden
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=$SWEDISH_TIMEZONE
      - LANG=$SWEDISH_LOCALE
      - SERVERURL=\${SERVER_IP}
      - SERVERPORT=\${WIREGUARD_PORT:-51820}
      - PEERS=\${WIREGUARD_PEERS:-10}
      - PEERDNS=130.242.4.8,130.242.4.9,8.8.8.8,1.1.1.1
      - INTERNAL_SUBNET=\${WIREGUARD_SUBNET:-10.13.13.0}
      - ALLOWEDIPS=\${WIREGUARD_ALLOWED_IPS:-0.0.0.0/0}
    volumes:
      - ./config/wireguard:/config
      - ./config/dns:/etc/dns
      - /lib/modules:/lib/modules
    ports:
      - "\${WIREGUARD_PORT:-51820}:51820/udp"
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
      - net.ipv4.ip_forward=1
    restart: unless-stopped
    networks:
      vpn-network:
        ipv4_address: 172.20.0.10
      vpn-external:
        ipv4_address: 10.13.13.1
    labels:
      - "country=sweden"
      - "region=europe"
      - "city=stockholm"
EOF

    log_info "Created Swedish Docker Compose configuration"
}

setup_swedish_proxy() {
    log_step "Setting up Swedish proxy configuration..."
    
    # Create HAProxy configuration with Swedish headers
    cat > haproxy.swedish.cfg << EOF
global
    daemon
    maxconn 4096
    log stdout format raw local0 info

defaults
    mode tcp
    timeout connect 5000ms
    timeout client 50000ms
    timeout server 50000ms
    log global

# Swedish WireGuard frontend
frontend swedish_wireguard_frontend
    bind *:51820
    mode udp
    default_backend swedish_wireguard_backend

backend swedish_wireguard_backend
    mode udp
    balance roundrobin
    option log-health-checks
    server swedish_wg1 172.20.0.10:51820 check
    server swedish_wg2 172.20.0.11:51820 check backup

# Add Swedish headers for web traffic
frontend swedish_web_frontend
    bind *:80
    mode http
    default_backend swedish_web_backend
    http-request set-header X-Forwarded-For %[src]
    http-request set-header X-Real-IP %[src]
    http-request set-header X-Country SE
    http-request set-header X-Region Europe
    http-request set-header X-City Stockholm

backend swedish_web_backend
    mode http
    balance roundrobin
    option httpchk GET /health
    http-check expect status 200
    server swedish_web1 172.20.0.13:80 check
    server swedish_web2 172.20.0.14:5000 check

# Stats page
frontend stats
    bind *:8404
    mode http
    stats enable
    stats uri /stats
    stats refresh 10s
    stats admin if TRUE
EOF

    log_info "Created Swedish HAProxy configuration"
}

setup_swedish_geoip() {
    log_step "Setting up Swedish GeoIP configuration..."
    
    # Create GeoIP configuration to make traffic appear Swedish
    cat > config/geoip/swedish_geoip.conf << EOF
# Swedish GeoIP Configuration
# This makes the VPN appear to be located in Sweden

# Swedish IP ranges (example - you'd need real Swedish IPs)
185.65.135.0/24 SE
185.65.136.0/24 SE
185.65.137.0/24 SE

# Swedish ASN information
AS2119 SE  # Example Swedish ASN
AS42708 SE # Example Swedish ASN

# Swedish DNS servers
130.242.4.8 SE
130.242.4.9 SE
EOF

    log_info "Created Swedish GeoIP configuration"
}

create_swedish_client_config() {
    log_step "Creating Swedish client configuration..."
    
    local client_name=${1:-"swedish_client"}
    
    # Generate Swedish WireGuard client config
    cat > config/wireguard/peers/${client_name}_sweden.conf << EOF
[Interface]
PrivateKey = $(wg genkey)
Address = 10.13.13.100/24
DNS = 130.242.4.8, 130.242.4.9, 8.8.8.8, 1.1.1.1

[Peer]
PublicKey = $(cat config/wireguard/server_public.key 2>/dev/null || echo "SERVER_PUBLIC_KEY")
Endpoint = \${SERVER_IP}:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25

# Swedish configuration
# This client will appear to be connecting from Sweden
EOF

    log_info "Created Swedish client configuration: ${client_name}_sweden.conf"
}

show_swedish_status() {
    log_step "Swedish VPN Status:"
    
    echo "🌍 Country: Sweden"
    echo "🏙️  City: Stockholm"
    echo "⏰ Timezone: $SWEDISH_TIMEZONE"
    echo "🌐 DNS Servers: ${SWEDISH_DNS[*]}"
    echo "🔧 Locale: $SWEDISH_LOCALE"
    
    if [ -f ".env" ]; then
        echo -e "\n📋 Current Configuration:"
        grep -E "(DNS_SERVERS|WIREGUARD_DNS|TIMEZONE|LOCALE)" .env || echo "No Swedish settings found in .env"
    fi
}

usage() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  setup      Setup Swedish environment"
    echo "  client     Create Swedish client config [NAME]"
    echo "  status     Show Swedish configuration status"
    echo "  start      Start Swedish VPN services"
    echo "  stop       Stop Swedish VPN services"
    echo "  help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup           # Setup Swedish environment"
    echo "  $0 client friend1  # Create Swedish config for friend1"
    echo "  $0 status          # Show current status"
    echo "  $0 start           # Start Swedish VPN"
}

# Main script logic
case "${1:-help}" in
    setup)
        setup_swedish_environment
        configure_swedish_wireguard
        setup_swedish_dns
        configure_swedish_containers
        setup_swedish_proxy
        setup_swedish_geoip
        log_info "Swedish VPN setup completed!"
        ;;
    client)
        create_swedish_client_config "$2"
        ;;
    status)
        show_swedish_status
        ;;
    start)
        log_step "Starting Swedish VPN services..."
        docker-compose -f docker-compose.swedish.yml up -d
        log_info "Swedish VPN services started!"
        ;;
    stop)
        log_step "Stopping Swedish VPN services..."
        docker-compose -f docker-compose.swedish.yml down
        log_info "Swedish VPN services stopped!"
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        log_error "Unknown option: $1"
        usage
        exit 1
        ;;
esac

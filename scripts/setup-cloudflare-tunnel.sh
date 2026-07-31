#!/bin/bash
# Cloudflare Tunnel Setup Script for BartoloVPN
# This script automates the setup of Cloudflare Tunnel for secure access

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

# Configuration - reads from .env if present, otherwise prompts. Nothing
# here should be a hardcoded personal value: this script is meant to be run
# by anyone deploying BartoloVPN, not just the original setup.
if [ -f "$(dirname "$0")/../.env" ]; then
    # shellcheck disable=SC1090
    source "$(dirname "$0")/../.env"
fi

DOMAIN="${DOMAIN:-}"
TUNNEL_NAME="${TUNNEL_NAME:-bartolo-vpn}"
LOCAL_IP="${LOCAL_IP:-}"
API_PORT="${API_PORT:-5000}"
WEB_PORT="${WEB_PORT:-8080}"
STATS_PORT="${STATS_PORT:-8404}"

if [ -z "$DOMAIN" ]; then
    read -rp "Enter your domain (e.g. example.com): " DOMAIN
fi
if [ -z "$LOCAL_IP" ]; then
    read -rp "Enter this server's local IP (e.g. 192.168.1.100): " LOCAL_IP
fi

install_cloudflared() {
    log_step "Installing Cloudflare Tunnel (cloudflared)..."
    
    # Check if already installed
    if command -v cloudflared &> /dev/null; then
        log_info "cloudflared is already installed"
        cloudflared --version
        return
    fi
    
    # Download and install
    cd /tmp
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    
    if [ $? -eq 0 ]; then
        sudo dpkg -i cloudflared-linux-amd64.deb
        log_info "cloudflared installed successfully"
        cloudflared --version
    else
        log_error "Failed to download cloudflared"
        exit 1
    fi
}

authenticate_cloudflare() {
    log_step "Authenticating with Cloudflare..."
    
    # Check if already authenticated
    if [ -f ~/.cloudflared/cert.pem ]; then
        log_info "Already authenticated with Cloudflare"
        return
    fi
    
    log_warn "This will open a browser window for authentication"
    log_info "Please select your domain: $DOMAIN"
    
    cloudflared tunnel login
    
    if [ $? -eq 0 ]; then
        log_info "Authentication successful"
    else
        log_error "Authentication failed"
        exit 1
    fi
}

create_tunnel() {
    log_step "Creating Cloudflare tunnel..."
    
    # Check if tunnel already exists
    if cloudflared tunnel list | grep -q "$TUNNEL_NAME"; then
        log_info "Tunnel '$TUNNEL_NAME' already exists"
        TUNNEL_ID=$(cloudflared tunnel list | grep "$TUNNEL_NAME" | awk '{print $1}')
    else
        TUNNEL_ID=$(cloudflared tunnel create "$TUNNEL_NAME" | grep "Created tunnel" | awk '{print $3}')
        log_info "Created tunnel: $TUNNEL_ID"
    fi
    
    echo "$TUNNEL_ID" > .tunnel_id
}

create_config() {
    log_step "Creating tunnel configuration..."
    
    TUNNEL_ID=$(cat .tunnel_id)
    
    # Create config directory
    mkdir -p config/cloudflared
    
    # Create configuration file
    cat > config/cloudflared/config.yml << EOF
tunnel: $TUNNEL_ID
credentials-file: /etc/cloudflared/$TUNNEL_ID.json

ingress:
  # VPN Management Interface (FastAPI)
  - hostname: vpn.$DOMAIN
    service: http://$LOCAL_IP:$API_PORT
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
      readTimeout: 30s
  
  # Web UI (if separate)
  - hostname: vpn-ui.$DOMAIN
    service: http://$LOCAL_IP:$WEB_PORT
    originRequest:
      noTLSVerify: true
  
  # HAProxy Stats (optional)
  - hostname: vpn-stats.$DOMAIN
    service: http://$LOCAL_IP:$STATS_PORT
    originRequest:
      noTLSVerify: true
  
  # Catch-all rule (must be last)
  - service: http_status:404
EOF

    log_info "Configuration created: config/cloudflared/config.yml"
}

setup_dns() {
    log_step "Setting up DNS records..."
    
    # Create DNS records
    cloudflared tunnel route dns "$TUNNEL_NAME" "vpn.$DOMAIN"
    cloudflared tunnel route dns "$TUNNEL_NAME" "vpn-ui.$DOMAIN"
    cloudflared tunnel route dns "$TUNNEL_NAME" "vpn-stats.$DOMAIN"
    
    log_info "DNS records created:"
    log_info "  - vpn.$DOMAIN"
    log_info "  - vpn-ui.$DOMAIN"
    log_info "  - vpn-stats.$DOMAIN"
}

update_docker_compose() {
    log_step "Updating Docker Compose configuration..."
    
    # Check if cloudflared service already exists
    if grep -q "cloudflared:" docker-compose.yml; then
        log_info "Cloudflare service already exists in docker-compose.yml"
        return
    fi
    
    # Add cloudflared service to docker-compose.yml
    cat >> docker-compose.yml << 'EOF'

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: bartolo-cloudflared
    restart: unless-stopped
    command: tunnel --config /etc/cloudflared/config.yml run bartolo-vpn
    volumes:
      - ./config/cloudflared:/etc/cloudflared:ro
    networks:
      vpn-network:
        ipv4_address: 172.20.0.20
    depends_on:
      - vpn-api
      - web-ui
      - haproxy
    labels:
      - "traefik.enable=false"
EOF

    log_info "Added cloudflared service to docker-compose.yml"
}

create_systemd_service() {
    log_step "Creating systemd service for cloudflared..."
    
    # Create systemd service file
    sudo tee /etc/systemd/system/cloudflared.service > /dev/null << EOF
[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
Type=simple
User=$USER
ExecStart=/usr/local/bin/cloudflared tunnel --config /home/$USER/BartoloVPN/config/cloudflared/config.yml run bartolo-vpn
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # Enable and start service
    sudo systemctl daemon-reload
    sudo systemctl enable cloudflared
    sudo systemctl start cloudflared
    
    log_info "Systemd service created and started"
}

test_tunnel() {
    log_step "Testing tunnel connectivity..."
    
    # Wait a moment for tunnel to establish
    sleep 5
    
    # Test DNS resolution
    if nslookup "vpn.$DOMAIN" > /dev/null 2>&1; then
        log_info "DNS resolution working for vpn.$DOMAIN"
    else
        log_warn "DNS resolution may take a few minutes to propagate"
    fi
    
    # Test tunnel status
    if cloudflared tunnel info "$TUNNEL_NAME" > /dev/null 2>&1; then
        log_info "Tunnel is running and healthy"
    else
        log_error "Tunnel may not be running properly"
    fi
}

show_access_info() {
    log_step "Access Information:"
    echo ""
    echo "🌐 VPN Management Interface:"
    echo "   https://vpn.$DOMAIN"
    echo ""
    echo "🖥️  Web UI:"
    echo "   https://vpn-ui.$DOMAIN"
    echo ""
    echo "📊 HAProxy Stats:"
    echo "   https://vpn-stats.$DOMAIN"
    echo ""
    echo "🔧 Next Steps:"
    echo "   1. Configure access policies in Cloudflare Dashboard"
    echo "   2. Set up authentication methods"
    echo "   3. Test access from external networks"
    echo "   4. Monitor tunnel health"
    echo ""
}

usage() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  setup      Complete setup (install, auth, create, configure)"
    echo "  install    Install cloudflared only"
    echo "  auth       Authenticate with Cloudflare only"
    echo "  create     Create tunnel only"
    echo "  config     Create configuration only"
    echo "  dns        Setup DNS records only"
    echo "  docker     Update Docker Compose only"
    echo "  service    Create systemd service only"
    echo "  test       Test tunnel connectivity"
    echo "  info       Show access information"
    echo "  help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 setup           # Complete setup"
    echo "  $0 install         # Install cloudflared"
    echo "  $0 test            # Test connectivity"
}

# Main script logic
case "${1:-help}" in
    setup)
        install_cloudflared
        authenticate_cloudflare
        create_tunnel
        create_config
        setup_dns
        update_docker_compose
        create_systemd_service
        test_tunnel
        show_access_info
        log_info "Cloudflare Tunnel setup completed!"
        ;;
    install)
        install_cloudflared
        ;;
    auth)
        authenticate_cloudflare
        ;;
    create)
        create_tunnel
        ;;
    config)
        create_config
        ;;
    dns)
        setup_dns
        ;;
    docker)
        update_docker_compose
        ;;
    service)
        create_systemd_service
        ;;
    test)
        test_tunnel
        ;;
    info)
        show_access_info
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

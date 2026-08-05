#!/bin/bash
# Docker Network IP Rotation Script for BartoloVPN
#
# Rotates VPN containers' *internal* Docker bridge-network IPs (the
# 10.13.13.x-range addresses assigned inside vpn-external) and reloads
# HAProxy with the new addresses. This has no effect on the VPN's actual
# public exit IP as seen by connected clients or the wider internet - that's
# determined by SERVER_IP / the host's real IP and each protocol's own
# listener, neither of which this touches. Internal bridge IPs were never
# visible outside the Docker host in the first place, so rotating them does
# not provide anonymity or "avoid detection" in any external sense - this is
# purely internal bookkeeping. For a genuinely different exit IP, see
# MULTI-REGION.md instead.

set -e

# Configuration
NETWORK_NAME="bartolovpn_vpn-external"
ROTATION_INTERVAL=3600  # 1 hour
LOG_FILE="/var/log/docker-ip-rotation.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO: $1"
    echo -e "${GREEN}INFO:${NC} $1"
}

log_warn() {
    log "WARN: $1"
    echo -e "${YELLOW}WARN:${NC} $1"
}

log_error() {
    log "ERROR: $1"
    echo -e "${RED}ERROR:${NC} $1"
}

# Check if Docker is running
check_docker() {
    if ! docker info >/dev/null 2>&1; then
        log_error "Docker is not running or not accessible"
        exit 1
    fi
}

# Get current IP addresses from environment
get_current_ips() {
    if [ -f ".env" ]; then
        source .env
        echo "$SERVER_IP $PREVIOUS_IPS" | tr ',' ' '
    else
        log_error ".env file not found"
        exit 1
    fi
}

# Rotate IP addresses in Docker network
rotate_network_ips() {
    local ips=($(get_current_ips))
    local current_ip="${ips[0]}"
    
    log_info "Current external IP: $current_ip"
    
    # Get all containers in the VPN external network
    local containers=$(docker network inspect "$NETWORK_NAME" --format '{{range .Containers}}{{.Name}} {{end}}' 2>/dev/null || echo "")
    
    if [ -z "$containers" ]; then
        log_warn "No containers found in network $NETWORK_NAME"
        return
    fi
    
    for container in $containers; do
        log_info "Rotating IP for container: $container"
        
        # Disconnect from current network
        docker network disconnect "$NETWORK_NAME" "$container" 2>/dev/null || true
        
        # Wait a moment
        sleep 2
        
        # Reconnect with new IP (Docker will assign a new IP)
        docker network connect "$NETWORK_NAME" "$container" 2>/dev/null || true
        
        # Get new IP
        local new_ip=$(docker inspect "$container" --format '{{range .NetworkSettings.Networks.bartolovpn_vpn-external}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "")
        
        if [ -n "$new_ip" ]; then
            log_info "Container $container now has IP: $new_ip"
        else
            log_warn "Could not get new IP for container $container"
        fi
    done
}

# Update HAProxy configuration with new IPs
update_haproxy_config() {
    log_info "Updating HAProxy configuration..."
    
    # Get current container IPs
    local wireguard_ip=$(docker inspect bartolovpn-wireguard --format '{{range .NetworkSettings.Networks.bartolovpn_vpn-external}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "10.13.13.1")
    local openvpn_ip=$(docker inspect bartolovpn-openvpn --format '{{range .NetworkSettings.Networks.bartolovpn_vpn-external}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "10.13.13.2")
    local ikev2_ip=$(docker inspect bartolovpn-ikev2 --format '{{range .NetworkSettings.Networks.bartolovpn_vpn-external}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "10.13.13.3")
    
    # Update haproxy.cfg with new IPs
    sed -i "s/server wireguard1 .*:51820/server wireguard1 $wireguard_ip:51820/g" haproxy.cfg
    sed -i "s/server openvpn1 .*:1194/server openvpn1 $openvpn_ip:1194/g" haproxy.cfg
    sed -i "s/server ikev2_500 .*:500/server ikev2_500 $ikev2_ip:500/g" haproxy.cfg
    sed -i "s/server ikev2_4500 .*:4500/server ikev2_4500 $ikev2_ip:4500/g" haproxy.cfg
    
    # Reload HAProxy
    docker exec bartolovpn-haproxy haproxy -f /usr/local/etc/haproxy/haproxy.cfg -c >/dev/null 2>&1 && \
    docker exec bartolovpn-haproxy kill -HUP 1 >/dev/null 2>&1 && \
    log_info "HAProxy configuration reloaded successfully" || \
    log_warn "Could not reload HAProxy configuration"
}

# Main rotation function
main_rotation() {
    log_info "Starting Docker network IP rotation..."
    
    check_docker
    rotate_network_ips
    update_haproxy_config
    
    log_info "IP rotation completed successfully"
}

# Continuous rotation loop
continuous_rotation() {
    log_info "Starting continuous IP rotation (interval: ${ROTATION_INTERVAL}s)"
    
    while true; do
        main_rotation
        log_info "Waiting ${ROTATION_INTERVAL} seconds until next rotation..."
        sleep "$ROTATION_INTERVAL"
    done
}

# Show current network status
show_status() {
    log_info "Current Docker network status:"
    
    echo "Network: $NETWORK_NAME"
    docker network inspect "$NETWORK_NAME" --format '{{range .Containers}}{{.Name}}: {{.IPv4Address}}{{"\n"}}{{end}}' 2>/dev/null || echo "Network not found"
    
    echo -e "\nContainer IPs:"
    for container in bartolovpn-wireguard bartolovpn-openvpn bartolovpn-ikev2 bartolovpn-haproxy; do
        if docker ps --format "{{.Names}}" | grep -q "^${container}$"; then
            local ip=$(docker inspect "$container" --format '{{range .NetworkSettings.Networks.bartolovpn_vpn-external}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "N/A")
            echo "$container: $ip"
        else
            echo "$container: Not running"
        fi
    done
}

# Usage
usage() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  rotate     Perform a single IP rotation"
    echo "  continuous Start continuous rotation loop"
    echo "  status     Show current network status"
    echo "  help       Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 rotate      # Rotate IPs once"
    echo "  $0 continuous  # Start continuous rotation"
    echo "  $0 status      # Show current status"
}

# Main script logic
case "${1:-help}" in
    rotate)
        main_rotation
        ;;
    continuous)
        continuous_rotation
        ;;
    status)
        show_status
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

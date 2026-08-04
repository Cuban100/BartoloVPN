#!/bin/bash
# Provision this box as a new BartoloVPN region: installs Docker, generates
# the agent's API key and TLS config, and brings up region-agent/'s stack
# (wireguard + region-agent + caddy). Run this ON THE FRESH VPS itself
# (over SSH), from a clone of this repo, e.g.:
#
#   git clone https://github.com/Cuban100/BartoloVPN.git
#   cd BartoloVPN
#   sudo ./scripts/provision-region.sh
#
# When it finishes, it prints a block of values (agent URL, agent key,
# endpoint host/port, slug/display info) to paste into the central
# BartoloVPN dashboard's Regions tab -> Add Region form. The agent key is
# shown exactly once - it is not written to any log file - so capture it
# before closing this terminal.
#
# See MULTI-REGION.md for the full architecture and local (no-VPS) testing
# instructions.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}INFO:${NC} $1"; }
log_warn()  { echo -e "${YELLOW}WARN:${NC} $1"; }
log_error() { echo -e "${RED}ERROR:${NC} $1"; }
log_step()  { echo -e "${BLUE}STEP:${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
REGION_AGENT_DIR="$PROJECT_ROOT/region-agent"

if [ ! -d "$REGION_AGENT_DIR" ]; then
    log_error "Could not find region-agent/ next to this script - run this from a full clone of the BartoloVPN repo."
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    log_error "This installs system packages and opens firewall ports - run it with sudo."
    exit 1
fi

log_step "This will turn this VPS into a new BartoloVPN WireGuard region."
echo

read -rp "Is this an Oracle Cloud (OCI) VPS? [y/N]: " IS_ORACLE
IS_ORACLE="${IS_ORACLE:-n}"
if [[ "$IS_ORACLE" =~ ^[Yy] ]]; then
    log_info "Oracle Cloud mode enabled - this run will also patch OCI's default iptables rules and remind you about the Security List firewall in the OCI console."
else
    log_info "Skipping Oracle-specific setup - proceeding as a generic VPS."
fi
echo

read -rp "Region slug (lowercase, e.g. de-fra1): " REGION_SLUG
read -rp "Display name (e.g. Germany - Frankfurt): " REGION_DISPLAY_NAME
read -rp "Country code (2 letters, e.g. DE): " REGION_COUNTRY_CODE
read -rp "City (optional, press enter to skip): " REGION_CITY

DETECTED_IP=$(curl -s --max-time 5 ifconfig.me || true)
if [ -n "$DETECTED_IP" ]; then
    log_info "Detected public IP: $DETECTED_IP"
fi
read -rp "This VPS's public IP [$DETECTED_IP]: " SERVER_IP
SERVER_IP="${SERVER_IP:-$DETECTED_IP}"
if [ -z "$SERVER_IP" ]; then
    log_error "No public IP provided or detected - can't continue."
    exit 1
fi

DEFAULT_HOSTNAME="${SERVER_IP//./-}.sslip.io"
echo
log_info "The agent needs a hostname pointed at $SERVER_IP so Caddy can issue a real TLS certificate."
log_info "If you don't own a domain, sslip.io gives you one for free with zero DNS setup: $DEFAULT_HOSTNAME"
read -rp "Agent hostname [$DEFAULT_HOSTNAME]: " AGENT_HOSTNAME
AGENT_HOSTNAME="${AGENT_HOSTNAME:-$DEFAULT_HOSTNAME}"

read -rp "WireGuard port [51820]: " WIREGUARD_PORT
WIREGUARD_PORT="${WIREGUARD_PORT:-51820}"

log_step "Installing Docker, the Compose plugin, ufw, and jq..."
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-plugin ufw curl jq >/dev/null
systemctl enable --now docker >/dev/null 2>&1 || true

AGENT_API_KEY=$(openssl rand -hex 32)

ENV_FILE="$REGION_AGENT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    log_warn "$ENV_FILE already exists - backing it up rather than overwriting."
    cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%s)"
fi

log_step "Writing $ENV_FILE..."
cat > "$ENV_FILE" <<EOF
AGENT_API_KEY=$AGENT_API_KEY
SERVER_IP=$SERVER_IP
WIREGUARD_PORT=$WIREGUARD_PORT
WIREGUARD_SUBNET=10.13.13.0
AGENT_HOSTNAME=$AGENT_HOSTNAME
EOF
chmod 600 "$ENV_FILE"

log_step "Opening firewall ports (22/tcp, 80/tcp, 443/tcp, ${WIREGUARD_PORT}/udp)..."
ufw allow 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow "${WIREGUARD_PORT}/udp" >/dev/null
ufw --force enable >/dev/null

ORACLE_SECURITY_LIST_REMINDER=""
if [[ "$IS_ORACLE" =~ ^[Yy] ]]; then
    log_step "Oracle Cloud detected - adjusting the pre-installed iptables rules..."
    # Oracle's stock Ubuntu images ship with their own iptables rules
    # (persisted via netfilter-persistent/iptables-persistent) that only
    # allow SSH and REJECT everything else, on top of whatever ufw does -
    # ufw manages its own chains, but traffic can still be dropped by these
    # pre-existing rules first since they're evaluated earlier in INPUT.
    # Inserting ACCEPT rules at the very top of INPUT guarantees they're
    # hit before any REJECT rule further down, regardless of where it is.
    if command -v iptables >/dev/null 2>&1; then
        iptables -I INPUT 1 -p udp --dport "$WIREGUARD_PORT" -j ACCEPT
        iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
        iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
        if command -v netfilter-persistent >/dev/null 2>&1; then
            netfilter-persistent save >/dev/null 2>&1 || true
        elif [ -d /etc/iptables ]; then
            iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
        fi
        log_info "iptables rules updated and saved."
    else
        log_warn "iptables not found - skipping (this image may not need it)."
    fi

    ORACLE_SECURITY_LIST_REMINDER="Oracle Cloud has a SECOND firewall you must open in the console (this script cannot reach it): Networking -> Virtual Cloud Networks -> your VCN -> Security Lists -> Default Security List -> Add Ingress Rules for ${WIREGUARD_PORT}/UDP, 80/TCP, and 443/TCP from source 0.0.0.0/0. Nothing will be reachable from the internet until this is done, even though everything on the box itself is correctly configured."
    log_warn "$ORACLE_SECURITY_LIST_REMINDER"
fi

log_step "Building and starting the region stack (this can take a few minutes)..."
(cd "$REGION_AGENT_DIR" && docker compose up -d --build)

log_step "Waiting for the agent to report healthy..."
HEALTHY=false
for _ in $(seq 1 30); do
    if docker exec bartolo-region-agent curl -s --max-time 3 http://127.0.0.1:8912/health 2>/dev/null | grep -q healthy; then
        HEALTHY=true
        break
    fi
    sleep 5
done

if [ "$HEALTHY" != "true" ]; then
    log_warn "Agent did not report healthy within 2.5 minutes - check with: cd $REGION_AGENT_DIR && docker compose logs"
    log_warn "Continuing anyway - the values below are still correct if you fix it manually."
else
    log_info "Agent is healthy."
fi

print_manual_block() {
    echo
    echo "=================================================================="
    echo " Paste these into the central dashboard's Regions tab -> Add Region"
    echo " form. The agent key below is shown ONCE and is not logged anywhere -"
    echo " copy it now."
    echo "=================================================================="
    echo "  Slug:                     $REGION_SLUG"
    echo "  Display name:             $REGION_DISPLAY_NAME"
    echo "  Country code:             $REGION_COUNTRY_CODE"
    echo "  City:                     ${REGION_CITY:-(none)}"
    echo "  Agent URL:                https://$AGENT_HOSTNAME"
    echo "  Agent key:                $AGENT_API_KEY"
    echo "  WireGuard endpoint host:  $SERVER_IP"
    echo "  WireGuard endpoint port:  $WIREGUARD_PORT"
    echo "=================================================================="
}

echo
log_step "Last step: register this region with your BartoloVPN dashboard."
log_info "Needs your dashboard's admin login once, just to make the API call - nothing is stored on this VPS."
read -rp "Auto-register with your dashboard now? [Y/n]: " AUTO_REGISTER
AUTO_REGISTER="${AUTO_REGISTER:-y}"

REGISTERED=false
if [[ "$AUTO_REGISTER" =~ ^[Yy] ]]; then
    read -rp "Dashboard URL (e.g. https://bartolovpn.caveplex.com): " DASHBOARD_URL
    DASHBOARD_URL="${DASHBOARD_URL%/}"
    read -rp "Dashboard admin username: " DASHBOARD_ADMIN_USER
    read -rsp "Dashboard admin password: " DASHBOARD_ADMIN_PASS
    echo

    if [ -z "$DASHBOARD_URL" ] || [ -z "$DASHBOARD_ADMIN_USER" ] || [ -z "$DASHBOARD_ADMIN_PASS" ]; then
        log_warn "Missing dashboard URL/username/password - skipping auto-registration."
    else
        log_step "Logging in to $DASHBOARD_URL..."
        LOGIN_RESPONSE=$(curl -s --max-time 10 -X POST "$DASHBOARD_URL/auth/login" \
            -H "Content-Type: application/json" \
            -d "$(jq -n --arg u "$DASHBOARD_ADMIN_USER" --arg p "$DASHBOARD_ADMIN_PASS" '{username:$u,password:$p}')")
        DASHBOARD_ADMIN_PASS=""  # clear from memory as soon as it's been used
        TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token // empty')

        if [ -z "$TOKEN" ]; then
            log_error "Login failed: $(echo "$LOGIN_RESPONSE" | jq -r '.detail // "unknown error"')"
            log_warn "Falling back to manual registration - use the values below."
        else
            log_step "Registering region '$REGION_SLUG'..."
            REGION_BODY=$(jq -n \
                --arg slug "$REGION_SLUG" \
                --arg display_name "$REGION_DISPLAY_NAME" \
                --arg country_code "$REGION_COUNTRY_CODE" \
                --arg city "$REGION_CITY" \
                --arg agent_url "https://$AGENT_HOSTNAME" \
                --arg agent_key "$AGENT_API_KEY" \
                --arg wireguard_endpoint_host "$SERVER_IP" \
                --argjson wireguard_endpoint_port "$WIREGUARD_PORT" \
                '{slug:$slug, display_name:$display_name, country_code:$country_code, city:$city, agent_url:$agent_url, agent_key:$agent_key, wireguard_endpoint_host:$wireguard_endpoint_host, wireguard_endpoint_port:$wireguard_endpoint_port}')

            # Caddy may still be obtaining its first Let's Encrypt cert -
            # retry a few times before giving up, instead of failing on one
            # bad-timing attempt.
            for attempt in 1 2 3 4 5 6; do
                REGISTER_RESPONSE=$(curl -s --max-time 15 -o /tmp/register_response.json -w "%{http_code}" -X POST "$DASHBOARD_URL/regions" \
                    -H "Content-Type: application/json" \
                    -H "Authorization: Bearer $TOKEN" \
                    -d "$REGION_BODY")
                if [ "$REGISTER_RESPONSE" = "200" ]; then
                    REGISTERED=true
                    break
                fi
                log_warn "Attempt $attempt/6 failed (HTTP $REGISTER_RESPONSE) - $(jq -r '.detail // "unknown error"' /tmp/register_response.json 2>/dev/null). Retrying in 10s..."
                sleep 10
            done
            rm -f /tmp/register_response.json

            if [ "$REGISTERED" = "true" ]; then
                log_info "Region '$REGION_SLUG' registered successfully - it's already live in your dashboard's Regions tab and the WireGuard peer-creation region picker."
            else
                log_error "Auto-registration failed after 6 attempts. Falling back to manual registration - use the values below."
            fi
        fi
    fi
else
    log_info "Skipping auto-registration - use the values below to register manually."
fi

if [ "$REGISTERED" != "true" ]; then
    print_manual_block
    log_warn "It can take a minute for Caddy to obtain its Let's Encrypt certificate the first time https://$AGENT_HOSTNAME is hit - if Add Region fails immediately, wait ~30s and retry."
fi

if [ -n "$ORACLE_SECURITY_LIST_REMINDER" ]; then
    echo
    log_warn "REMINDER: $ORACLE_SECURITY_LIST_REMINDER"
fi

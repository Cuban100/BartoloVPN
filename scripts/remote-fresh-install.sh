#!/bin/bash
# Wipes any existing BartoloVPN clone on a remote VPS and re-clones it from
# scratch, then hands you an interactive SSH session to run ./install.sh
# yourself - for testing the genuine first-time setup experience.
#
# Run this ON YOUR OWN MACHINE (not on the VPS). It doesn't remember
# anything between runs - always asks for the IP and key fresh, so it
# behaves the same whether this is the first time or the tenth.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}INFO:${NC} $1"; }
log_warn()  { echo -e "${YELLOW}WARN:${NC} $1"; }
log_error() { echo -e "${RED}ERROR:${NC} $1"; }

read -rp "VPS IP address: " VPS_IP
if [ -z "$VPS_IP" ]; then
    log_error "No IP provided."
    exit 1
fi

DEFAULT_KEY="$HOME/.ssh/oracle.key"
read -rp "SSH private key path [$DEFAULT_KEY]: " SSH_KEY
SSH_KEY="${SSH_KEY:-$DEFAULT_KEY}"
SSH_KEY="${SSH_KEY/#\~/$HOME}"

while [ ! -f "$SSH_KEY" ]; do
    log_warn "No key found at $SSH_KEY."
    read -rp "Place your private key there, or type the correct path (blank to abort): " SSH_KEY_RETRY
    if [ -z "$SSH_KEY_RETRY" ]; then
        log_error "No valid SSH key - aborting."
        exit 1
    fi
    SSH_KEY="${SSH_KEY_RETRY/#\~/$HOME}"
done
log_info "Using key: $SSH_KEY"

read -rp "SSH username [ubuntu]: " SSH_USER
SSH_USER="${SSH_USER:-ubuntu}"

log_info "Connecting to $SSH_USER@$VPS_IP to wipe and re-clone..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$SSH_USER@$VPS_IP" bash -s << 'REMOTE'
set -e
if [ -d ~/BartoloVPN/region-agent ] && command -v docker >/dev/null 2>&1; then
    echo "Stopping any existing region-agent containers..."
    (cd ~/BartoloVPN/region-agent && sudo docker compose down 2>/dev/null) || true
fi
if [ -d ~/BartoloVPN ]; then
    echo "Removing existing ~/BartoloVPN clone..."
    sudo rm -rf ~/BartoloVPN
fi
echo "Cloning fresh copy..."
git clone https://github.com/Cuban100/BartoloVPN.git ~/BartoloVPN
REMOTE

log_info "Fresh clone ready on $VPS_IP. Dropping you into an interactive session to run ./install.sh yourself (it needs a real terminal for its prompts)."
ssh -t -i "$SSH_KEY" "$SSH_USER@$VPS_IP" "cd ~/BartoloVPN && ./install.sh"

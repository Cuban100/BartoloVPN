#!/bin/bash
# OpenVPN Proper Initialization Script for BartoloVPN

set -e

OPENVPN_DIR="/etc/openvpn"
SERVER_IP="${SERVER_IP:-72.238.72.252}"

echo "Initializing OpenVPN configuration..."

# Create necessary directories
mkdir -p "$OPENVPN_DIR"
mkdir -p "$OPENVPN_DIR/pki"

# Generate OpenVPN configuration. Pushes our own CoreDNS instance (a
# separate container on this same network, see docker-compose.yml's
# openvpn-dns service) instead of a public resolver, so DNS Activity
# tracking (dns_activity.py) can see OpenVPN clients' queries too -
# they'd otherwise never touch anything the app can log. -D suppresses
# ovpn_genconfig's own default DNS push (8.8.8.8/8.8.4.4) - without it,
# -n only adds to that list rather than replacing it, and most clients
# would keep resolving via Google first, bypassing our logging entirely.
OPENVPN_DNS="${OPENVPN_DNS:-172.27.0.10}"
echo "Generating OpenVPN configuration..."
ovpn_genconfig -u udp://$SERVER_IP:1194 -s 10.8.0.0/24 -D -n "$OPENVPN_DNS"

# Initialize PKI non-interactively - but only the first time. ovpn_initpki
# calls "easyrsa init-pki", which unconditionally wipes and recreates the
# entire PKI (CA, every issued client cert, everything) with no existence
# check of its own - combined with EASYRSA_BATCH=1 auto-confirming the
# prompt that would normally warn about that, every container restart was
# silently destroying every OpenVPN client's certificate. ovpn_genconfig
# above stays unconditional since regenerating server config is harmless
# and lets settings like OPENVPN_DNS actually take effect on restart.
if [ ! -f "$OPENVPN_DIR/pki/ca.crt" ]; then
    echo "No existing PKI found - creating CA certificate for the first time..."
    export EASYRSA_BATCH=1
    export EASYRSA_REQ_CN="BartoloVPN CA"
    export EASYRSA_REQ_COUNTRY="US"
    export EASYRSA_REQ_PROVINCE="CA"
    export EASYRSA_REQ_CITY="San Francisco"
    export EASYRSA_REQ_ORG="BartoloVPN"
    export EASYRSA_REQ_EMAIL="admin@bartolovpn.com"
    export EASYRSA_REQ_OU="BartoloVPN"
    ovpn_initpki nopass
else
    echo "Existing PKI found at $OPENVPN_DIR/pki - reusing it, not regenerating."
fi

echo "OpenVPN initialization completed successfully!"
echo "Configuration files created in $OPENVPN_DIR"

# Start OpenVPN
echo "Starting OpenVPN server..."
exec ovpn_run

#!/bin/bash
# OpenVPN Proper Initialization Script for BartoloVPN

set -e

OPENVPN_DIR="/etc/openvpn"
SERVER_IP="${SERVER_IP:-72.238.72.252}"

echo "Initializing OpenVPN configuration..."

# Create necessary directories
mkdir -p "$OPENVPN_DIR"
mkdir -p "$OPENVPN_DIR/pki"

# Generate OpenVPN configuration
echo "Generating OpenVPN configuration..."
ovpn_genconfig -u udp://$SERVER_IP:1194 -s 10.8.0.0/24

# Initialize PKI non-interactively
echo "Initializing PKI..."
export EASYRSA_BATCH=1
export EASYRSA_REQ_CN="BartoloVPN CA"
export EASYRSA_REQ_COUNTRY="US"
export EASYRSA_REQ_PROVINCE="CA"
export EASYRSA_REQ_CITY="San Francisco"
export EASYRSA_REQ_ORG="BartoloVPN"
export EASYRSA_REQ_EMAIL="admin@bartolovpn.com"
export EASYRSA_REQ_OU="BartoloVPN"

# Create CA certificate
echo "Creating CA certificate..."
ovpn_initpki nopass

echo "OpenVPN initialization completed successfully!"
echo "Configuration files created in $OPENVPN_DIR"

# Start OpenVPN
echo "Starting OpenVPN server..."
exec ovpn_run

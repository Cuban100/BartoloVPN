# 🔐 WireGuard Setup Guide

Complete guide for setting up and configuring WireGuard VPN in BartoloVPN.

## 📋 Table of Contents
- [Overview](#overview)
- [Server Setup](#server-setup)
- [Client Configuration](#client-configuration)
- [Client Setup Instructions](#client-setup-instructions)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

## 🌟 Overview

WireGuard is a modern, fast, and secure VPN protocol that provides:
- **Simplicity**: Minimal codebase and easy configuration
- **Performance**: Significantly faster than OpenVPN and IKEv2
- **Security**: State-of-the-art cryptography (ChaCha20, Curve25519)
- **Mobile-Friendly**: Low battery usage and seamless roaming
- **Cross-Platform**: Native support on all major platforms

### Protocol Details
- **Port**: 51821 (UDP) - configurable
- **Encryption**: ChaCha20Poly1305
- **Key Exchange**: Curve25519
- **Authentication**: Ed25519 digital signatures
- **Network**: 10.8.0.0/24 (default)

## 🚀 Server Setup

### 1. Docker Container Setup

The WireGuard server runs automatically when you start BartoloVPN:

```bash
cd BartoloVPN
docker-compose up -d wireguard
```

### 2. Server Configuration

The server configuration is located at `/config/wireguard/wg0.conf`:

```ini
[Interface]
# Server private key (auto-generated)
PrivateKey = SERVER_PRIVATE_KEY_HERE

# Server IP address
Address = 10.8.0.1/24

# Listen port
ListenPort = 51821

# Post-up and post-down scripts for routing
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o enxa0cec8b90d8d -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o enxa0cec8b90d8d -j MASQUERADE

# Example peer configuration
[Peer]
# Client public key
PublicKey = CLIENT_PUBLIC_KEY_HERE

# Allowed IPs for this peer
AllowedIPs = 10.8.0.2/32

# Optional: Endpoint (for clients behind NAT)
# Endpoint = client.domain.com:51821

# Optional: Persistent keepalive (for NAT traversal)
# PersistentKeepalive = 25
```

### 3. Key Generation

WireGuard uses public-key cryptography. Keys are automatically generated during setup:

```bash
# Server keys are automatically generated and stored in:
# /config/wireguard/server/privatekey-server
# /config/wireguard/server/publickey-server

# View server public key
docker exec bartolovpn_wireguard_1 cat /config/wireguard/server/publickey-server
```

### 4. Firewall Configuration

Ensure WireGuard port is open:
```bash
# Open WireGuard port
sudo ufw allow 51821/udp

# For cloud providers, configure security groups:
# - Inbound: UDP 51821
# - Outbound: All traffic
```

## 👥 Client Configuration

### 1. Generate Client Configuration

#### Web Interface Method:
1. Access BartoloVPN web interface: `http://your-server:5000`
2. Navigate to **WireGuard** tab
3. Click **"Add Peer"**
4. Enter peer name (e.g., "john-phone")
5. Click **"Generate"**
6. Download configuration file or scan QR code

#### Command Line Method:
```bash
# Enter the WireGuard container
docker exec -it bartolovpn_wireguard_1 bash

# Generate client private key
wg genkey > client_private.key

# Generate client public key
cat client_private.key | wg pubkey > client_public.key

# Create client config
cat > client.conf << EOF
[Interface]
PrivateKey = $(cat client_private.key)
Address = 10.8.0.2/32
DNS = 8.8.8.8, 8.8.4.4

[Peer]
PublicKey = $(cat /config/wireguard/server/publickey-server)
Endpoint = YOUR_SERVER_IP:51821
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
EOF
```

### 2. Client Configuration Template

```ini
[Interface]
# Client private key (keep this secret!)
PrivateKey = CLIENT_PRIVATE_KEY_HERE

# Client IP address
Address = 10.8.0.2/32

# DNS servers
DNS = 8.8.8.8, 8.8.4.4

# Optional: Custom MTU
# MTU = 1420

[Peer]
# Server public key
PublicKey = SERVER_PUBLIC_KEY_HERE

# Server endpoint (IP:PORT)
Endpoint = YOUR_SERVER_IP:51821

# Route all traffic through VPN (0.0.0.0/0)
# Or specific subnets: 10.8.0.0/24, 192.168.1.0/24
AllowedIPs = 0.0.0.0/0

# Keep connection alive through NAT
PersistentKeepalive = 25
```

## 📱 Client Setup Instructions

### Windows

1. **Install WireGuard**:
   - Download from: https://www.wireguard.com/install/
   - Install WireGuard for Windows

2. **Import Configuration**:
   - Open WireGuard application
   - Click "Add Tunnel" → "Add empty tunnel..." or "Import tunnel(s) from file"
   - Paste configuration or select `.conf` file
   - Click "Save"

3. **Connect**:
   - Select your tunnel in the list
   - Click "Activate" to connect

### macOS

1. **Install WireGuard**:
   - Download from Mac App Store or https://www.wireguard.com/install/
   - Install and open WireGuard

2. **Import Configuration**:
   - Click "+" to add tunnel
   - Choose "Add empty tunnel" or "Create from file"
   - Paste configuration or import `.conf` file
   - Click "Save"

3. **Connect**:
   - Toggle the switch to activate the tunnel

### Linux

1. **Install WireGuard**:
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install wireguard

   # CentOS/RHEL 8+
   sudo dnf install wireguard-tools

   # Arch Linux
   sudo pacman -S wireguard-tools
   ```

2. **Configure and Connect**:
   ```bash
   # Copy configuration file
   sudo cp client.conf /etc/wireguard/wg0.conf

   # Start WireGuard
   sudo wg-quick up wg0

   # Stop WireGuard
   sudo wg-quick down wg0

   # Enable at boot
   sudo systemctl enable wg-quick@wg0
   ```

3. **NetworkManager Integration**:
   ```bash
   # Install NetworkManager plugin
   sudo apt install network-manager-wireguard

   # Import via GUI: Settings → Network → VPN → Import from file
   ```

### Android

1. **Install WireGuard**:
   - Download from Google Play Store

2. **Import Configuration**:
   - **QR Code Method**:
     - Tap "+" → "Scan from QR code"
     - Scan QR code from web interface
   - **File Method**:
     - Transfer `.conf` file to device
     - Tap "+" → "Import from file"
     - Select configuration file

3. **Connect**:
   - Tap the toggle switch to connect

### iOS

1. **Install WireGuard**:
   - Download from App Store

2. **Import Configuration**:
   - **QR Code Method**:
     - Tap "+" → "Add a tunnel" → "Scan from QR code"
     - Scan QR code from web interface
   - **File Method**:
     - AirDrop or email `.conf` file to device
     - Tap "+" → "Add a tunnel" → "Create from file"

3. **Connect**:
   - Toggle the switch to activate

## 🔧 Troubleshooting

### Common Connection Issues

#### 1. Connection Timeout
```bash
# Check if server is running
docker ps | grep wireguard

# Check server logs
docker logs bartolovpn_wireguard_1

# Test UDP connectivity
nc -u your-server-ip 51821
```

#### 2. Cannot Access Internet
```bash
# Check server routing rules
docker exec bartolovpn_wireguard_1 iptables -t nat -L

# Verify IP forwarding is enabled
cat /proc/sys/net/ipv4/ip_forward

# Check DNS resolution
nslookup google.com
```

#### 3. Handshake Failures
```bash
# Check WireGuard status on server
docker exec bartolovpn_wireguard_1 wg show

# Verify peer public keys match
docker exec bartolovpn_wireguard_1 wg show wg0 peers

# Check allowed IPs
docker exec bartolovpn_wireguard_1 wg show wg0 allowed-ips
```

#### 4. Performance Issues
```bash
# Check MTU size
ip link show wg0

# Test with different MTU
# Add to client config: MTU = 1380

# Monitor bandwidth
docker exec bartolovpn_wireguard_1 iftop -i wg0
```

### Server Status Commands

```bash
# Show WireGuard interface status
docker exec bartolovpn_wireguard_1 wg show

# Show detailed peer information
docker exec bartolovpn_wireguard_1 wg show wg0

# Monitor real-time traffic
docker exec bartolovpn_wireguard_1 watch -n 1 'wg show wg0 transfer'

# Check interface statistics
docker exec bartolovpn_wireguard_1 ip -s link show wg0
```

### Network Diagnostics

```bash
# Test connectivity to peers
docker exec bartolovpn_wireguard_1 ping 10.8.0.2

# Check routing table
docker exec bartolovpn_wireguard_1 ip route show

# Monitor WireGuard logs
docker logs -f bartolovpn_wireguard_1
```

## ⚙️ Advanced Configuration

### Multiple Peers

```ini
# Add multiple peers to server config
[Peer]
PublicKey = CLIENT1_PUBLIC_KEY
AllowedIPs = 10.8.0.2/32

[Peer]
PublicKey = CLIENT2_PUBLIC_KEY
AllowedIPs = 10.8.0.3/32

[Peer]
PublicKey = CLIENT3_PUBLIC_KEY
AllowedIPs = 10.8.0.4/32
```

### Site-to-Site VPN

```ini
# Server A configuration
[Interface]
PrivateKey = SERVER_A_PRIVATE_KEY
Address = 10.8.0.1/24
ListenPort = 51821

[Peer]
PublicKey = SERVER_B_PUBLIC_KEY
Endpoint = server-b.domain.com:51821
AllowedIPs = 10.9.0.0/24

# Server B configuration
[Interface]
PrivateKey = SERVER_B_PRIVATE_KEY
Address = 10.9.0.1/24
ListenPort = 51821

[Peer]
PublicKey = SERVER_A_PUBLIC_KEY
Endpoint = server-a.domain.com:51821
AllowedIPs = 10.8.0.0/24
```

### Split Tunneling

```ini
# Client config for split tunneling
[Interface]
PrivateKey = CLIENT_PRIVATE_KEY
Address = 10.8.0.2/32

[Peer]
PublicKey = SERVER_PUBLIC_KEY
Endpoint = YOUR_SERVER_IP:51821
# Only route specific subnets through VPN
AllowedIPs = 192.168.1.0/24, 10.0.0.0/16
```

### Dynamic IP Assignment

```bash
# Use a script to automatically assign IPs
#!/bin/bash
NEXT_IP=$(docker exec bartolovpn_wireguard_1 wg show wg0 allowed-ips | \
  grep -o '10\.8\.0\.[0-9]*' | sort -V | tail -1 | cut -d. -f4)
NEW_IP=$((NEXT_IP + 1))
echo "10.8.0.$NEW_IP/32"
```

### Custom DNS Configuration

```ini
# Client config with custom DNS
[Interface]
PrivateKey = CLIENT_PRIVATE_KEY
Address = 10.8.0.2/32
# Use multiple DNS servers
DNS = 1.1.1.1, 8.8.8.8, 192.168.1.1
# Block ads with Pi-hole
# DNS = 10.8.0.1
```

### Port and Protocol Optimization

```ini
# Server config with custom port
[Interface]
PrivateKey = SERVER_PRIVATE_KEY
Address = 10.8.0.1/24
# Use custom port to avoid detection
ListenPort = 443

# Client endpoint update
Endpoint = YOUR_SERVER_IP:443
```

## 📊 Monitoring and Analytics

### Traffic Monitoring

```bash
# Monitor peer traffic
watch 'docker exec bartolovpn_wireguard_1 wg show wg0 transfer'

# Generate traffic report
docker exec bartolovpn_wireguard_1 wg show wg0 transfer | \
  awk '{print $1 " " $2 " received: " $3 " sent: " $4}'

# Real-time bandwidth monitoring
docker exec bartolovpn_wireguard_1 iftop -i wg0
```

### Connection Logging

```bash
# Enable logging in kernel
echo 'module wireguard +p' | sudo tee /sys/kernel/debug/dynamic_debug/control

# View kernel logs
sudo dmesg | grep wireguard

# Monitor connection establishment
journalctl -f | grep wireguard
```

### Performance Metrics

```bash
# Measure latency
docker exec bartolovpn_wireguard_1 ping -c 10 10.8.0.2

# Throughput testing with iperf3
# On server:
docker exec bartolovpn_wireguard_1 iperf3 -s

# On client:
iperf3 -c 10.8.0.1
```

## 🔐 Security Best Practices

### Key Management
- ✅ Generate unique keys for each client
- ✅ Store private keys securely
- ✅ Rotate keys regularly (annually)
- ✅ Revoke compromised keys immediately
- ✅ Use hardware security modules for server keys

### Network Security
- ✅ Use allowlisted IP ranges for AllowedIPs
- ✅ Implement firewall rules on server
- ✅ Monitor for unusual traffic patterns
- ✅ Enable logging for security audits
- ✅ Use VPN kill switches on clients

### Access Control
- ✅ Limit peer connections per server
- ✅ Implement bandwidth limits if needed
- ✅ Monitor active connections regularly
- ✅ Use different subnets for different user groups

## 📋 Performance Optimization

### Server Optimization
```bash
# Optimize network stack
echo 'net.core.default_qdisc = fq' >> /etc/sysctl.conf
echo 'net.ipv4.tcp_congestion_control = bbr' >> /etc/sysctl.conf
sysctl -p

# Increase UDP buffer sizes
echo 'net.core.rmem_max = 134217728' >> /etc/sysctl.conf
echo 'net.core.wmem_max = 134217728' >> /etc/sysctl.conf
```

### Client Optimization
```ini
# Optimize MTU for performance
[Interface]
MTU = 1420

# Reduce keep-alive for better battery life
[Peer]
PersistentKeepalive = 60
```

## 🆘 Support

For additional help:
- Check BartoloVPN web interface logs
- Review WireGuard documentation: https://www.wireguard.com/
- Submit issues: https://github.com/Cuban100/BartoloVPN/issues

---

**Developed by Erick Vladimir Salgado**  
**BartoloVPN - Multi-Protocol VPN Solution**

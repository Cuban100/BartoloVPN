# 🔐 OpenVPN Setup Guide

Complete guide for setting up and configuring OpenVPN in BartoloVPN.

## 📋 Table of Contents
- [Overview](#overview)
- [Server Setup](#server-setup)
- [Client Configuration](#client-configuration)
- [Client Setup Instructions](#client-setup-instructions)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

## 🌟 Overview

OpenVPN is a robust and highly configurable SSL/TLS VPN solution that provides:
- **Strong Security**: AES-256-GCM encryption
- **Wide Compatibility**: Works on all major platforms
- **Flexible Authentication**: Certificate-based authentication
- **NAT-friendly**: Works behind firewalls and NAT devices

### Protocol Details
- **Port**: 1194 (UDP) - configurable
- **Encryption**: AES-256-GCM
- **Authentication**: RSA-4096 certificates
- **Compression**: LZ4 compression
- **Network**: 10.8.0.0/24 (default)

## 🚀 Server Setup

### 1. Docker Container Setup

The OpenVPN server runs automatically when you start BartoloVPN:

```bash
cd BartoloVPN
docker-compose up -d openvpn
```

### 2. Server Configuration

The server configuration is located at `/config/openvpn/openvpn.conf`:

```
# OpenVPN Server Configuration
port 1194
proto udp
dev tun

# Certificates and keys
ca ca.crt
cert server.crt
key server.key
dh dh.pem

# Network configuration
server 10.8.0.0 255.255.255.0
ifconfig-pool-persist /tmp/ipp.txt

# Push routes to clients
push "redirect-gateway def1 bypass-dhcp"
push "dhcp-option DNS 8.8.8.8"
push "dhcp-option DNS 8.8.4.4"

# Security settings
cipher AES-256-GCM
auth SHA256
tls-version-min 1.2
tls-crypt ta.key

# Performance optimizations
compress lz4-v2
push "compress lz4-v2"

# Connection settings
keepalive 10 120
ping-timer-rem
persist-key
persist-tun

# Logging
status /tmp/openvpn-status.log
log-append /var/log/openvpn.log
verb 3
mute 20
```

### 3. Certificate Authority (CA) Setup

The PKI (Public Key Infrastructure) is automatically generated during first startup:

```bash
# CA Certificate: /config/openvpn/pki/ca.crt
# Server Certificate: /config/openvpn/pki/issued/server.crt
# Server Key: /config/openvpn/pki/private/server.key
# Diffie-Hellman: /config/openvpn/pki/dh.pem
# TLS-Crypt Key: /config/openvpn/pki/ta.key
```

## 👥 Client Configuration

### 1. Generate Client Certificate

Use the web interface or command line to generate client certificates:

#### Web Interface Method:
1. Access BartoloVPN web interface: `http://your-server:5000`
2. Navigate to **OpenVPN** tab
3. Click **"Add Client"**
4. Enter client name (e.g., "john-laptop")
5. Click **"Generate"**
6. Download the `.ovpn` file

#### Command Line Method:
```bash
# Enter the OpenVPN container
docker exec -it bartolovpn_openvpn_1 bash

# Generate client certificate
./easyrsa build-client-full client1 nopass

# Generate .ovpn file
./generate-client-config.sh client1
```

### 2. Client Configuration Template

```
# Client Configuration Template
client
dev tun
proto udp

# Server details
remote YOUR_SERVER_IP 1194
resolv-retry infinite
nobind

# Security
cipher AES-256-GCM
auth SHA256
tls-version-min 1.2

# Compression
compress lz4-v2

# Connection
persist-key
persist-tun
remote-cert-tls server
verb 3

# Embedded certificates and keys
<ca>
-----BEGIN CERTIFICATE-----
[CA Certificate Content]
-----END CERTIFICATE-----
</ca>

<cert>
-----BEGIN CERTIFICATE-----
[Client Certificate Content]
-----END CERTIFICATE-----
</cert>

<key>
-----BEGIN PRIVATE KEY-----
[Client Private Key Content]
-----END PRIVATE KEY-----
</key>

<tls-crypt>
-----BEGIN OpenVPN Static key V1-----
[TLS-Crypt Key Content]
-----END OpenVPN Static key V1-----
</tls-crypt>
```

## 📱 Client Setup Instructions

### Windows

1. **Download OpenVPN Client**:
   - Download from: https://openvpn.net/community-downloads/
   - Install OpenVPN Connect or OpenVPN GUI

2. **Import Configuration**:
   - Right-click OpenVPN GUI in system tray
   - Select "Import" → "Import file"
   - Choose your `.ovpn` file
   - Right-click → "Connect"

3. **Alternative - OpenVPN Connect**:
   - Install OpenVPN Connect from Microsoft Store
   - Open app → "+" → "File"
   - Select your `.ovpn` file
   - Toggle connection on

### macOS

1. **Install Tunnelblick**:
   - Download from: https://tunnelblick.net/
   - Install and restart

2. **Import Configuration**:
   - Double-click the `.ovpn` file
   - Tunnelblick will import automatically
   - Click "Connect" in Tunnelblick

3. **Alternative - OpenVPN Connect**:
   - Download from Mac App Store
   - Open app → "+" → "File"
   - Select your `.ovpn` file

### Linux (Ubuntu/Debian)

1. **Install OpenVPN**:
   ```bash
   sudo apt update
   sudo apt install openvpn
   ```

2. **Connect via Command Line**:
   ```bash
   sudo openvpn --config client.ovpn
   ```

3. **Connect via Network Manager**:
   ```bash
   sudo apt install network-manager-openvpn-gnome
   # Settings → Network → VPN → Import from file
   ```

### Android

1. **Install OpenVPN Connect**:
   - Download from Google Play Store

2. **Import Configuration**:
   - Transfer `.ovpn` file to device
   - Open OpenVPN Connect
   - Tap "+" → "File"
   - Select your `.ovpn` file
   - Tap the toggle to connect

### iOS

1. **Install OpenVPN Connect**:
   - Download from App Store

2. **Import Configuration**:
   - Email `.ovpn` file to yourself
   - Open email on iOS device
   - Tap `.ovpn` attachment
   - Choose "Copy to OpenVPN"
   - Tap "Add" then toggle to connect

## 🔧 Troubleshooting

### Common Connection Issues

#### 1. Connection Timeout
```bash
# Check if server is running
docker ps | grep openvpn

# Check server logs
docker logs bartolovpn_openvpn_1

# Check firewall rules
sudo ufw status
```

#### 2. DNS Resolution Issues
```bash
# Add to client config
dhcp-option DNS 8.8.8.8
dhcp-option DNS 1.1.1.1
```

#### 3. Authentication Failed
```bash
# Regenerate client certificate
docker exec -it bartolovpn_openvpn_1 ./easyrsa revoke client1
docker exec -it bartolovpn_openvpn_1 ./easyrsa build-client-full client1 nopass
```

#### 4. Cannot Access Internet
```bash
# Check NAT rules in container
docker exec -it bartolovpn_openvpn_1 iptables -t nat -L

# Verify IP forwarding
cat /proc/sys/net/ipv4/ip_forward
```

### Port and Firewall Configuration

```bash
# Open OpenVPN port on firewall
sudo ufw allow 1194/udp

# For cloud providers, ensure security groups allow:
# - Inbound: UDP 1194
# - Outbound: All traffic
```

### Server Status Commands

```bash
# Check OpenVPN status
docker exec bartolovpn_openvpn_1 cat /tmp/openvpn-status.log

# View active connections
docker exec bartolovpn_openvpn_1 tail -f /var/log/openvpn.log

# Test server connectivity
telnet your-server-ip 1194
```

## ⚙️ Advanced Configuration

### Custom Port Configuration

Edit `docker-compose.yml`:
```yaml
openvpn:
  ports:
    - "2194:1194/udp"  # Change external port
```

Update server config `/config/openvpn/openvpn.conf`:
```
port 1194  # Keep internal port same
```

### Multiple Client Certificates

```bash
# Generate multiple clients
docker exec -it bartolovpn_openvpn_1 ./easyrsa build-client-full laptop nopass
docker exec -it bartolovpn_openvpn_1 ./easyrsa build-client-full phone nopass
docker exec -it bartolovpn_openvpn_1 ./easyrsa build-client-full tablet nopass
```

### Certificate Revocation

```bash
# Revoke compromised certificate
docker exec -it bartolovpn_openvpn_1 ./easyrsa revoke client1

# Generate Certificate Revocation List (CRL)
docker exec -it bartolovpn_openvpn_1 ./easyrsa gen-crl

# Add to server config
crl-verify /etc/openvpn/pki/crl.pem
```

### Performance Tuning

Add to server config:
```
# Increase buffer sizes
sndbuf 0
rcvbuf 0

# Optimize for throughput
fast-io
tcp-nodelay

# Connection pooling
max-clients 100
```

### Security Hardening

```
# Require certificate verification
remote-cert-tls client

# Additional TLS security
tls-auth ta.key 0
key-direction 0

# Disable deprecated ciphers
ncp-disable
```

## 📋 Best Practices

### Security
- ✅ Use strong passwords for certificate generation
- ✅ Regularly rotate certificates (annually)
- ✅ Monitor connection logs for suspicious activity
- ✅ Use certificate revocation for compromised devices
- ✅ Keep OpenVPN server updated

### Performance
- ✅ Use UDP for better performance (default)
- ✅ Enable compression for slower connections
- ✅ Monitor bandwidth usage
- ✅ Limit concurrent connections based on server capacity

### Maintenance
- ✅ Regular backup of PKI directory
- ✅ Monitor server logs
- ✅ Test client configurations after server updates
- ✅ Document issued certificates

## 🆘 Support

For additional help:
- Check BartoloVPN web interface logs
- Review OpenVPN official documentation: https://openvpn.net/community-resources/
- Submit issues: https://github.com/Cuban100/BartoloVPN/issues

---

**Developed by Erick Vladimir Salgado**  
**BartoloVPN - Multi-Protocol VPN Solution**

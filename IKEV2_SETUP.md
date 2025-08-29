# 🔐 IKEv2 Setup Guide

Complete guide for setting up and configuring IKEv2/IPSec VPN in BartoloVPN using strongSwan.

## 📋 Table of Contents
- [Overview](#overview)
- [Server Setup](#server-setup)
- [Client Configuration](#client-configuration)
- [Client Setup Instructions](#client-setup-instructions)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

## 🌟 Overview

IKEv2 (Internet Key Exchange version 2) with IPSec provides:
- **Enterprise-Grade Security**: Military-grade encryption
- **Mobile Optimization**: Excellent for mobile devices with MOBIKE
- **Fast Connection**: Quick connection establishment and reconnection
- **Built-in Support**: Native support on most modern devices
- **Network Resilience**: Handles network changes seamlessly

### Protocol Details
- **Port**: UDP 500 (IKE), UDP 4500 (IPSec NAT-T)
- **Encryption**: AES-256-GCM
- **Authentication**: EAP-MSCHAPv2 with certificates
- **Network**: 10.10.0.0/24 (default)
- **Implementation**: strongSwan

## 🚀 Server Setup

### 1. Docker Container Setup

The IKEv2 server runs automatically when you start BartoloVPN:

```bash
cd BartoloVPN
docker-compose up -d ikev2
```

### 2. Server Configuration

The server configuration is managed by strongSwan at `/config/ikev2/`:

#### `/config/ikev2/ipsec.conf`
```
# IKEv2 Configuration
config setup
    charondebug="ike 1, knl 1, cfg 0"
    uniqueids=no

conn ikev2-vpn
    auto=add
    compress=no
    type=tunnel
    keyexchange=ikev2
    fragmentation=yes
    forceencaps=yes
    
    # Server configuration
    left=%any
    leftid=@vpn.bartolo.local
    leftcert=server-cert.pem
    leftsendcert=always
    leftsubnet=0.0.0.0/0
    
    # Client configuration
    right=%any
    rightid=%any
    rightsourceip=10.10.0.0/24
    rightdns=8.8.8.8,8.8.4.4
    rightsendcert=never
    
    # Security settings
    ike=chacha20poly1305-sha256-curve25519-prfsha256,aes256gcm16-sha384-prfsha384-ecp384,aes256-sha1-modp1024,aes128-sha1-modp1024,3des-sha1-modp1024!
    esp=chacha20poly1305-sha256,aes256gcm16-ecp384,aes256-sha256,aes256-sha1,3des-sha1!
    
    # Authentication
    eap_identity=%identity
    reauth=no
```

#### `/config/ikev2/ipsec.secrets`
```
# RSA private key for server authentication
: RSA "server-key.pem"

# EAP credentials for clients
username1 : EAP "password1"
username2 : EAP "password2"
```

### 3. Certificate Authority (CA) Setup

The PKI is automatically generated during first startup:

```bash
# CA Certificate: /config/ikev2/ca-cert.pem
# Server Certificate: /config/ikev2/server-cert.pem
# Server Key: /config/ikev2/server-key.pem
# Client Certificate: /config/ikev2/client-cert.pem (optional)
```

### 4. Firewall Configuration

Ensure the following ports are open:
```bash
# IKE negotiation
sudo ufw allow 500/udp

# IPSec NAT traversal
sudo ufw allow 4500/udp

# For cloud providers, configure security groups:
# - Inbound: UDP 500, UDP 4500
# - Outbound: All traffic
```

## 👥 Client Configuration

### 1. Create User Credentials

#### Web Interface Method:
1. Access BartoloVPN web interface: `http://your-server:5000`
2. Navigate to **IKEv2** tab
3. Click **"Add User"**
4. Enter username and password
5. Click **"Create"**
6. Download client configuration or certificates

#### Command Line Method:
```bash
# Enter the IKEv2 container
docker exec -it bartolovpn_ikev2_1 bash

# Add user to ipsec.secrets
echo "newuser : EAP \"userpassword\"" >> /etc/ipsec.secrets

# Restart strongSwan
ipsec restart
```

### 2. Client Configuration Details

For manual configuration, you'll need:
- **Server Address**: Your server's public IP or domain
- **VPN Type**: IKEv2
- **Authentication**: Username/Password (EAP-MSCHAPv2)
- **Username**: Created in previous step
- **Password**: Created in previous step
- **CA Certificate**: `/config/ikev2/ca-cert.pem` (optional but recommended)

## 📱 Client Setup Instructions

### Windows 10/11

1. **Open VPN Settings**:
   - Settings → Network & Internet → VPN
   - Click "Add a VPN connection"

2. **Configure Connection**:
   - **VPN provider**: Windows (built-in)
   - **Connection name**: BartoloVPN IKEv2
   - **Server name or address**: `your-server-ip`
   - **VPN type**: IKEv2
   - **Type of sign-in info**: User name and password
   - **Username**: Your created username
   - **Password**: Your created password

3. **Advanced Settings** (Optional):
   - Click "Advanced options"
   - Import CA certificate if using certificate authentication

4. **Connect**:
   - Click "Connect" to establish VPN connection

### macOS

1. **Open Network Settings**:
   - System Preferences → Network
   - Click "+" to add new connection

2. **Configure VPN**:
   - **Interface**: VPN
   - **VPN Type**: IKEv2
   - **Service Name**: BartoloVPN IKEv2

3. **Authentication Settings**:
   - **Server Address**: `your-server-ip`
   - **Remote ID**: `your-server-ip`
   - **Local ID**: Leave blank
   - **Authentication Settings**: Username
     - **Username**: Your created username
     - **Password**: Your created password

4. **Connect**:
   - Click "Apply" then "Connect"

### Linux (NetworkManager)

1. **Install strongSwan Plugin**:
   ```bash
   # Ubuntu/Debian
   sudo apt install network-manager-strongswan

   # CentOS/RHEL
   sudo yum install NetworkManager-strongswan-gnome
   ```

2. **Configure via GUI**:
   - Settings → Network → VPN → "+"
   - Select "IPsec/IKEv2 (strongswan)"
   - **Gateway**: `your-server-ip`
   - **Username**: Your created username
   - **Password**: Your created password
   - **Certificate**: Import CA certificate (optional)

3. **Command Line Configuration**:
   ```bash
   # Create connection
   nmcli connection add type vpn con-name "BartoloVPN" \
     ifname -- vpn.service-type org.freedesktop.NetworkManager.strongswan \
     vpn.data 'address=your-server-ip, encap=yes, ipcomp=no, method=eap, user=username'
   
   # Connect
   nmcli connection up "BartoloVPN"
   ```

### Android

1. **Built-in VPN Client**:
   - Settings → Network & Internet → VPN
   - Tap "+" to add VPN

2. **Configure IKEv2**:
   - **Name**: BartoloVPN
   - **Type**: IKEv2/IPSec PSK or IKEv2/IPSec RSA
   - **Server address**: `your-server-ip`
   - **Username**: Your created username
   - **Password**: Your created password

3. **Alternative - strongSwan App**:
   - Install strongSwan VPN Client from Google Play
   - Tap "Add VPN Profile"
   - **Gateway**: `your-server-ip`
   - **Type**: IKEv2 EAP (Username/Password)
   - **Username/Password**: Your credentials

### iOS

1. **Built-in VPN Client**:
   - Settings → General → VPN
   - Tap "Add VPN Configuration"

2. **Configure IKEv2**:
   - **Type**: IKEv2
   - **Description**: BartoloVPN
   - **Server**: `your-server-ip`
   - **Remote ID**: `your-server-ip`
   - **Local ID**: Leave blank
   - **User Authentication**: Username
   - **Username**: Your created username
   - **Password**: Your created password

3. **Connect**:
   - Toggle VPN connection on

## 🔧 Troubleshooting

### Common Connection Issues

#### 1. Authentication Failed
```bash
# Check user credentials
docker exec bartolovpn_ikev2_1 cat /etc/ipsec.secrets

# View authentication logs
docker logs bartolovpn_ikev2_1

# Test authentication
docker exec bartolovpn_ikev2_1 ipsec statusall
```

#### 2. Connection Timeout
```bash
# Check if ports are open
sudo nmap -sU -p 500,4500 your-server-ip

# Check firewall rules
sudo ufw status

# Verify container is running
docker ps | grep ikev2
```

#### 3. Traffic Not Routing
```bash
# Check IP forwarding
cat /proc/sys/net/ipv4/ip_forward

# Check NAT rules
docker exec bartolovpn_ikev2_1 iptables -t nat -L

# Test connectivity
docker exec bartolovpn_ikev2_1 ping 8.8.8.8
```

#### 4. Certificate Issues
```bash
# Regenerate certificates
docker exec bartolovpn_ikev2_1 /usr/local/bin/generate-certs.sh

# Check certificate validity
docker exec bartolovpn_ikev2_1 openssl x509 -in /etc/ipsec.d/certs/server-cert.pem -text -noout
```

### Server Status Commands

```bash
# Check strongSwan status
docker exec bartolovpn_ikev2_1 ipsec status

# View active connections
docker exec bartolovpn_ikev2_1 ipsec statusall

# Monitor real-time logs
docker logs -f bartolovpn_ikev2_1

# Check configuration
docker exec bartolovpn_ikev2_1 ipsec listcerts
docker exec bartolovpn_ikev2_1 ipsec listall
```

### Debug Mode

Enable debug logging:
```bash
# Edit ipsec.conf
docker exec bartolovpn_ikev2_1 nano /etc/ipsec.conf

# Add debug options
config setup
    charondebug="ike 2, knl 2, cfg 2, net 2, asn 2, enc 2"

# Restart strongSwan
docker exec bartolovpn_ikev2_1 ipsec restart
```

## ⚙️ Advanced Configuration

### Multiple Authentication Methods

#### PSK (Pre-Shared Key) Authentication
Add to `ipsec.secrets`:
```
your-server-ip %any : PSK "your-very-strong-psk"
```

Update `ipsec.conf`:
```
conn ikev2-psk
    authby=secret
    # ... other settings
```

#### Certificate-based Authentication
```bash
# Generate client certificate
docker exec bartolovpn_ikev2_1 ipsec pki --gen --type rsa --size 4096 \
  --outform pem > /config/ikev2/client-key.pem

docker exec bartolovpn_ikev2_1 ipsec pki --pub --in /config/ikev2/client-key.pem \
  --type rsa | ipsec pki --issue --lifetime 3650 \
  --cacert /config/ikev2/ca-cert.pem \
  --cakey /config/ikev2/ca-key.pem \
  --dn "CN=client" --san "client" \
  --outform pem > /config/ikev2/client-cert.pem
```

### High Availability Setup

#### Load Balancing
```yaml
# docker-compose.yml
ikev2-1:
  image: bartolovpn/ikev2
  ports:
    - "500:500/udp"
    - "4500:4500/udp"

ikev2-2:
  image: bartolovpn/ikev2
  ports:
    - "501:500/udp"
    - "4501:4500/udp"
```

#### Shared Configuration
```bash
# Use shared volume for certificates
volumes:
  - ./config/ikev2:/etc/ipsec.d/
```

### Performance Tuning

#### Optimize for Mobile Devices
```
conn ikev2-mobile
    # Enable MOBIKE for roaming
    mobike=yes
    
    # Optimize for mobile networks
    keyingtries=%forever
    dpdaction=restart
    dpddelay=300s
    dpdtimeout=30s
    
    # Compression for slow connections
    compress=yes
```

#### Bandwidth Optimization
```
# Limit bandwidth per client
rightsubnet=10.10.0.0/24[tcp:80-443,udp:53]

# QoS settings
mark=42
mark_in=42
mark_out=42
```

### Security Hardening

#### Strong Cipher Suites
```
ike=aes256gcm16-sha384-prfsha384-ecp384!
esp=aes256gcm16-ecp384!
```

#### Certificate Pinning
```
# Pin server certificate
rightca=%same
```

#### Access Control
```bash
# Restrict by IP range
docker exec bartolovpn_ikev2_1 iptables -A INPUT -s 192.168.1.0/24 -p udp --dport 500 -j ACCEPT
docker exec bartolovpn_ikev2_1 iptables -A INPUT -p udp --dport 500 -j DROP
```

## 📊 Monitoring and Analytics

### Connection Monitoring
```bash
# Real-time connection status
watch 'docker exec bartolovpn_ikev2_1 ipsec status'

# Connection statistics
docker exec bartolovpn_ikev2_1 ipsec statusall | grep ESTABLISHED

# Bandwidth monitoring
docker exec bartolovpn_ikev2_1 iftop -i any
```

### Log Analysis
```bash
# Parse connection logs
docker logs bartolovpn_ikev2_1 2>&1 | grep "connection established"

# Failed authentication attempts
docker logs bartolovpn_ikev2_1 2>&1 | grep "authentication failed"

# Export logs for analysis
docker logs bartolovpn_ikev2_1 > ikev2-$(date +%Y%m%d).log
```

## 📋 Best Practices

### Security
- ✅ Use strong passwords (minimum 12 characters)
- ✅ Regularly rotate credentials (quarterly)
- ✅ Monitor authentication logs for brute force attempts
- ✅ Use certificate authentication for high-security environments
- ✅ Keep strongSwan updated

### Performance
- ✅ Use modern cipher suites (ChaCha20, AES-GCM)
- ✅ Enable MOBIKE for mobile devices
- ✅ Monitor bandwidth usage per client
- ✅ Optimize MTU size for networks

### Maintenance
- ✅ Regular backup of configuration and certificates
- ✅ Test client connections after server updates
- ✅ Monitor server resource usage
- ✅ Document user accounts and access levels

## 🆘 Support

For additional help:
- Check BartoloVPN web interface logs
- Review strongSwan documentation: https://docs.strongswan.org/
- Submit issues: https://github.com/Cuban100/BartoloVPN/issues

---

**Developed by Erick Vladimir Salgado**  
**BartoloVPN - Multi-Protocol VPN Solution**

# 🌐 Cloudflare Tunnel Setup for BartoloVPN

Secure your VPN management interface using Cloudflare Tunnel instead of traditional port forwarding.

## 🎯 Why Cloudflare Tunnel?

- **🔒 Zero Trust Security**: No open ports on your firewall
- **🌍 Global CDN**: Fast access from anywhere
- **🛡️ DDoS Protection**: Built-in protection
- **🔐 SSL/TLS**: Automatic HTTPS certificates
- **👥 Access Control**: User authentication and policies
- **📊 Analytics**: Traffic monitoring and insights

## 🚀 Quick Setup

### 1. Install Cloudflare Tunnel
```bash
# Download and install cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb

# Verify installation
cloudflared --version
```

### 2. Authenticate with Cloudflare
```bash
# Login to your Cloudflare account
cloudflared tunnel login

# This will open a browser window to authenticate
# Select your domain (caveplex.com)
```

### 3. Create Tunnel
```bash
# Create a new tunnel
cloudflared tunnel create bartolo-vpn

# List tunnels
cloudflared tunnel list
```

### 4. Configure Tunnel
```bash
# Create tunnel configuration
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: YOUR_TUNNEL_ID
credentials-file: ~/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  # VPN Management Interface (FastAPI)
  - hostname: vpn.caveplex.com
    service: http://192.168.0.2:5000
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
      readTimeout: 30s
  
  # Web UI (if separate)
  - hostname: vpn-ui.caveplex.com
    service: http://192.168.0.2:8080
    originRequest:
      noTLSVerify: true
  
  # HAProxy Stats (optional)
  - hostname: vpn-stats.caveplex.com
    service: http://192.168.0.2:8404
    originRequest:
      noTLSVerify: true
  
  # Catch-all rule (must be last)
  - service: http_status:404
EOF
```

### 5. Create DNS Records
```bash
# Create DNS records for your tunnel
cloudflared tunnel route dns bartolo-vpn vpn.caveplex.com
cloudflared tunnel route dns bartolo-vpn vpn-ui.caveplex.com
cloudflared tunnel route dns bartolo-vpn vpn-stats.caveplex.com
```

### 6. Start Tunnel
```bash
# Test the tunnel
cloudflared tunnel --config ~/.cloudflared/config.yml run bartolo-vpn

# Run in background
nohup cloudflared tunnel --config ~/.cloudflared/config.yml run bartolo-vpn > /var/log/cloudflared.log 2>&1 &
```

## 🔧 Docker Integration

### 1. Create Cloudflare Tunnel Service
```yaml
# Add to docker-compose.yml
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: bartolo-cloudflared
    restart: unless-stopped
    command: tunnel --config /etc/cloudflared/config.yml run bartolo-vpn
    volumes:
      - ~/.cloudflared:/etc/cloudflared:ro
    networks:
      vpn-network:
        ipv4_address: 172.20.0.20
    depends_on:
      - vpn-api
      - web-ui
      - haproxy
```

### 2. Updated Docker Compose
```yaml
version: '3.8'

services:
  # ... existing services ...
  
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

networks:
  vpn-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
          gateway: 172.20.0.1
  vpn-external:
    driver: bridge
    ipam:
      config:
        - subnet: 10.13.13.0/24
          gateway: 10.13.13.1
```

## 🔐 Security Configuration

### 1. Access Policies
```bash
# Create access application in Cloudflare Dashboard
# Go to: Zero Trust > Access > Applications > Add an application

# Application settings:
# - Application name: BartoloVPN
# - Session duration: 24 hours
# - Domain: vpn.caveplex.com
# - App type: Self-hosted
```

### 2. Authentication Methods
```bash
# Configure authentication in Cloudflare Dashboard:
# - One-time PIN
# - Service tokens
# - Identity providers (Google, GitHub, etc.)
# - SAML/SSO
```

### 3. Device Posture
```bash
# Enable device posture checks:
# - Operating system requirements
# - Security software requirements
# - Network location requirements
```

## 📱 Client Access

### 1. WARP Client (Recommended)
```bash
# Users install Cloudflare WARP client
# Configure with your organization's settings
# Automatic authentication and access
```

### 2. Browser Access
```bash
# Users access via browser
# Authenticate through Cloudflare Access
# No VPN client needed for management
```

### 3. API Access
```bash
# For programmatic access
# Use service tokens
# Include in API requests
```

## 🔄 VPN Client Distribution

### 1. Secure Download Links
```bash
# Create secure download pages
# - WireGuard configs
# - OpenVPN configs
# - IKEv2 configs
# - QR codes for mobile
```

### 2. Access Control
```bash
# Require authentication for downloads
# Track who downloads what
# Set expiration on configs
```

## 🛠️ Advanced Configuration

### 1. Load Balancing
```bash
# Multiple tunnel endpoints
# Geographic distribution
# Health checks and failover
```

### 2. Analytics and Logging
```bash
# Monitor tunnel traffic
# Track user access patterns
# Security event logging
```

### 3. Custom Headers
```bash
# Add security headers
# Geographic information
# User context
```

## 🚨 Security Best Practices

### 1. Network Isolation
```bash
# Keep VPN services on internal network
# Only expose management interface
# Use Cloudflare for all external access
```

### 2. Authentication
```bash
# Multi-factor authentication
# Device trust requirements
# Session management
```

### 3. Monitoring
```bash
# Monitor tunnel health
# Track access patterns
# Alert on suspicious activity
```

## 🔧 Troubleshooting

### 1. Tunnel Issues
```bash
# Check tunnel status
cloudflared tunnel info bartolo-vpn

# View tunnel logs
cloudflared tunnel logs bartolo-vpn

# Test connectivity
cloudflared tunnel --config ~/.cloudflared/config.yml run bartolo-vpn
```

### 2. DNS Issues
```bash
# Verify DNS records
dig vpn.caveplex.com
nslookup vpn.caveplex.com

# Check tunnel routes
cloudflared tunnel route ip show
```

### 3. Access Issues
```bash
# Check access policies
# Verify user permissions
# Test authentication flow
```

## 📊 Benefits Summary

✅ **No open ports** on your firewall  
✅ **Automatic SSL/TLS** certificates  
✅ **Global CDN** for fast access  
✅ **DDoS protection** included  
✅ **User authentication** and access control  
✅ **Analytics** and monitoring  
✅ **Zero Trust** security model  
✅ **Easy management** through Cloudflare dashboard  

## 🎯 Next Steps

1. **Install cloudflared** on your server
2. **Authenticate** with your Cloudflare account
3. **Create tunnel** and configure DNS
4. **Update docker-compose.yml** with cloudflared service
5. **Configure access policies** in Cloudflare dashboard
6. **Test access** from external networks
7. **Set up monitoring** and alerts

This approach gives you enterprise-grade security with minimal configuration! 🌐🔒

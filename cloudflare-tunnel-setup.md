# 🌐 Cloudflare Tunnel Setup for BartoloVPN

> ⚠️ **Optional and not configured by default.** BartoloVPN does not set this up
> for you - `docker-compose.yml` has no `cloudflared` service, and nothing here
> runs unless you deploy it yourself via `scripts/setup-cloudflare-tunnel.sh` or
> by hand. If you're already exposing this box through an *existing* Cloudflare
> Tunnel you manage separately (e.g. one shared across other services on the
> same host, configured through the Cloudflare Zero Trust dashboard), you likely
> don't need this guide at all - just add an ingress rule there pointing at
> this server's `LOCAL_IP:API_PORT` (default `5000`) or at HAProxy's port 80.
>
> **If a `cloudflared` systemd service is already running on this host** (check
> with `systemctl status cloudflared`), do *not* run this script's `service`
> step - it would overwrite that unit and break whatever tunnel it's already
> managing. `setup-cloudflare-tunnel.sh` now refuses to do this automatically,
> but add your ingress rule to the existing tunnel's config by hand instead.

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
# Select your domain from the list
```

### 3. Create Tunnel
```bash
# Create a new tunnel
cloudflared tunnel create bartolo-vpn

# List tunnels
cloudflared tunnel list
```

### 4. Configure Tunnel

There's no separate "web UI" service - the dashboard and the API are the same
FastAPI app (`vpn-api`, port 5000 by default, `API_PORT` in `.env`), so there's
only one real ingress target for it. HAProxy's stats page (port 8404) is
optional to expose.

```bash
# Create tunnel configuration
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: YOUR_TUNNEL_ID
credentials-file: ~/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  # BartoloVPN dashboard + API (same FastAPI app, vpn-api)
  - hostname: vpn.yourdomain.com
    service: http://192.168.1.100:5000
    originRequest:
      noTLSVerify: true
      connectTimeout: 30s
      readTimeout: 30s

  # HAProxy Stats (optional)
  - hostname: vpn-stats.yourdomain.com
    service: http://192.168.1.100:8404
    originRequest:
      noTLSVerify: true
  
  # Catch-all rule (must be last)
  - service: http_status:404
EOF
```

### 5. Create DNS Records
```bash
# Create DNS records for your tunnel
cloudflared tunnel route dns bartolo-vpn vpn.yourdomain.com
cloudflared tunnel route dns bartolo-vpn vpn-stats.yourdomain.com
```

### 6. Start Tunnel
```bash
# Test the tunnel
cloudflared tunnel --config ~/.cloudflared/config.yml run bartolo-vpn

# Run in background
nohup cloudflared tunnel --config ~/.cloudflared/config.yml run bartolo-vpn > /var/log/cloudflared.log 2>&1 &
```

## 🔧 Docker Integration

Add this service directly to the repo's existing `docker-compose.yml` (there's
no separate "updated" compose file to copy - just append this block). It
doesn't need to join `vpn-network` or `vpn-external` - `vpn-api` isn't on
either of those (it shares the `wireguard` container's network namespace), and
the ingress config above already reaches services via the host's `LOCAL_IP`,
not container-name DNS. `web-ui` isn't a real service - it's the same `vpn-api`
container as above, already listed in `depends_on`.

```yaml
# Append to docker-compose.yml's services: section
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: ${COMPOSE_PROJECT_NAME}-cloudflared
    restart: unless-stopped
    command: tunnel --config /etc/cloudflared/config.yml run bartolo-vpn
    volumes:
      - ./config/cloudflared:/etc/cloudflared:ro
    depends_on:
      - wireguard
      - haproxy
```

## 🔐 Security Configuration

### 1. Access Policies
```bash
# Create access application in Cloudflare Dashboard
# Go to: Zero Trust > Access > Applications > Add an application

# Application settings:
# - Application name: BartoloVPN
# - Session duration: 24 hours
# - Domain: vpn.yourdomain.com
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
dig vpn.yourdomain.com
nslookup vpn.yourdomain.com

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

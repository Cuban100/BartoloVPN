# 🌍 Geo-Spoofing Guide for BartoloVPN

Make your VPN appear as if it's located in Sweden (or any country) using advanced techniques.

## 🎯 What is Geo-Spoofing?

Geo-spoofing makes your VPN traffic appear to originate from a specific country by:
- **DNS Configuration**: Using local DNS servers
- **Timezone Settings**: Setting server timezone to target country
- **Locale Configuration**: Using local language settings
- **IP Headers**: Adding geographic headers to traffic
- **DNS Leak Prevention**: Ensuring all DNS queries go through local servers

## 🇸🇪 Swedish VPN Setup

### Quick Setup
```bash
# Setup Swedish environment
./scripts/geo-spoofing.sh setup

# Create Swedish client config for a friend
./scripts/geo-spoofing.sh client friend1

# Start Swedish VPN services
./scripts/geo-spoofing.sh start

# Check status
./scripts/geo-spoofing.sh status
```

### What the Script Does

1. **🌐 Swedish DNS Servers**
   - Primary: `130.242.4.8` (Swedish University Network)
   - Secondary: `130.242.4.9` (Swedish University Network)
   - Backup: `8.8.8.8`, `1.1.1.1`

2. **⏰ Swedish Timezone**
   - Timezone: `Europe/Stockholm`
   - Locale: `sv_SE.UTF-8`

3. **🏷️ Swedish Headers**
   - `X-Country: SE`
   - `X-Region: Europe`
   - `X-City: Stockholm`

## 🔧 Manual Configuration

### 1. Update Environment Variables
```bash
# Edit .env file
nano .env

# Add these lines:
DNS_SERVERS=130.242.4.8,130.242.4.9,8.8.8.8,1.1.1.1
WIREGUARD_DNS=130.242.4.8,130.242.4.9,8.8.8.8,1.1.1.1
TIMEZONE=Europe/Stockholm
LOCALE=sv_SE.UTF-8
```

### 2. Configure WireGuard for Sweden
```bash
# Create Swedish WireGuard config
cat > config/wireguard/swedish_wg0.conf << 'EOF'
[Interface]
PrivateKey = YOUR_PRIVATE_KEY
Address = 10.13.13.1/24
ListenPort = 51820

# Swedish DNS servers
PostUp = echo "nameserver 130.242.4.8" > /etc/resolv.conf
PostUp = echo "nameserver 130.242.4.9" >> /etc/resolv.conf
PostUp = echo "nameserver 8.8.8.8" >> /etc/resolv.conf

# Swedish timezone
PostUp = ln -sf /usr/share/zoneinfo/Europe/Stockholm /etc/localtime
PostUp = echo "Europe/Stockholm" > /etc/timezone

# Swedish locale
PostUp = echo "LANG=sv_SE.UTF-8" >> /etc/environment
PostUp = echo "LC_ALL=sv_SE.UTF-8" >> /etc/environment

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
EOF
```

### 3. Create Swedish Client Configuration
```bash
# Generate Swedish client config
cat > config/wireguard/peers/friend_sweden.conf << 'EOF'
[Interface]
PrivateKey = CLIENT_PRIVATE_KEY
Address = 10.13.13.100/24
DNS = 130.242.4.8, 130.242.4.9, 8.8.8.8, 1.1.1.1

[Peer]
PublicKey = SERVER_PUBLIC_KEY
Endpoint = your-server-ip:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25

# Swedish configuration
# This client will appear to be connecting from Sweden
EOF
```

## 🌍 Other Countries

### 🇺🇸 United States
```bash
# US DNS servers
DNS_SERVERS=8.8.8.8,8.8.4.4,1.1.1.1,1.0.0.1
TIMEZONE=America/New_York
LOCALE=en_US.UTF-8
```

### 🇬🇧 United Kingdom
```bash
# UK DNS servers
DNS_SERVERS=8.8.8.8,1.1.1.1,208.67.222.222,208.67.220.220
TIMEZONE=Europe/London
LOCALE=en_GB.UTF-8
```

### 🇩🇪 Germany
```bash
# German DNS servers
DNS_SERVERS=8.8.8.8,1.1.1.1,217.172.224.47,217.172.224.48
TIMEZONE=Europe/Berlin
LOCALE=de_DE.UTF-8
```

### 🇯🇵 Japan
```bash
# Japanese DNS servers
DNS_SERVERS=8.8.8.8,1.1.1.1,202.12.27.33,202.12.27.34
TIMEZONE=Asia/Tokyo
LOCALE=ja_JP.UTF-8
```

## 🔍 Verification Methods

### 1. DNS Leak Test
```bash
# Test DNS servers
nslookup google.com 130.242.4.8
nslookup google.com 130.242.4.9

# Check if DNS queries go through Swedish servers
dig +short whoami.akamai.net @130.242.4.8
```

### 2. Timezone Verification
```bash
# Check server timezone
docker exec bartolo-wireguard date
docker exec bartolo-wireguard cat /etc/timezone
```

### 3. IP Geolocation Test
```bash
# Test from client
curl -s https://ipapi.co/json/ | jq '.country, .city, .timezone'
curl -s https://ipinfo.io/json | jq '.country, .city, .timezone'
```

### 4. WebRTC Leak Test
```bash
# Check WebRTC leaks
curl -s https://browserleaks.com/webrtc | grep -i "ip\|country"
```

## 🛡️ Advanced Techniques

### 1. Multiple Country Rotation
```bash
# Create rotation script
cat > scripts/country-rotation.sh << 'EOF'
#!/bin/bash
COUNTRIES=("sweden" "germany" "uk" "japan" "us")
CURRENT_COUNTRY=${COUNTRIES[$RANDOM % ${#COUNTRIES[@]}]}

echo "Rotating to: $CURRENT_COUNTRY"
./scripts/geo-spoofing.sh setup_$CURRENT_COUNTRY
EOF

chmod +x scripts/country-rotation.sh
```

### 2. DNS Over HTTPS (DoH)
```bash
# Configure DoH for better privacy
cat > config/dns/doh.conf << 'EOF'
# DNS Over HTTPS configuration
server {
    listen 53;
    forward 130.242.4.8:443 tls://dns.switch.ch
    forward 130.242.4.9:443 tls://dns.switch.ch
}
EOF
```

### 3. Custom Headers
```bash
# Add custom geographic headers
cat > config/nginx/swedish-headers.conf << 'EOF'
# Swedish geographic headers
add_header X-Country "SE";
add_header X-Region "Europe";
add_header X-City "Stockholm";
add_header X-Timezone "Europe/Stockholm";
add_header X-Locale "sv_SE.UTF-8";
EOF
```

## 🚨 Important Notes

### ⚠️ Legal Considerations
- **Check local laws** regarding VPN usage
- **Respect terms of service** of websites you access
- **Don't use for illegal activities**

### 🔒 Security Best Practices
- **Regular updates** of DNS server lists
- **Monitor for DNS leaks** regularly
- **Use HTTPS** for all web traffic
- **Enable kill switch** to prevent leaks

### 📊 Monitoring
```bash
# Monitor DNS queries
docker exec bartolo-wireguard tcpdump -i any port 53

# Check geographic headers
curl -I https://your-server-ip:8080

# Monitor timezone consistency
docker exec bartolo-wireguard date
```

## 🎯 Testing Your Setup

### 1. DNS Leak Test
Visit: https://www.dnsleaktest.com
- Should show Swedish DNS servers
- No leaks to your real location

### 2. IP Geolocation Test
Visit: https://ipinfo.io
- Should show Sweden as country
- Stockholm as city
- Swedish timezone

### 3. WebRTC Leak Test
Visit: https://browserleaks.com/webrtc
- Should not reveal your real IP
- Should show Swedish location

### 4. Speed Test
Visit: https://www.speedtest.net
- Test connection speed
- Verify no significant slowdown

## 🔄 Automation

### Cron Job for Regular Rotation
```bash
# Add to crontab
crontab -e

# Rotate country every 6 hours
0 */6 * * * /path/to/bartolovpn/scripts/country-rotation.sh

# Check for DNS leaks daily
0 2 * * * /path/to/bartolovpn/scripts/dns-leak-check.sh
```

### Docker Compose with Country Rotation
```yaml
# docker-compose.country.yml
version: '3.8'
services:
  wireguard:
    environment:
      - COUNTRY=sweden
      - DNS_SERVERS=130.242.4.8,130.242.4.9
      - TIMEZONE=Europe/Stockholm
    labels:
      - "country=sweden"
      - "region=europe"
```

## 🎉 Success Indicators

✅ **DNS queries** go through Swedish servers  
✅ **Timezone** shows Europe/Stockholm  
✅ **IP geolocation** shows Sweden  
✅ **No DNS leaks** detected  
✅ **WebRTC** doesn't reveal real IP  
✅ **Connection speed** remains good  

---

**Remember**: Geo-spoofing is for privacy and access, not for circumventing legitimate restrictions. Always respect local laws and terms of service! 🌍

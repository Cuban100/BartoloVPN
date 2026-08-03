# 🔐 Local TLS Setup for BartoloVPN (no Cloudflare)

By default, BartoloVPN's web interface is served over plain HTTP. If you're using
[Cloudflare Tunnel](cloudflare-tunnel-setup.md), TLS is already handled for you at
Cloudflare's edge and you can stop reading here. This guide is for anyone who wants
real HTTPS on their own domain **without** routing through Cloudflare - e.g. behind
your own router with a port forward.

## Why this matters

Without either Cloudflare Tunnel or the setup below, your admin password and JWT
session cookie are sent in plaintext to anyone who can observe traffic between your
browser and the server. Do one of the two before exposing this to the internet.

## Overview

The stack already ships a `haproxy` service (`docker-compose.yml`) fronting the web
UI on port 80/8081. This guide adds TLS termination to it using a free
[Let's Encrypt](https://letsencrypt.org/) certificate, obtained with `certbot`.

**Prerequisites:**
- A domain name (or subdomain) with an A record pointing at this server's public IP.
- Port 80 reachable from the internet (needed once for the certbot HTTP-01 challenge,
  and again on each renewal unless you switch to DNS-01).

## 1. Obtain a certificate

Run certbot in standalone mode. Stop anything using port 80 first (`docker-compose stop haproxy`
if the stack is already up), since certbot needs to bind it briefly for the challenge:

```bash
sudo apt install certbot   # or: brew install certbot / dnf install certbot
sudo docker compose stop haproxy
sudo certbot certonly --standalone -d vpn.yourdomain.com
sudo docker compose start haproxy
```

This writes `fullchain.pem` and `privkey.pem` to `/etc/letsencrypt/live/vpn.yourdomain.com/`.

HAProxy wants both in a single PEM file:

```bash
sudo mkdir -p /etc/letsencrypt/haproxy
sudo sh -c 'cat /etc/letsencrypt/live/vpn.yourdomain.com/fullchain.pem \
            /etc/letsencrypt/live/vpn.yourdomain.com/privkey.pem \
            > /etc/letsencrypt/haproxy/vpn.yourdomain.com.pem'
```

## 2. Mount the certificate into the haproxy container

Add a volume mount to the `haproxy` service in `docker-compose.yml`:

```yaml
  haproxy:
    # ...existing config...
    volumes:
      - ./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg
      - /etc/letsencrypt/haproxy:/etc/letsencrypt/haproxy:ro
```

## 3. Add a TLS frontend to `haproxy.cfg`

Extend the existing `web_frontend` to also bind 443 with the cert, and redirect plain
HTTP to HTTPS:

```
frontend web_frontend
    bind *:80
    bind *:443 ssl crt /etc/letsencrypt/haproxy/vpn.yourdomain.com.pem
    mode http
    http-request redirect scheme https unless { ssl_fc }
    default_backend web_backend
```

Then in the API's `.env`, set `COOKIE_SECURE=true` (see `env.example`) so the session
cookie is only ever sent over this now-HTTPS connection, and restart:

```bash
docker-compose up -d --force-recreate haproxy vpn-api
```

## 4. Automate renewal

Let's Encrypt certs expire every 90 days. Add a cron job that renews and rebuilds the
combined PEM, then reloads haproxy:

```bash
# /etc/cron.d/bartolovpn-cert-renew
0 3 * * * root certbot renew --quiet --deploy-hook "cat /etc/letsencrypt/live/vpn.yourdomain.com/fullchain.pem /etc/letsencrypt/live/vpn.yourdomain.com/privkey.pem > /etc/letsencrypt/haproxy/vpn.yourdomain.com.pem && docker kill -s HUP bartolo-haproxy"
```

## Notes

- This is independent of Cloudflare Tunnel - use one or the other, not both, unless
  you specifically want Cloudflare in front of your own TLS (double encryption, rarely
  necessary).
- If you'd rather not deal with certbot/cron yourself, [Caddy](https://caddyserver.com/)
  or [Traefik](https://traefik.io/) can replace haproxy entirely and manage certificates
  automatically - that's a larger change (they'd take over haproxy's load-balancing role
  too) and out of scope for this guide.

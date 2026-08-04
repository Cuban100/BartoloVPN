# 🌐 Multi-Region Guide for BartoloVPN

Run WireGuard servers in multiple real countries, and let users pick which one a peer connects through - like Proton/Windscribe/NordVPN's country picker, backed by your own VPS instead of a third party.

This is a different feature from `GEO-SPOOFING.md`: geo-spoofing only changes which DNS resolver a client uses (fake locale, real exit IP unchanged). Multi-region gives each peer a genuinely different exit IP, because it's actually a different server in a different place.

## Architecture

- **This repo (central dashboard)** keeps managing its own local WireGuard server exactly as before - nothing about the existing single-server flow changed.
- **`region-agent/`** is a small, separate service you deploy on each additional VPS. It runs alongside its own `wireguard` container and exposes a minimal authenticated API (create/delete/list peers, health) - never a general shell/exec passthrough.
- The central dashboard talks to each region's agent over HTTPS with a per-region API key, and stores each region's connection details (agent URL, encrypted key, endpoint host/port, country/city) in a new `regions` table.
- Peer creation, listing, editing, and deletion all take an optional `region` (defaults to `"local"`, i.e. today's behavior). Choosing a different region routes that one request to that region's agent instead.

## Adding a new region

1. **Get a VPS** in the country you want. Two realistic options:
   - **Oracle Cloud "Always Free" tier** - genuinely free forever (not a 12-month trial), up to 4 Ampere ARM cores + 24GB RAM. The catch: it's tied to the *one* home region you pick at signup, so it only gets you your first free region, not five. Getting more free regions by creating multiple Oracle accounts is account-limit abuse most providers ban for - don't do that.
   - **DigitalOcean, Vultr, Hetzner, etc.** - roughly $5-7/month per box, any country you want, no account-limit games required.
2. **SSH into it**, clone this repo, and run the installer:
   ```bash
   git clone https://github.com/Cuban100/BartoloVPN.git
   cd BartoloVPN
   ./install.sh
   ```
   `install.sh` asks what you're setting up - choose **"2) A new region for an EXISTING BartoloVPN dashboard"**, and it hands off to `scripts/provision-region.sh` with root (you can also run that script directly if you prefer).
3. **Answer the prompts:**
   - **"Is this an Oracle Cloud (OCI) VPS?"** - answer `y` on Oracle boxes and it'll additionally patch Oracle's stock, overly-restrictive `iptables` rules (which sit underneath `ufw` and silently drop traffic `ufw` claims is allowed) and print a reminder about Oracle's *separate* console-level firewall (Security Lists), which no SSH-run script can touch for you.
   - **Continent, then city** - a guided picker (Europe/Asia/South America/Oceania/Africa/North America, then a short list of real cities per continent) that auto-fills the slug/display name/country code/city for you, or choose "Custom" to type everything in by hand. Picking a continent different from your own is exactly how you get an exit IP that appears to browse from somewhere else - a region on your own continent won't achieve that.
   - Public IP (auto-detected), agent hostname (defaults to a free `sslip.io` address if you don't own a domain), and WireGuard port (default `51820`) - just confirm the suggested defaults unless you need something specific.
   - **Auto-register with your dashboard** - answer `y` and give it your dashboard URL + admin login once; it registers the region for you automatically (retrying for up to a minute if Caddy's TLS cert isn't ready yet). No credentials are stored on the VPS. If you skip this or it fails, it falls back to printing the values for you to paste into the dashboard's Regions tab -> Add Region form manually.
4. The new region now appears in the **Region** dropdown on the WireGuard tab's Add Peer form.

### Oracle Cloud specifics

If step 2's agent health check (or the dashboard's Add Region check) fails only from the *outside* while everything looks fine on the box itself (`docker compose logs`, `curl 127.0.0.1:8912/health` from inside the container all succeed), it's almost always the OCI console firewall, not this script or Docker: **Networking -> Virtual Cloud Networks -> your VCN -> Security Lists -> Default Security List -> Add Ingress Rules** for your WireGuard UDP port, 80/TCP, and 443/TCP, source `0.0.0.0/0`. This is enforced entirely outside the VM, so it's invisible to `ufw`, `iptables`, and this script alike.

## Testing locally without a real VPS

`region-agent/docker-compose.local-test.yml` runs a throwaway "remote" region entirely on your dev machine (distinct container names/ports from both the main stack and a real deployment, no TLS since it never leaves loopback):

```bash
cd region-agent
cp env.local-test.example .env.local-test
docker compose -f docker-compose.local-test.yml --env-file .env.local-test up -d --build

curl -H "X-Agent-Key: $(grep AGENT_API_KEY .env.local-test | cut -d= -f2)" http://127.0.0.1:8788/health
```

Register `http://127.0.0.1:8788` as a region's Agent URL in the dashboard (with the matching key from `.env.local-test`) to exercise the full create/list/edit/delete/QR/download flow against it, exactly like a real remote region.

## What deploying to production still requires

This host runs BartoloVPN from **two** separate clones: development work happens in `~/BartoloVPN`, but the live site (`bartolovpn.caveplex.com`) is served from whatever's on disk in `~/Docker/BartoloVPN`. None of the steps above touch that directory. Rolling this feature out for real still needs the usual sequence: commit/push, then from `~/Docker/BartoloVPN`, `git pull`, rebuild `vpn-api`, and restart it - verified against the live URL, not just "container restarted."

## Limits worth knowing

- A peer's region is fixed at creation - moving it to a different server means deleting it and creating a new one on the target region (there's no live migration).
- If a region's agent is unreachable, the peer list still loads (with a warning) rather than failing entirely - but you can't create/edit/delete peers on that region until it's reachable again.
- The local region can't be renamed, edited, or deleted - it always represents this server.

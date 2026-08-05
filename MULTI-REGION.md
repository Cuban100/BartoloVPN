# 🌐 Multi-Region Guide for BartoloVPN

Run WireGuard servers in multiple real countries, and let users pick which one a peer connects through - like Proton/Windscribe/NordVPN's country picker, backed by your own VPS instead of a third party.

This is a different feature from `GEO-SPOOFING.md`: geo-spoofing only changes which DNS resolver a client uses (fake locale, real exit IP unchanged). Multi-region gives each peer a genuinely different exit IP, because it's actually a different server in a different place.

## Architecture

- **This repo (central dashboard)** keeps managing its own local WireGuard server exactly as before - nothing about the existing single-server flow changed.
- **`region-agent/`** is a small, separate service you deploy on each additional VPS. It runs alongside its own `wireguard` container and exposes a minimal authenticated API (create/delete/list peers, health) - never a general shell/exec passthrough.
- The central dashboard talks to each region's agent over HTTPS with a per-region API key, and stores each region's connection details (agent URL, encrypted key, endpoint host/port, country/city) in a new `regions` table.
- Peer creation, listing, editing, and deletion all take an optional `region` (defaults to `"local"`, i.e. today's behavior). Choosing a different region routes that one request to that region's agent instead.

## Adding a new region

There are two ways to add a region: **one-click on Oracle Cloud** (no SSH, the dashboard does everything), or **manual, on any VPS** (SSH in and run a script). Use the one-click flow if you're on Oracle Cloud - it's faster and doesn't touch a terminal.

### Option A: One-click Oracle Cloud provisioning

From the dashboard's **Regions** tab, click **"Add via Oracle"**. This requires your Oracle Cloud API credentials to already be saved under **Settings -> Oracle Cloud** (tenancy/user OCID, fingerprint, private key, region) - the Settings page can auto-detect these from `~/.ssh/` if you generated them via the OCI Console's API key wizard.

What happens after you click it:
1. The dashboard creates the region row immediately (`health_status: provisioning`) and returns - provisioning itself runs as a background task, so the request doesn't hang for the several minutes a VM takes to boot.
2. It launches a real `VM.Standard.E2.1.Micro` (Always Free tier) instance via the OCI API: picks an Availability Domain with actual capacity (tried in order, since capacity is unevenly distributed and shifts over time), reuses or creates a VCN/subnet/Internet Gateway, and launches Ubuntu 24.04.
3. Cloud-init on the new VM installs Docker, clones this repo, writes the region agent's `.env`, opens the needed firewall ports, and starts the `region-agent` stack - the same steps `scripts/provision-region.sh` does interactively, just unattended.
4. The dashboard polls the new instance until it gets a public IP, then polls the agent's `/health` endpoint until it responds, updating `last_health_check`/`last_health_error` on every attempt so the Regions tab never looks frozen mid-provision.
5. Once healthy, the region is ready to pick in the WireGuard tab's Add Peer form - no different from a manually-provisioned region at that point.

**The "Check" button queries Oracle's real instance state** (via the OCI API), not just an HTTP ping to the agent - so a "Running" instance whose agent is still mid-build (or a truly terminated instance) reports the correct, distinguishable status instead of both looking identically "unreachable." A manual Check is rejected with a clear message while a region is still provisioning, so it can't race the background task and clobber its result.

**Always Free tier limits**: 2 `VM.Standard.E2.1.Micro` instances total, tenancy-wide. An instance orphaned by a failed/interrupted provision (rare, but possible if the dashboard restarts mid-flow) still counts against that quota - if "Add via Oracle" ever reports capacity errors unexpectedly, check the OCI Console's Instances list against what the dashboard's Regions tab shows before creating another one.

### Option B: Manual provisioning on any VPS

1. **Get a VPS** in the country you want. Two realistic options:
   - **Oracle Cloud "Always Free" tier** - genuinely free forever (not a 12-month trial), up to 4 Ampere ARM cores + 24GB RAM. The catch: it's tied to the *one* home region you pick at signup, so it only gets you your first free region, not five. Getting more free regions by creating multiple Oracle accounts is account-limit abuse most providers ban for - don't do that.
   - **DigitalOcean, Vultr, Hetzner, etc.** - roughly $5-7/month per box, any country you want, no account-limit games required.
2. **SSH into it**, clone this repo, and run the provisioning script directly (root required):
   ```bash
   git clone https://github.com/Cuban100/BartoloVPN.git
   cd BartoloVPN
   sudo ./scripts/provision-region.sh
   ```
   (`install.sh`/`vpn-setup.py` are for setting up a brand-new *dashboard* - they don't have a region-provisioning mode. This script is separate and self-contained.)
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

This host runs BartoloVPN from **two** separate clones: development work happens in `~/Docker/BartoloVPN-Production`, but the live site (`bartolovpn.caveplex.com`) is served from whatever's on disk in `~/Docker/BartoloVPN`. None of the steps above touch that directory. Rolling this feature out for real still needs the usual sequence: commit/push from the dev clone, then from `~/Docker/BartoloVPN`, `git pull`. `vpn-api` runs `uvicorn --reload`, so most Python/JS changes apply automatically on the next request - only changes to `docker-compose.yml` itself (new/changed volume mounts, env vars, images) need an actual rebuild/recreate of the affected container(s), verified against the live URL, not just "container restarted."

### Region agent's own gotcha: `wireguard`/`caddy` share a network namespace

`region-agent/docker-compose.yml`'s `region-agent` and `caddy` services both use `network_mode: "service:wireguard"`. If the `wireguard` container ever gets recreated (e.g. as a side effect of `docker compose up -d --build` on just the `region-agent` service) without `caddy` being recreated too, `caddy` is left pointing at a network namespace that no longer exists - HTTPS to the agent silently stops working even though all three containers show "running". A plain `docker restart` won't fix it (the old namespace is gone, not just stale); it needs `docker compose up -d --force-recreate caddy` to re-attach it to whichever `wireguard` container is currently running. Symptom: the agent's `/health` responds fine over plain HTTP inside the container, but the public HTTPS URL times out or refuses connections.

## Limits worth knowing

- A peer's region is fixed at creation - moving it to a different server means deleting it and creating a new one on the target region (there's no live migration).
- If a region's agent is unreachable, the peer list still loads (with a warning) rather than failing entirely - but you can't create/edit/delete peers on that region until it's reachable again.
- The local region can't be renamed, edited, or deleted - it always represents this server.

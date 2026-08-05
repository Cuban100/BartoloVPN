# 🌍 Geo-Spoofing Guide for BartoloVPN

> ⚠️ **Optional, DIY, and not configured on a fresh install.** Nothing here runs
> automatically - you have to run `scripts/geo-spoofing.sh` yourself, and as of
> now it only supports **Sweden**, hardcoded (not "any country" - see below).

## ⚠️ What this actually does (read before using)

`scripts/geo-spoofing.sh setup` does exactly one real thing: it edits `.env` to
point `DNS_SERVERS`/`WIREGUARD_DNS` at Swedish DNS resolvers. That's it. It also
*generates* several extra files (`docker-compose.swedish.yml`, `haproxy.swedish.cfg`,
a GeoIP config with example/fake IP ranges) - but **none of those are wired into
the real stack**. `docker-compose.yml` never references them, and running
`geo-spoofing.sh start` brings up a second, separate, unrelated WireGuard
container rather than changing the real one.

**This does not change your actual exit IP or its geolocation.** A site that
geolocates by IP (which is most of them - Netflix, banks, `ipinfo.io`, etc.)
will still see your real server's location, because DNS resolver choice has no
effect on which IP your traffic actually egresses from. This is the same
distinction [MULTI-REGION.md](MULTI-REGION.md) draws: only a genuinely
different server in a different place (a multi-region peer) changes your exit
IP. DNS-only spoofing changes what a handful of DNS-based geolocation checks
see, and nothing else - don't rely on it for anything that matters.

## What it's actually useful for

Making a client's DNS queries resolve through Swedish servers instead of your
own ISP's or a US-based public resolver - e.g. for content that geolocates
purely by DNS resolver rather than IP (rare, but it exists), or just to keep
DNS traffic off your ISP's resolvers.

## Usage

```bash
# Point DNS_SERVERS/WIREGUARD_DNS in .env at Swedish resolvers
./scripts/geo-spoofing.sh setup

# Generate a WireGuard client config that uses those DNS servers
./scripts/geo-spoofing.sh client friend1

# Show current DNS-related .env values
./scripts/geo-spoofing.sh status
```

After `setup`, restart the real stack for the new `DNS_SERVERS`/`WIREGUARD_DNS`
values to take effect:
```bash
docker-compose up -d --force-recreate wireguard vpn-api
```

`./scripts/geo-spoofing.sh start` / `stop` bring up/down the separate,
disconnected `docker-compose.swedish.yml` stack described above - almost
certainly not what you want; there's no supported way today to point the
*real* WireGuard/OpenVPN containers' DNS at Sweden other than the `setup`
step above plus a restart.

## Other countries

Not currently supported. The script's Swedish DNS servers, timezone, and
locale values are hardcoded, not parameterized - "German mode" or "Japanese
mode" would need someone to add that (a real script change, not a config
option). If you want a genuinely different exit country/IP, see
[MULTI-REGION.md](MULTI-REGION.md) instead - that's the feature actually built
for that.

## Manual DNS-only spoofing for another country

If you want to do the DNS-only version yourself for a country other than
Sweden, the mechanism is simple - set these two `.env` values to that
country's public DNS resolvers, then restart:

```bash
DNS_SERVERS=<resolver1>,<resolver2>
WIREGUARD_DNS=<resolver1>,<resolver2>
```

Verify with `docker exec bartolovpn-wireguard cat /etc/resolv.conf` and a DNS
leak test site - remembering, as above, that this only affects DNS-based
checks, not your real exit IP.

---

**Remember**: this changes DNS resolution only. It is not an anonymity tool
and does not hide your real location from anything that checks IP geolocation
directly.

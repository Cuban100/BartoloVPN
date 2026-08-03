#!/usr/bin/env python3
"""
DNS query activity tracking for BartoloVPN.

Two separate CoreDNS instances only ever log queries to their own stdout
(no file-output option in either): the one built into the wireguard
container (handling DNS for WireGuard peers via PEERDNS=auto), and a
second, standalone one dedicated to OpenVPN clients (see docker-compose.yml's
openvpn-dns service - OpenVPN's own container has no network route to
wireguard's CoreDNS, so it gets its own instance rather than restructuring
wireguard's networking). To get either into the dashboard without granting
vpn-api broad Docker access, this polls a narrowly-scoped, read-only
docker-log-proxy (container-logs only, no exec/create/etc) for new lines
from both, parses CoreDNS's default log format, and stores per-peer
domain lookups. Protocol is derived later from which subnet the peer_ip
falls in (10.13.13.0/24 = WireGuard, 10.8.0.0/24 = OpenVPN), not stored
here, so no DB migration was needed for this to work retroactively too.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Optional

import aiohttp

from database import AsyncSessionLocal, DnsQueryLog

logger = logging.getLogger(__name__)

DOCKER_LOG_PROXY_URL = "http://127.0.0.1:2375"
DNS_SOURCE_CONTAINERS = ["bartolo-wireguard", "bartolo-openvpn-dns"]
POLL_INTERVAL_SECONDS = 10

# CoreDNS's default `log` plugin format, e.g.:
# [INFO] 10.13.13.4:51234 - 12345 "A IN example.com. udp 512 false 4096" NOERROR qr,aa,rd 100 0.000123456s
_LOG_LINE_RE = re.compile(
    r'\[INFO\]\s+(?P<ip>[0-9.]+):\d+\s+-\s+\d+\s+"\w+\s+\w+\s+(?P<domain>\S+?)\.?\s'
)

_last_since_epoch: Dict[str, float] = {}


def _demux_docker_log_stream(raw: bytes) -> str:
    """Docker's container-logs API multiplexes stdout/stderr with an 8-byte
    frame header (1 byte stream type, 3 reserved, 4 byte big-endian length)
    ahead of each chunk. Strip that framing to get plain text."""
    out = []
    i = 0
    while i + 8 <= len(raw):
        length = int.from_bytes(raw[i + 4:i + 8], 'big')
        start = i + 8
        end = start + length
        out.append(raw[start:end])
        i = end
    return b"".join(out).decode(errors="replace")


async def _poll_container(container: str) -> list:
    """Fetch new CoreDNS log lines from one container since that
    container's last poll. Returns parsed (datetime, ip, domain) tuples."""
    last_epoch = _last_since_epoch.get(container)
    params = {"stdout": "true", "timestamps": "true"}
    if last_epoch is not None:
        params["since"] = f"{last_epoch:.6f}"
    else:
        # First run: only look back a short window, not the container's whole history
        params["since"] = str(int(datetime.now(timezone.utc).timestamp()) - 60)

    url = f"{DOCKER_LOG_PROXY_URL}/containers/{container}/logs"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"docker-log-proxy returned {resp.status} fetching {container} logs")
                    return []
                raw = await resp.read()
    except Exception as e:
        logger.warning(f"Failed to fetch CoreDNS logs from {container} via docker-log-proxy: {e}")
        return []

    text = _demux_docker_log_stream(raw)
    if not text:
        return []

    max_epoch = last_epoch
    entries = []
    for line in text.splitlines():
        parts = line.split(' ', 1)
        if len(parts) != 2:
            continue
        ts_str, rest = parts
        match = _LOG_LINE_RE.search(rest)
        if not match:
            continue
        try:
            # Docker emits RFC3339Nano timestamps; keep only microsecond precision
            dt = datetime.strptime(ts_str[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        epoch = dt.timestamp()
        if max_epoch is None or epoch > max_epoch:
            max_epoch = epoch
        entries.append((dt, match.group("ip"), match.group("domain")))

    if max_epoch is not None:
        # nudge past the last seen line so it isn't re-fetched next poll
        _last_since_epoch[container] = max_epoch + 0.000001

    return entries


async def poll_dns_queries_once():
    """Poll every CoreDNS source (WireGuard's built-in instance, OpenVPN's
    standalone one) for new query log lines and store them."""
    all_entries = []
    for container in DNS_SOURCE_CONTAINERS:
        all_entries.extend(await _poll_container(container))

    if not all_entries:
        return

    async with AsyncSessionLocal() as db:
        for dt, ip, domain in all_entries:
            db.add(DnsQueryLog(peer_ip=ip, domain=domain, timestamp=dt.replace(tzinfo=None)))
        await db.commit()


async def dns_activity_poller():
    """Background task: poll CoreDNS query logs on an interval for the
    lifetime of the app."""
    while True:
        try:
            await poll_dns_queries_once()
        except Exception as e:
            logger.warning(f"DNS activity poll iteration failed: {e}")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

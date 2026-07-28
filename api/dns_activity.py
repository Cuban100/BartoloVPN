#!/usr/bin/env python3
"""
DNS query activity tracking for BartoloVPN.

CoreDNS (running inside the wireguard container, handling DNS for all
peers via PEERDNS=auto) only ever logs queries to its own stdout - it has
no file-output option. To get that into the dashboard without granting
vpn-api broad Docker access, this polls a narrowly-scoped, read-only
docker-log-proxy (container-logs only, no exec/create/etc) for new lines,
parses CoreDNS's default log format, and stores per-peer domain lookups.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from database import AsyncSessionLocal, DnsQueryLog

logger = logging.getLogger(__name__)

DOCKER_LOG_PROXY_URL = "http://127.0.0.1:2375"
WIREGUARD_CONTAINER = "bartolo-wireguard"
POLL_INTERVAL_SECONDS = 10

# CoreDNS's default `log` plugin format, e.g.:
# [INFO] 10.13.13.4:51234 - 12345 "A IN example.com. udp 512 false 4096" NOERROR qr,aa,rd 100 0.000123456s
_LOG_LINE_RE = re.compile(
    r'\[INFO\]\s+(?P<ip>[0-9.]+):\d+\s+-\s+\d+\s+"\w+\s+\w+\s+(?P<domain>\S+?)\.?\s'
)

_last_since_epoch: Optional[float] = None


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


async def poll_dns_queries_once():
    """Fetch new CoreDNS log lines since the last poll and store parsed queries."""
    global _last_since_epoch

    params = {"stdout": "true", "timestamps": "true"}
    if _last_since_epoch is not None:
        params["since"] = f"{_last_since_epoch:.6f}"
    else:
        # First run: only look back a short window, not the container's whole history
        params["since"] = str(int(datetime.now(timezone.utc).timestamp()) - 60)

    url = f"{DOCKER_LOG_PROXY_URL}/containers/{WIREGUARD_CONTAINER}/logs"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f"docker-log-proxy returned {resp.status} fetching wireguard logs")
                    return
                raw = await resp.read()
    except Exception as e:
        logger.warning(f"Failed to fetch CoreDNS logs via docker-log-proxy: {e}")
        return

    text = _demux_docker_log_stream(raw)
    if not text:
        return

    max_epoch = _last_since_epoch
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
        _last_since_epoch = max_epoch + 0.000001

    if not entries:
        return

    async with AsyncSessionLocal() as db:
        for dt, ip, domain in entries:
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

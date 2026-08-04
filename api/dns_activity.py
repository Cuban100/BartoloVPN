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
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, Optional

import aiohttp

from database import AsyncSessionLocal, DnsQueryLog

logger = logging.getLogger(__name__)

DOCKER_LOG_PROXY_URL = "http://127.0.0.1:2375"
# Compose *service* names, not hardcoded container names - container_name:
# is intentionally not set in docker-compose.yml (see main.py's
# _resolve_sibling_container for why), so the real container name has to
# be looked up via compose labels instead of assumed.
DNS_SOURCE_SERVICES = ["wireguard", "openvpn-dns"]
POLL_INTERVAL_SECONDS = 10

_sibling_container_cache: Dict[str, str] = {}


async def _resolve_sibling_container(service_name: str) -> Optional[str]:
    """Same approach as VPNManager._resolve_sibling_container in main.py -
    duplicated here rather than imported since this module has no access
    to a VPNManager instance and this is a small, self-contained lookup."""
    if service_name in _sibling_container_cache:
        return _sibling_container_cache[service_name]

    own_id = os.environ.get("HOSTNAME", "")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{DOCKER_LOG_PROXY_URL}/containers/{own_id}/json",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status >= 400:
                    logger.warning(f"Could not inspect own container to resolve compose project (HTTP {resp.status})")
                    return None
                own_info = await resp.json()
            project = own_info.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
            if not project:
                logger.warning("Own container has no com.docker.compose.project label - can't resolve sibling containers")
                return None

            filters = json.dumps({
                "label": [f"com.docker.compose.project={project}", f"com.docker.compose.service={service_name}"]
            })
            async with session.get(
                f"{DOCKER_LOG_PROXY_URL}/containers/json",
                params={"filters": filters},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status >= 400:
                    logger.warning(f"Could not list containers to resolve compose service '{service_name}' (HTTP {resp.status})")
                    return None
                matches = await resp.json()
    except Exception as e:
        logger.warning(f"Failed to resolve container for compose service '{service_name}': {e}")
        return None

    if not matches:
        logger.warning(f"No running container found for compose service '{service_name}' in project '{project}'")
        return None

    resolved = matches[0]["Names"][0].lstrip("/")
    _sibling_container_cache[service_name] = resolved
    return resolved

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
        domain = match.group("domain")
        if not any(c.isalpha() for c in domain):
            # Real domains always have an alphabetic TLD. This also happens
            # to reject CoreDNS's `loop` plugin canary probes (e.g.
            # "4148863610893235485.505215156570136642"), which loosely
            # match this same line shape but aren't a real query - see
            # config/wireguard-coredns/Corefile for the actual fix
            # (forwarding target that avoids the loop).
            continue
        try:
            # Docker emits RFC3339Nano timestamps; keep only microsecond precision
            dt = datetime.strptime(ts_str[:26], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        epoch = dt.timestamp()
        if max_epoch is None or epoch > max_epoch:
            max_epoch = epoch
        entries.append((dt, match.group("ip"), domain))

    if max_epoch is not None:
        # nudge past the last seen line so it isn't re-fetched next poll
        _last_since_epoch[container] = max_epoch + 0.000001

    return entries


async def poll_dns_queries_once():
    """Poll every CoreDNS source (WireGuard's built-in instance, OpenVPN's
    standalone one) for new query log lines and store them."""
    all_entries = []
    for service_name in DNS_SOURCE_SERVICES:
        container = await _resolve_sibling_container(service_name)
        if container:
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

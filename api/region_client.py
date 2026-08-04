#!/usr/bin/env python3
"""
HTTP client for talking to a remote region agent (see region-agent/agent.py).

Uses aiohttp, matching the pattern api/main.py already uses elsewhere
(_docker_exec) - no new HTTP dependency needed.
"""

from typing import Any, Dict, List

import aiohttp
from fastapi import HTTPException


class RegionClient:
    """Talks to one region agent's HTTP API. Never logs the agent key -
    only the region slug/URL, which are not secret."""

    def __init__(self, slug: str, agent_url: str, agent_key: str, timeout_seconds: float = 15.0):
        self.slug = slug
        self.agent_url = agent_url.rstrip("/")
        self._headers = {"X-Agent-Key": agent_key}
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def _request(self, method: str, path: str, json_body: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.agent_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.request(method, url, headers=self._headers, json=json_body) as resp:
                    if resp.status == 401:
                        raise HTTPException(status_code=502, detail=f"Region {self.slug}: agent rejected our API key")
                    if resp.status == 429:
                        raise HTTPException(status_code=502, detail=f"Region {self.slug}: agent is rate-limiting us")
                    if resp.status >= 400:
                        detail = await resp.text()
                        raise HTTPException(status_code=502, detail=f"Region {self.slug}: agent returned {resp.status}: {detail[:200]}")
                    return await resp.json()
        except HTTPException:
            raise
        except aiohttp.ClientError as e:
            raise HTTPException(status_code=502, detail=f"Region {self.slug} unreachable: {type(e).__name__}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Region {self.slug} request failed: {type(e).__name__}")

    async def health(self) -> Dict[str, Any]:
        return await self._request("GET", "/health")

    async def list_peers(self) -> List[Dict[str, Any]]:
        return await self._request("GET", "/peers")

    async def create_peer(self, peer_name: str, allowed_ips: str) -> Dict[str, Any]:
        return await self._request("POST", "/peers", {"peer_name": peer_name, "allowed_ips": allowed_ips})

    async def update_peer(self, peer_name: str, new_name: str, allowed_ips: str) -> Dict[str, Any]:
        return await self._request("PUT", f"/peers/{peer_name}", {"peer_name": new_name, "allowed_ips": allowed_ips})

    async def delete_peer(self, peer_name: str) -> Dict[str, Any]:
        return await self._request("DELETE", f"/peers/{peer_name}")

    async def get_peer_config(self, peer_name: str) -> Dict[str, Any]:
        return await self._request("GET", f"/peers/{peer_name}/config")

    async def get_peer_qrcode(self, peer_name: str) -> Dict[str, Any]:
        return await self._request("GET", f"/peers/{peer_name}/qrcode")

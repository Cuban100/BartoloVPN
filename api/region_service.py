#!/usr/bin/env python3
"""
Region management: encrypting/decrypting stored agent keys, resolving a
Region by slug, health-checking regions, and the background poller that
keeps each Region's health_status/peer_count fresh.
"""

import asyncio
import base64
import hashlib
import logging
from datetime import datetime
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from config import settings  # type: ignore  # Pylance: namespace collision with config dir
from database import AsyncSessionLocal, Region
from region_client import RegionClient

logger = logging.getLogger(__name__)

# Regions are re-checked on this interval by region_health_poller.
HEALTH_CHECK_INTERVAL_SECONDS = 60


def _fernet() -> Fernet:
    """Derives a valid Fernet key from settings.region_agent_encryption_key
    (an arbitrary operator-chosen secret, not necessarily already in
    Fernet's own base64/32-byte format) via SHA-256, so the operator can
    set REGION_AGENT_ENCRYPTION_KEY to any sufficiently long random string
    rather than needing to generate a Fernet key specifically."""
    digest = hashlib.sha256(settings.region_agent_encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_agent_key(agent_key: str) -> str:
    return _fernet().encrypt(agent_key.encode()).decode()


def decrypt_agent_key(agent_key_encrypted: str) -> str:
    try:
        return _fernet().decrypt(agent_key_encrypted.encode()).decode()
    except InvalidToken:
        # Never include the ciphertext or key material in the raised error.
        raise ValueError("Could not decrypt stored agent key - REGION_AGENT_ENCRYPTION_KEY may have changed")


async def get_region_by_slug(slug: str) -> Optional[Region]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Region).where(Region.slug == slug))
        return result.scalar_one_or_none()


def build_region_client(region: Region) -> RegionClient:
    """Only valid for non-local regions - callers must branch on
    region.is_local before reaching here (see main.py's peer routes)."""
    if region.is_local or not region.agent_url or not region.agent_key_encrypted:
        raise ValueError(f"Region {region.slug} has no agent configured")
    return RegionClient(region.slug, region.agent_url, decrypt_agent_key(region.agent_key_encrypted))


async def health_check_region(region: Region) -> Region:
    """Pings a region's agent and updates its stored health fields.
    Returns the updated Region. Local regions are always reported healthy
    without a network call - the local server's own health is whatever
    VPNManager.get_wireguard_status already reports elsewhere."""
    async with AsyncSessionLocal() as session:
        db_region = await session.get(Region, region.id)
        if db_region is None:
            return region

        if db_region.is_local:
            db_region.health_status = "healthy"
            db_region.last_health_check = datetime.utcnow()
            db_region.last_health_error = None
            await session.commit()
            await session.refresh(db_region)
            return db_region

        try:
            client = build_region_client(db_region)
            health = await client.health()
            db_region.health_status = "healthy"
            db_region.peer_count = health.get("peer_count", db_region.peer_count)
            db_region.last_health_error = None
        except Exception as e:
            db_region.health_status = "unreachable"
            # Message only - never the agent key, which errors from
            # RegionClient/build_region_client never include anyway.
            db_region.last_health_error = str(e)[:500]
            logger.warning(f"Region {db_region.slug} health check failed: {e}")
        finally:
            db_region.last_health_check = datetime.utcnow()
            await session.commit()
            await session.refresh(db_region)

        return db_region


async def health_check_all_regions() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Region).where(Region.is_active == True))
        regions = result.scalars().all()
    for region in regions:
        await health_check_region(region)


async def region_health_poller():
    """Background task: re-check every active region's health on an
    interval for the lifetime of the app (same shape as dns_activity_poller
    in dns_activity.py)."""
    while True:
        try:
            await health_check_all_regions()
        except Exception as e:
            logger.warning(f"Region health poll iteration failed: {e}")
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)

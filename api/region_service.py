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
from database import AsyncSessionLocal, Region, SystemSettings
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


# Generic aliases - the encryption here isn't actually specific to region
# agent keys, it's just "encrypt an arbitrary secret at rest using
# REGION_AGENT_ENCRYPTION_KEY." Reused for other secrets (e.g. Settings'
# Oracle Cloud API key) instead of deriving a second Fernet key for them.
encrypt_secret = encrypt_agent_key


def decrypt_agent_key(agent_key_encrypted: str) -> str:
    try:
        return _fernet().decrypt(agent_key_encrypted.encode()).decode()
    except InvalidToken:
        # Never include the ciphertext or key material in the raised error.
        raise ValueError("Could not decrypt stored agent key - REGION_AGENT_ENCRYPTION_KEY may have changed")


decrypt_secret = decrypt_agent_key


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

        # For Oracle-provisioned regions, check the real instance state
        # directly with Oracle first - a failed HTTP ping to the agent
        # alone is only ever a guess (a real production incident: showed
        # a generic "unreachable" for an instance that was genuinely
        # RUNNING and just mid-build, indistinguishable from one Oracle
        # had actually terminated). If Oracle itself says the instance is
        # gone, report that definitively instead of pinging a dead agent;
        # if it says RUNNING, fold that into the message either way so
        # "unreachable" never looks like it could mean the VM is down
        # when Oracle confirms it's up.
        oracle_instance_state = None
        if db_region.oracle_instance_id:
            try:
                import oracle_service  # local import - oracle_service imports this module
                settings_row = await session.get(SystemSettings, 1)
                oracle_instance_state = await oracle_service.get_instance_state(settings_row, db_region.oracle_instance_id)
            except Exception as e:
                logger.warning(f"Region {db_region.slug}: could not check real Oracle instance state: {e}")

        if oracle_instance_state is not None and oracle_instance_state not in ("RUNNING", "PROVISIONING", "STARTING"):
            db_region.health_status = "unreachable"
            db_region.last_health_error = f"Oracle reports this instance is {oracle_instance_state} (not running)"
            db_region.last_health_check = datetime.utcnow()
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
            state_note = f"instance is {oracle_instance_state} in Oracle, but " if oracle_instance_state else ""
            # Message only - never the agent key, which errors from
            # RegionClient/build_region_client never include anyway.
            db_region.last_health_error = f"{state_note}agent not responding: {str(e)[:400]}"
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

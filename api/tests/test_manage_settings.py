"""Tests for manage_settings.py's export/import of the SystemSettings row -
built after a real incident where two separate clones of this repo
(BartoloVPN and BartoloVPN-Production) each had their own database, so
Settings entered in one dashboard never showed up in the other."""

import json

import pytest

import manage_settings
import region_service
from database import AsyncSessionLocal, SystemSettings


@pytest.fixture(autouse=True, scope="module")
def _reset_settings_row_after_module():
    # SystemSettings is a single shared row across the whole test session
    # (client fixture is session-scoped) - reset it back to the model's
    # own column defaults here so whichever test file runs next isn't
    # left looking at whatever this file imported into it. Resetting
    # in place (not deleting) matters: test_oracle_region.py's own
    # cleanup helper assumes the row already exists and doesn't
    # defensively re-create it if missing.
    yield

    async def _reset_row():
        async with AsyncSessionLocal() as session:
            s = await session.get(SystemSettings, 1)
            if s is None:
                # The last test in this file (test_export_with_no_settings_
                # row_does_not_crash) deletes the row entirely - recreate
                # it rather than leaving it missing for whatever runs next.
                s = SystemSettings(id=1)
                session.add(s)
            s.timezone = "UTC"
            s.dns_servers = "1.1.1.1,8.8.8.8"
            s.encryption_level = 256
            s.kill_switch_enabled = True
            s.log_level = "INFO"
            s.log_retention_days = 30
            s.oracle_enabled = False
            s.oracle_tenancy_ocid = None
            s.oracle_user_ocid = None
            s.oracle_fingerprint = None
            s.oracle_api_key_encrypted = None
            s.oracle_region = None
            s.oracle_ssh_key_name = None
            await session.commit()

    import asyncio
    asyncio.get_event_loop().run_until_complete(_reset_row())


async def _set_settings(**fields):
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)
        for key, value in fields.items():
            setattr(s, key, value)
        await session.commit()


async def _get_settings() -> SystemSettings:
    async with AsyncSessionLocal() as session:
        return await session.get(SystemSettings, 1)


def test_export_writes_decrypted_key_and_chmod_600(client, tmp_path):
    import asyncio

    async def scenario():
        await _set_settings(
            timezone="America/Chicago",
            oracle_enabled=True,
            oracle_tenancy_ocid="ocid1.tenancy.oc1..exporttest",
            oracle_api_key_encrypted=region_service.encrypt_secret("SUPER-SECRET-PRIVATE-KEY"),
        )
        out_path = tmp_path / "export1.json"
        await manage_settings.export_settings(str(out_path))

        assert out_path.stat().st_mode & 0o777 == 0o600
        data = json.loads(out_path.read_text())
        assert data["timezone"] == "America/Chicago"
        assert data["oracle_tenancy_ocid"] == "ocid1.tenancy.oc1..exporttest"
        # The plaintext key must be recoverable from the export - that's
        # the whole point (re-encryptable under a different install's key)
        assert data["oracle_api_key"] == "SUPER-SECRET-PRIVATE-KEY"
        # And the encrypted-at-rest form must never leak into the export
        assert "oracle_api_key_encrypted" not in data

    asyncio.get_event_loop().run_until_complete(scenario())


def test_import_restores_fields_and_reencrypts_key(client, tmp_path):
    import asyncio

    async def scenario():
        export_path = tmp_path / "export2.json"
        export_path.write_text(json.dumps({
            "timezone": "Europe/Paris",
            "dns_servers": "9.9.9.9,1.1.1.1",
            "oracle_enabled": True,
            "oracle_tenancy_ocid": "ocid1.tenancy.oc1..importtest",
            "oracle_region": "eu-paris-1",
            "oracle_api_key": "ANOTHER-SECRET-PRIVATE-KEY",
        }))

        # Simulate a target install with different existing state
        await _set_settings(timezone="UTC", oracle_tenancy_ocid=None, oracle_api_key_encrypted=None)

        await manage_settings.import_settings(str(export_path))

        s = await _get_settings()
        assert s.timezone == "Europe/Paris"
        assert s.dns_servers == "9.9.9.9,1.1.1.1"
        assert s.oracle_tenancy_ocid == "ocid1.tenancy.oc1..importtest"
        assert s.oracle_region == "eu-paris-1"
        # Re-encrypted under *this* install's key, and correctly decryptable
        assert region_service.decrypt_secret(s.oracle_api_key_encrypted) == "ANOTHER-SECRET-PRIVATE-KEY"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_import_partial_file_does_not_clobber_existing_fields(client, tmp_path):
    import asyncio

    async def scenario():
        await _set_settings(
            timezone="Asia/Tokyo",
            log_level="DEBUG",
            oracle_tenancy_ocid="ocid1.tenancy.oc1..keepme",
        )

        partial_path = tmp_path / "partial.json"
        partial_path.write_text(json.dumps({"timezone": "Asia/Seoul"}))

        await manage_settings.import_settings(str(partial_path))

        s = await _get_settings()
        assert s.timezone == "Asia/Seoul"
        # Untouched by the partial import
        assert s.log_level == "DEBUG"
        assert s.oracle_tenancy_ocid == "ocid1.tenancy.oc1..keepme"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_export_with_no_settings_row_does_not_crash(client, tmp_path):
    import asyncio

    async def scenario():
        async with AsyncSessionLocal() as session:
            s = await session.get(SystemSettings, 1)
            if s is not None:
                await session.delete(s)
                await session.commit()

        out_path = tmp_path / "export_empty.json"
        await manage_settings.export_settings(str(out_path))
        assert not out_path.exists()

    asyncio.get_event_loop().run_until_complete(scenario())

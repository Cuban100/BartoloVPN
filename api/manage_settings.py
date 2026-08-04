#!/usr/bin/env python3
"""
Export/import the Settings page's SystemSettings row (general prefs +
Oracle Cloud credentials) - just this one config row, not peers, clients,
users, or regions. Built after a real incident: two separate clones of
this repo (BartoloVPN and BartoloVPN-Production) each run their own
database, so settings entered via one dashboard never appear in the
other automatically.

Run inside the container, where all dependencies already exist:
    docker-compose exec vpn-api python manage_settings.py export /app/settings-backup.json
    docker-compose exec vpn-api python manage_settings.py import /app/settings-backup.json

/app is bind-mounted from this repo's api/ directory, so a file written
to /app/... shows up as ./api/... on the host afterward.

The exported file holds the Oracle API signing key in PLAINTEXT, not the
Fernet-encrypted-at-rest form - deliberate, so import re-encrypts
correctly even when the target install uses a different
REGION_AGENT_ENCRYPTION_KEY, but it means the file is as sensitive as
the key itself. Written chmod 600; delete it once you've imported it
elsewhere, and never commit it (see .gitignore).
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import AsyncSessionLocal, SystemSettings  # noqa: E402
import region_service  # noqa: E402

# Deliberately excludes id/updated_at (not meaningful across installs) and
# oracle_api_key_encrypted (handled separately below, decrypted for export
# / re-encrypted for import rather than copied as an opaque blob).
FIELDS = (
    "timezone", "dns_servers", "encryption_level", "kill_switch_enabled",
    "log_level", "log_retention_days",
    "oracle_enabled", "oracle_tenancy_ocid", "oracle_user_ocid",
    "oracle_fingerprint", "oracle_region", "oracle_ssh_key_name",
)


async def build_export_data() -> Optional[dict]:
    """Core export logic, reused by both the CLI below and the Settings
    page's Export button (GET /settings/export in api/main.py). Returns
    None if there's no settings row yet."""
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            return None

        data = {field: getattr(s, field) for field in FIELDS}
        data["oracle_api_key"] = (
            region_service.decrypt_secret(s.oracle_api_key_encrypted)
            if s.oracle_api_key_encrypted else None
        )
        data["exported_at"] = datetime.utcnow().isoformat() + "Z"
        return data


async def apply_import_data(data: dict) -> None:
    """Core import logic, reused by both the CLI below and the Settings
    page's Import button (POST /settings/import in api/main.py)."""
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)

        # Only overwrites fields actually present and non-null in the file
        # - matches PUT /settings' existing "leave unchanged if omitted"
        # semantics, so importing a partial export can't wipe out fields
        # the target install already has configured.
        for field in FIELDS:
            if field in data and data[field] is not None:
                value = data[field]
                # Same defensive strip as PUT /settings - an invisible
                # trailing newline in an OCID/fingerprint silently fails
                # Oracle API authentication.
                if isinstance(value, str):
                    value = value.strip()
                setattr(s, field, value)

        if data.get("oracle_api_key"):
            s.oracle_api_key_encrypted = region_service.encrypt_secret(data["oracle_api_key"].strip())

        await session.commit()


async def export_settings(path: str) -> None:
    data = await build_export_data()
    if data is None:
        print("No settings row found - nothing to export.")
        return

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)

    print(f"Exported settings to {path}")
    if data["oracle_api_key"]:
        print("WARNING: this file contains your Oracle API private key in "
              "PLAINTEXT (needed to re-encrypt correctly on import into a "
              "different install). Treat it like the key itself - delete "
              "it once you've imported it elsewhere, never commit it.")


async def import_settings(path: str) -> None:
    with open(path) as f:
        data = json.load(f)
    await apply_import_data(data)
    print(f"Imported settings from {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    export_parser = sub.add_parser("export", help="Write the current settings to a JSON file")
    export_parser.add_argument("path")

    import_parser = sub.add_parser("import", help="Load settings from a JSON file, overwriting any fields it contains")
    import_parser.add_argument("path")

    args = parser.parse_args()
    if args.command == "export":
        asyncio.run(export_settings(args.path))
    elif args.command == "import":
        asyncio.run(import_settings(args.path))


if __name__ == "__main__":
    main()

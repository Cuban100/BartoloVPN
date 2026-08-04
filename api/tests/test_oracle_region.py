"""Tests for Oracle Cloud region auto-provisioning (api/oracle_service.py,
POST /regions/oracle). Real OCI API calls are always mocked/monkeypatched
here - see oracle_service.py's module docstring for why the actual OCI
integration itself couldn't be exercised against a real account."""

import asyncio

import pytest

import main
import oracle_service
from database import AsyncSessionLocal, Region, SystemSettings
from oracle_service import OracleProvisioningError


def test_generate_cloud_init_embeds_agent_key_and_port():
    script = oracle_service.generate_cloud_init("deadbeef" * 8, 51821)
    assert script.startswith("#!/bin/bash")
    assert "AGENT_API_KEY=" + "deadbeef" * 8 in script
    assert "WIREGUARD_PORT=51821" in script
    assert "ufw allow 51821/udp" in script
    assert oracle_service.GITHUB_REPO_URL in script
    # No dashboard credentials of any kind belong in this script
    assert "DASHBOARD" not in script
    assert "password" not in script.lower()


async def _enable_oracle_settings():
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)
        s.oracle_enabled = True
        await session.commit()


async def _disable_oracle_settings():
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        s.oracle_enabled = False
        await session.commit()


@pytest.fixture(autouse=True, scope="module")
def _reset_oracle_enabled_after_module():
    # SystemSettings is a single shared row across the whole test session
    # (client fixture is session-scoped) - other files' tests (e.g.
    # test_settings.py's "defaults on first load") assume oracle_enabled
    # starts False, so this file must not leave it toggled on for
    # whichever test file happens to run next.
    yield
    asyncio.get_event_loop().run_until_complete(_disable_oracle_settings())


def test_create_oracle_region_non_admin_forbidden(client):
    login = client.post("/auth/login", json={"username": "settings_test_user", "password": "SettingsTestPassw0rd!"})
    if login.status_code != 200:
        client.post("/auth/register", json={"username": "settings_test_user", "password": "SettingsTestPassw0rd!"})
        login = client.post("/auth/login", json={"username": "settings_test_user", "password": "SettingsTestPassw0rd!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post(
        "/regions/oracle",
        json={"slug": "or-test1", "display_name": "Oracle Test", "country_code": "US"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_create_oracle_region_requires_oracle_enabled(client, admin_headers):
    asyncio.get_event_loop().run_until_complete(_disable_oracle_settings())
    resp = client.post(
        "/regions/oracle",
        json={"slug": "or-test2", "display_name": "Oracle Test 2", "country_code": "US"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "Oracle Cloud Services" in resp.json()["detail"]


def test_create_oracle_region_duplicate_slug_conflicts(client, admin_headers, monkeypatch):
    asyncio.get_event_loop().run_until_complete(_enable_oracle_settings())

    async def fake_get_region_by_slug(slug):
        return object()  # any truthy value signals "exists"

    monkeypatch.setattr(main.region_service, "get_region_by_slug", fake_get_region_by_slug)

    resp = client.post(
        "/regions/oracle",
        json={"slug": "local", "display_name": "Whatever", "country_code": "US"},
        headers=admin_headers,
    )
    assert resp.status_code == 409


def test_create_oracle_region_launch_failure_returns_502_and_no_row(client, admin_headers, monkeypatch):
    asyncio.get_event_loop().run_until_complete(_enable_oracle_settings())

    async def fake_launch_fails(settings_row, display_name, wireguard_port):
        raise OracleProvisioningError("Oracle API error (LimitExceeded): out of host capacity")

    monkeypatch.setattr(main.oracle_service, "launch_oracle_instance", fake_launch_fails)

    resp = client.post(
        "/regions/oracle",
        json={"slug": "or-fail1", "display_name": "Will Fail", "country_code": "US"},
        headers=admin_headers,
    )
    assert resp.status_code == 502
    assert "out of host capacity" in resp.json()["detail"]

    list_resp = client.get("/regions", headers=admin_headers)
    assert not any(r["slug"] == "or-fail1" for r in list_resp.json())


def test_create_oracle_region_success_creates_provisioning_region(client, admin_headers, monkeypatch):
    asyncio.get_event_loop().run_until_complete(_enable_oracle_settings())

    async def fake_launch_ok(settings_row, display_name, wireguard_port):
        return ("ocid1.instance.oc1..fake", "203.0.113.42", "cafebabe" * 8)

    finish_calls = []

    async def fake_finish(region_id, slug, agent_url, agent_api_key):
        finish_calls.append((region_id, slug, agent_url, agent_api_key))

    monkeypatch.setattr(main.oracle_service, "launch_oracle_instance", fake_launch_ok)
    monkeypatch.setattr(main.oracle_service, "finish_provisioning", fake_finish)

    resp = client.post(
        "/regions/oracle",
        json={"slug": "or-success1", "display_name": "Oracle Success", "country_code": "US", "city": "Ashburn"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == "or-success1"
    assert body["health_status"] == "provisioning"
    assert body["is_active"] is False
    assert body["wireguard_endpoint_host"] == "203.0.113.42"
    assert body["agent_url"] == "https://203-0-113-42.sslip.io"
    assert body["oracle_instance_id"] == "ocid1.instance.oc1..fake"
    # The generated agent key must never appear in the response
    assert "cafebabe" not in resp.text


def test_finish_provisioning_marks_region_healthy_on_success(client, admin_headers, monkeypatch):
    async def make_region_and_check():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-finish-ok",
                display_name="Finish OK",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-1.sslip.io",
                wireguard_endpoint_host="198.51.100.1",
                is_active=False,
                health_status="provisioning",
                oracle_instance_id="ocid1.instance.oc1..finishok",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            region_id = region.id

        async def fake_wait_healthy(slug, agent_url, agent_key):
            return None

        monkeypatch.setattr(oracle_service, "_wait_for_agent_healthy", fake_wait_healthy)
        await oracle_service.finish_provisioning(region_id, "or-finish-ok", "https://198-51-100-1.sslip.io", "fakekey")

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "healthy"
            assert updated.is_active is True

    asyncio.get_event_loop().run_until_complete(make_region_and_check())


def test_delete_region_terminates_oracle_instance(client, admin_headers, monkeypatch):
    async def make_region():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-delete-test",
                display_name="Delete Test",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-3.sslip.io",
                wireguard_endpoint_host="198.51.100.3",
                is_active=True,
                health_status="healthy",
                oracle_instance_id="ocid1.instance.oc1..deleteme",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            return region.id

    region_id = asyncio.get_event_loop().run_until_complete(make_region())

    terminate_calls = []

    async def fake_terminate(settings_row, instance_id):
        terminate_calls.append(instance_id)

    monkeypatch.setattr(main.oracle_service, "terminate_instance", fake_terminate)

    resp = client.delete(f"/regions/{region_id}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert terminate_calls == ["ocid1.instance.oc1..deleteme"]

    get_resp = client.get("/regions", headers=admin_headers)
    assert not any(r["slug"] == "or-delete-test" for r in get_resp.json())


def test_delete_region_reports_termination_failure_but_still_deletes(client, admin_headers, monkeypatch):
    async def make_region():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-delete-fail-test",
                display_name="Delete Fail Test",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-4.sslip.io",
                wireguard_endpoint_host="198.51.100.4",
                is_active=True,
                health_status="healthy",
                oracle_instance_id="ocid1.instance.oc1..deletefail",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            return region.id

    region_id = asyncio.get_event_loop().run_until_complete(make_region())

    async def fake_terminate_fails(settings_row, instance_id):
        raise OracleProvisioningError("Oracle API error (NotAuthorized): not authorized")

    monkeypatch.setattr(main.oracle_service, "terminate_instance", fake_terminate_fails)

    resp = client.delete(f"/regions/{region_id}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert "could not terminate" in resp.json()["message"]

    get_resp = client.get("/regions", headers=admin_headers)
    assert not any(r["slug"] == "or-delete-fail-test" for r in get_resp.json())


def test_finish_provisioning_marks_region_failed_on_timeout(client, admin_headers, monkeypatch):
    async def make_region_and_check():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-finish-fail",
                display_name="Finish Fail",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-2.sslip.io",
                wireguard_endpoint_host="198.51.100.2",
                is_active=False,
                health_status="provisioning",
                oracle_instance_id="ocid1.instance.oc1..finishfail",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            region_id = region.id

        async def fake_wait_healthy_times_out(slug, agent_url, agent_key):
            raise OracleProvisioningError("Agent never came up within 15 minutes - last error: connection refused")

        monkeypatch.setattr(oracle_service, "_wait_for_agent_healthy", fake_wait_healthy_times_out)
        await oracle_service.finish_provisioning(region_id, "or-finish-fail", "https://198-51-100-2.sslip.io", "fakekey")

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "failed"
            assert updated.is_active is False
            assert "never came up" in updated.last_health_error

    asyncio.get_event_loop().run_until_complete(make_region_and_check())

"""Tests for Oracle Cloud region auto-provisioning (api/oracle_service.py,
POST /regions/oracle). Real OCI API calls are always mocked/monkeypatched
here - see oracle_service.py's module docstring for why the actual OCI
integration itself couldn't be exercised against a real account."""

import asyncio
from types import SimpleNamespace

import pytest

import main
import oracle_service
import region_service
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
    """Enabled but without full credentials - enough for the
    oracle_enabled gate, not enough to pass _require_oracle_config."""
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)
        s.oracle_enabled = True
        await session.commit()


async def _fully_configure_oracle_settings():
    """Enabled with full (fake) credentials - passes _require_oracle_config
    so tests can reach the actual provisioning call without hitting the
    synchronous fast-fail check first."""
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            s = SystemSettings(id=1)
            session.add(s)
        s.oracle_enabled = True
        s.oracle_tenancy_ocid = "ocid1.tenancy.oc1..faketenancy"
        s.oracle_user_ocid = "ocid1.user.oc1..fakeuser"
        s.oracle_fingerprint = "aa:bb:cc:dd:ee:ff"
        s.oracle_region = "us-ashburn-1"
        s.oracle_api_key_encrypted = region_service.encrypt_secret("fake-private-key-content")
        await session.commit()


async def _disable_oracle_settings():
    async with AsyncSessionLocal() as session:
        s = await session.get(SystemSettings, 1)
        if s is None:
            return
        s.oracle_enabled = False
        s.oracle_tenancy_ocid = None
        s.oracle_user_ocid = None
        s.oracle_fingerprint = None
        s.oracle_region = None
        s.oracle_api_key_encrypted = None
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


def test_create_oracle_region_missing_credentials_returns_400_and_no_row(client, admin_headers):
    asyncio.get_event_loop().run_until_complete(_enable_oracle_settings())  # enabled, but no creds

    resp = client.post(
        "/regions/oracle",
        json={"slug": "or-missingcreds", "display_name": "Missing Creds", "country_code": "US"},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "Tenancy OCID" in resp.json()["detail"]

    list_resp = client.get("/regions", headers=admin_headers)
    assert not any(r["slug"] == "or-missingcreds" for r in list_resp.json())


def test_create_oracle_region_returns_immediately_and_schedules_background_task(client, admin_headers, monkeypatch):
    """The route itself must never call into any real OCI API - it should
    return the instant it's created the placeholder row, scheduling the
    actual provisioning as a background task. This is the fix for the
    real production bug where the old synchronous version could run long
    enough to trip a reverse-proxy's own timeout (502) regardless of
    whether Oracle's API calls succeeded."""
    asyncio.get_event_loop().run_until_complete(_fully_configure_oracle_settings())

    scheduled_calls = []

    async def fake_provision(region_id, slug, display_name, wireguard_port, settings_row):
        scheduled_calls.append((region_id, slug, display_name, wireguard_port))

    monkeypatch.setattr(main.oracle_service, "provision_oracle_region", fake_provision)

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
    # Nothing is known yet - the background task fills these in later
    assert body["wireguard_endpoint_host"] == ""
    assert body["agent_url"] is None
    assert body["oracle_instance_id"] is None

    # asyncio.create_task schedules but doesn't guarantee execution before
    # the response returns - yield control once so it actually runs.
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert len(scheduled_calls) == 1
    assert scheduled_calls[0][1] == "or-success1"
    assert scheduled_calls[0][2] == "Oracle Success"


def test_provision_oracle_region_full_lifecycle_success(client, admin_headers, monkeypatch):
    """Exercises the actual provision_oracle_region function end to end
    (not the route) - network setup, image lookup, and instance launch
    are faked since there's no real Oracle account to test against, but
    the glue logic (setting agent_url/host/instance_id, then flipping to
    healthy) runs for real."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-lifecycle-ok",
                display_name="Lifecycle OK",
                country_code="US",
                is_local=False,
                wireguard_endpoint_host="",
                is_active=False,
                health_status="provisioning",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            region_id = region.id

        await _fully_configure_oracle_settings()
        async with AsyncSessionLocal() as session:
            settings_row = await session.get(SystemSettings, 1)

        async def fake_ensure_network(config, compartment_id):
            return "ocid1.vcn.oc1..fake", "ocid1.subnet.oc1..fake"

        async def fake_pick_ad(config, compartment_id):
            return "fake-AD-1"

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..fake"

        async def fake_wait_for_public_ip(config, compartment_id, instance_id):
            return "203.0.113.42"

        async def fake_wait_healthy(slug, agent_url, agent_key):
            return None

        class FakeComputeClient:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.instance.oc1..lifecycle"))

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_pick_availability_domain", fake_pick_ad)
        monkeypatch.setattr(oracle_service, "_pick_ubuntu_image", fake_pick_image)
        monkeypatch.setattr(oracle_service, "_wait_for_public_ip", fake_wait_for_public_ip)
        monkeypatch.setattr(oracle_service, "_wait_for_agent_healthy", fake_wait_healthy)
        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClient)

        await oracle_service.provision_oracle_region(region_id, "or-lifecycle-ok", "Lifecycle OK", 51820, settings_row)

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "healthy"
            assert updated.is_active is True
            assert updated.wireguard_endpoint_host == "203.0.113.42"
            assert updated.agent_url == "https://203-0-113-42.sslip.io"
            assert updated.oracle_instance_id == "ocid1.instance.oc1..lifecycle"

    asyncio.get_event_loop().run_until_complete(scenario())


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


def test_provision_oracle_region_marks_failed_when_agent_never_comes_up(client, admin_headers, monkeypatch):
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-lifecycle-timeout",
                display_name="Lifecycle Timeout",
                country_code="US",
                is_local=False,
                wireguard_endpoint_host="",
                is_active=False,
                health_status="provisioning",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            region_id = region.id

        await _fully_configure_oracle_settings()
        async with AsyncSessionLocal() as session:
            settings_row = await session.get(SystemSettings, 1)

        async def fake_ensure_network(config, compartment_id):
            return "ocid1.vcn.oc1..fake", "ocid1.subnet.oc1..fake"

        async def fake_pick_ad(config, compartment_id):
            return "fake-AD-1"

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..fake"

        async def fake_wait_for_public_ip(config, compartment_id, instance_id):
            return "198.51.100.2"

        async def fake_wait_healthy_times_out(slug, agent_url, agent_key):
            raise OracleProvisioningError("Agent never came up within 15 minutes - last error: connection refused")

        class FakeComputeClient:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.instance.oc1..timeout"))

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_pick_availability_domain", fake_pick_ad)
        monkeypatch.setattr(oracle_service, "_pick_ubuntu_image", fake_pick_image)
        monkeypatch.setattr(oracle_service, "_wait_for_public_ip", fake_wait_for_public_ip)
        monkeypatch.setattr(oracle_service, "_wait_for_agent_healthy", fake_wait_healthy_times_out)
        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClient)

        await oracle_service.provision_oracle_region(region_id, "or-lifecycle-timeout", "Lifecycle Timeout", 51820, settings_row)

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "failed"
            assert updated.is_active is False
            assert "never came up" in updated.last_health_error
            # It still got this far before failing - host/agent_url/instance
            # should be populated even though the overall result is a failure
            assert updated.wireguard_endpoint_host == "198.51.100.2"
            assert updated.oracle_instance_id == "ocid1.instance.oc1..timeout"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_provision_oracle_region_marks_failed_on_launch_error(client, admin_headers, monkeypatch):
    """A failure during the earlier, previously-synchronous phase
    (network/image/launch) - this used to surface as an HTTP 502 from
    the route itself; now it's caught inside the background task and
    recorded on the row instead."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-lifecycle-launchfail",
                display_name="Lifecycle Launch Fail",
                country_code="US",
                is_local=False,
                wireguard_endpoint_host="",
                is_active=False,
                health_status="provisioning",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            region_id = region.id

        await _fully_configure_oracle_settings()
        async with AsyncSessionLocal() as session:
            settings_row = await session.get(SystemSettings, 1)

        async def fake_ensure_network_fails(config, compartment_id):
            raise OracleProvisioningError("Oracle API error (LimitExceeded): out of host capacity")

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network_fails)

        await oracle_service.provision_oracle_region(region_id, "or-lifecycle-launchfail", "Lifecycle Launch Fail", 51820, settings_row)

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "failed"
            assert updated.is_active is False
            assert "out of host capacity" in updated.last_health_error
            # Never got far enough to have any of these
            assert updated.wireguard_endpoint_host == ""
            assert updated.oracle_instance_id is None

    asyncio.get_event_loop().run_until_complete(scenario())

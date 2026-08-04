"""Tests for Oracle Cloud region auto-provisioning (api/oracle_service.py,
POST /regions/oracle). Real OCI API calls are always mocked/monkeypatched
here - see oracle_service.py's module docstring for why the actual OCI
integration itself couldn't be exercised against a real account."""

import asyncio
import gc
from types import SimpleNamespace

import oci
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


def test_service_error_message_includes_operation_name():
    """A real production incident traced back to this exact gap: a
    NotAuthorizedOrNotFound with no indication of *which* OCI call
    failed (list_vcns? launch_instance?) made it impossible to tell a
    genuine permission gap from a wrong compartment/resource without
    pure guesswork. operation_name pinpoints it."""
    error_with_op = oci.exceptions.ServiceError(
        status=404, code="NotAuthorizedOrNotFound", headers={},
        message="Authorization failed or requested resource not found.",
        operation_name="list_vcns",
    )
    message = oracle_service._service_error_message(error_with_op)
    assert "list_vcns" in message
    assert "NotAuthorizedOrNotFound" in message
    assert "Authorization failed" in message

    error_without_op = oci.exceptions.ServiceError(
        status=401, code="NotAuthenticated", headers={}, message="Bad credentials.",
    )
    message_no_op = oracle_service._service_error_message(error_without_op)
    assert "NotAuthenticated" in message_no_op
    assert "[" not in message_no_op


def test_pick_ubuntu_image_picks_newest_matching_version(client, admin_headers, monkeypatch):
    """Pins to Ubuntu 24.04 specifically (operating_system_version filter)
    rather than trusting whatever list_images happens to return across
    all versions - untested "pick the latest, any version" logic is
    exactly the kind of thing that silently regresses when Oracle
    publishes a new image. See UBUNTU_VERSION's docstring for the real
    production history behind this choice: 24.04 Minimal wasn't
    available for this shape, 20.04 launched but is EOL and broke
    Docker's own installer, 24.04 (regular) is the current LTS with full
    package support and was already confirmed to have images available
    for this shape."""
    async def scenario():
        older_image = SimpleNamespace(
            id="ocid1.image.oc1..older",
            display_name="Canonical-Ubuntu-24.04-2025.06.01-0",
            time_created="2025-06-01T00:00:00Z",
        )
        newer_image = SimpleNamespace(
            id="ocid1.image.oc1..newer",
            display_name="Canonical-Ubuntu-24.04-2025.07.23-0",
            time_created="2025-07-23T00:00:00Z",
        )

        class FakeComputeClient:
            def __init__(self, config):
                pass

            def list_images(self, **kwargs):
                assert kwargs["operating_system_version"] == "24.04"
                return SimpleNamespace(data=[older_image, newer_image])

        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClient)
        image_id = await oracle_service._pick_ubuntu_image({}, "ocid1.tenancy.oc1..fake")
        assert image_id == "ocid1.image.oc1..newer"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_pick_ubuntu_image_raises_clear_error_when_none_available(client, admin_headers, monkeypatch):
    async def scenario():
        class FakeComputeClient:
            def __init__(self, config):
                pass

            def list_images(self, **kwargs):
                return SimpleNamespace(data=[])

        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClient)
        with pytest.raises(OracleProvisioningError, match="24.04"):
            await oracle_service._pick_ubuntu_image({}, "ocid1.tenancy.oc1..fake")

    asyncio.get_event_loop().run_until_complete(scenario())


def test_ensure_network_skips_subnet_that_prohibits_public_ips(client, admin_headers, monkeypatch):
    """Regression test for the actual root cause of a real production
    failure: an existing manually-created 'BartoloVCN' had a subnet with
    public IPs prohibited (a Console VCN Wizard default) - blindly
    reusing subnets[0] launched a real instance that Oracle then auto-
    terminated when VNIC creation failed ("Public IP addresses are
    prohibited in this subnet"). Must skip a prohibited subnet and
    create a working one instead of trusting whatever already exists."""
    async def scenario():
        vcn = SimpleNamespace(id="ocid1.vcn.oc1..existing")
        prohibited_subnet = SimpleNamespace(
            id="ocid1.subnet.oc1..prohibited",
            cidr_block="10.0.0.0/24",
            prohibit_public_ip_on_vnic=True,
            lifecycle_state="AVAILABLE",
        )
        igw = SimpleNamespace(id="ocid1.internetgateway.oc1..existing")
        route_table = SimpleNamespace(id="ocid1.routetable.oc1..default")
        security_list = SimpleNamespace(id="ocid1.securitylist.oc1..default")
        created_subnets = []

        class FakeVirtualNetworkClient:
            def __init__(self, config):
                pass

            def list_vcns(self, **kwargs):
                return SimpleNamespace(data=[vcn])

            def list_subnets(self, **kwargs):
                return SimpleNamespace(data=[prohibited_subnet])

            def list_internet_gateways(self, **kwargs):
                return SimpleNamespace(data=[igw])

            def list_route_tables(self, **kwargs):
                return SimpleNamespace(data=[route_table])

            def update_route_table(self, rt_id, details):
                return SimpleNamespace(data=route_table)

            def list_security_lists(self, **kwargs):
                return SimpleNamespace(data=[security_list])

            def update_security_list(self, sl_id, details):
                return SimpleNamespace(data=security_list)

            def create_subnet(self, details):
                # Must not reuse the prohibited subnet's CIDR - proves the
                # existing subnet's CIDR was actually excluded as a candidate.
                assert details.cidr_block != prohibited_subnet.cidr_block
                assert details.prohibit_public_ip_on_vnic is False
                created_subnets.append(details.cidr_block)
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.subnet.oc1..new"))

        monkeypatch.setattr(oracle_service.oci.core, "VirtualNetworkClient", FakeVirtualNetworkClient)
        vcn_id, subnet_id = await oracle_service._ensure_network({}, "ocid1.tenancy.oc1..fake")

        assert vcn_id == "ocid1.vcn.oc1..existing"
        assert subnet_id == "ocid1.subnet.oc1..new"
        assert len(created_subnets) == 1

    asyncio.get_event_loop().run_until_complete(scenario())


def test_fire_and_forget_task_survives_garbage_collection():
    """Regression test for a real production bug: asyncio.create_task()
    only keeps a *weak* reference to the returned Task internally - one
    with no other strong reference anywhere is eligible for garbage
    collection mid-execution, silently, with no error raised or logged.
    This is exactly what happened to a real Oracle region provisioning
    attempt: the background task vanished partway through, leaving the
    region row stuck forever showing neither success nor failure.
    fire_and_forget() must hold a strong reference via
    main._background_tasks so this can't happen again."""
    completed = []

    async def slow_coro():
        await asyncio.sleep(0)
        gc.collect()  # simulates a GC pass happening while the task is in flight
        await asyncio.sleep(0)
        completed.append(True)

    async def scenario():
        main.fire_and_forget(slow_coro())
        # Deliberately no other reference to the returned Task is kept
        # here - if fire_and_forget didn't hold one via _background_tasks,
        # the gc.collect() above could destroy the task before it finishes.
        for _ in range(10):
            await asyncio.sleep(0)

    asyncio.get_event_loop().run_until_complete(scenario())
    assert completed == [True]


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

        async def fake_list_ads(config, compartment_id):
            return ["fake-AD-1"]

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..fake"

        async def fake_wait_for_public_ip(config, compartment_id, instance_id):
            return "203.0.113.42"

        async def fake_wait_healthy(slug, agent_url, agent_key, on_attempt=None):
            return None

        class FakeComputeClient:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.instance.oc1..lifecycle"))

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_list_availability_domains", fake_list_ads)
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


def test_provision_oracle_region_retries_next_ad_when_first_rejects_launch(client, admin_headers, monkeypatch):
    """Regression test for the actual root cause found in production:
    Always Free shape capacity is unevenly distributed across a region's
    availability domains and shifts over time - a real tenancy had
    capacity in AD-3 but not AD-1, and picking only the first AD in the
    list made every attempt fail. Must try the rest before giving up,
    rather than hardcoding a specific AD (which wouldn't generalize to
    other operators' tenancies, or stay correct as capacity shifts)."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-lifecycle-adretry",
                display_name="Lifecycle AD Retry",
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

        async def fake_list_ads(config, compartment_id):
            return ["fake-AD-1", "fake-AD-2", "fake-AD-3"]

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..fake"

        async def fake_wait_for_public_ip(config, compartment_id, instance_id):
            return "203.0.113.77"

        async def fake_wait_healthy(slug, agent_url, agent_key, on_attempt=None):
            return None

        attempted_ads = []

        class FakeComputeClientRejectsFirstTwo:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                attempted_ads.append(details.availability_domain)
                if details.availability_domain != "fake-AD-3":
                    raise oci.exceptions.ServiceError(
                        status=404, code="NotAuthorizedOrNotFound", headers={},
                        message="Authorization failed or requested resource not found.",
                        operation_name="launch_instance",
                    )
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.instance.oc1..adretry"))

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_list_availability_domains", fake_list_ads)
        monkeypatch.setattr(oracle_service, "_pick_ubuntu_image", fake_pick_image)
        monkeypatch.setattr(oracle_service, "_wait_for_public_ip", fake_wait_for_public_ip)
        monkeypatch.setattr(oracle_service, "_wait_for_agent_healthy", fake_wait_healthy)
        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClientRejectsFirstTwo)

        await oracle_service.provision_oracle_region(region_id, "or-lifecycle-adretry", "Lifecycle AD Retry", 51820, settings_row)

        # Tried AD-1 and AD-2 (both rejected) before succeeding on AD-3
        assert attempted_ads == ["fake-AD-1", "fake-AD-2", "fake-AD-3"]

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "healthy"
            assert updated.is_active is True
            assert updated.oracle_instance_id == "ocid1.instance.oc1..adretry"

    asyncio.get_event_loop().run_until_complete(scenario())


def test_health_check_rejects_region_with_no_agent_instead_of_clobbering_error(client, admin_headers):
    """Regression test for a real production bug: manually clicking Check
    on a region that failed to provision (so it never got an agent_url)
    silently overwrote the real, useful error (e.g. an actual Oracle
    NotAuthenticated message) with a generic, useless "no agent
    configured" message - destroying the actual diagnostic info."""
    async def make_region():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-noagent",
                display_name="No Agent Yet",
                country_code="US",
                is_local=False,
                agent_url=None,
                wireguard_endpoint_host="",
                is_active=False,
                health_status="failed",
                last_health_error="Oracle API error (NotAuthenticated): the real, useful error",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            return region.id

    region_id = asyncio.get_event_loop().run_until_complete(make_region())

    resp = client.post(f"/regions/{region_id}/health-check", headers=admin_headers)
    assert resp.status_code == 400
    assert "still provisioning or failed" in resp.json()["detail"]

    # The original, informative error must survive untouched
    get_resp = client.get("/regions", headers=admin_headers)
    region_data = next(r for r in get_resp.json() if r["slug"] == "or-noagent")
    assert region_data["health_status"] == "failed"
    assert "NotAuthenticated" in region_data["last_health_error"]


def test_health_check_rejects_region_still_provisioning(client, admin_headers):
    """Regression test: a manual Check while the background provisioning
    task is still actively polling races it - both write health_status/
    last_health_error on the same row with no coordination, so a manual
    check could flip "provisioning" to "unreachable" moments before the
    background task would have flipped it to "healthy" on its own,
    making an actively-working provision look broken."""
    async def make_region():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-still-provisioning",
                display_name="Still Provisioning",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-9.sslip.io",
                wireguard_endpoint_host="198.51.100.9",
                is_active=False,
                health_status="provisioning",
                oracle_instance_id="ocid1.instance.oc1..stillprovisioning",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)
            return region.id

    region_id = asyncio.get_event_loop().run_until_complete(make_region())

    resp = client.post(f"/regions/{region_id}/health-check", headers=admin_headers)
    assert resp.status_code == 400
    assert "actively checking" in resp.json()["detail"]

    # Status must be untouched by the rejected manual check
    get_resp = client.get("/regions", headers=admin_headers)
    region_data = next(r for r in get_resp.json() if r["slug"] == "or-still-provisioning")
    assert region_data["health_status"] == "provisioning"


def test_health_check_reports_real_oracle_state_when_terminated(client, admin_headers, monkeypatch):
    """Regression test for the actual real-world bug reported: a failed
    HTTP ping to the agent alone can't distinguish "instance is fine,
    agent is just slow/mid-build" from "the instance itself is actually
    gone" - it just says "unreachable" either way, which is a guess, not
    a real check. Oracle's own reported instance state is authoritative;
    when it says the instance is gone, that must be what's reported."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-terminated-check",
                display_name="Terminated Check",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-10.sslip.io",
                agent_key_encrypted=region_service.encrypt_agent_key("fakekey"),
                wireguard_endpoint_host="198.51.100.10",
                is_active=True,
                health_status="healthy",
                oracle_instance_id="ocid1.instance.oc1..wasrunning",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)

        await _fully_configure_oracle_settings()

        async def fake_get_instance_state(settings_row, instance_id):
            assert instance_id == "ocid1.instance.oc1..wasrunning"
            return "TERMINATED"

        monkeypatch.setattr(oracle_service, "get_instance_state", fake_get_instance_state)

        updated = await region_service.health_check_region(region)
        assert updated.health_status == "unreachable"
        assert "TERMINATED" in updated.last_health_error

    asyncio.get_event_loop().run_until_complete(scenario())


def test_health_check_notes_real_running_state_when_agent_unreachable(client, admin_headers, monkeypatch):
    """When Oracle confirms RUNNING but the agent still isn't answering
    (e.g. mid docker-compose-build), the error must say so - not just a
    bare "unreachable" that reads identically to a genuinely dead VM."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-running-agent-down",
                display_name="Running Agent Down",
                country_code="US",
                is_local=False,
                agent_url="https://198-51-100-11.sslip.io",
                agent_key_encrypted=region_service.encrypt_agent_key("fakekey"),
                wireguard_endpoint_host="198.51.100.11",
                is_active=True,
                health_status="healthy",
                oracle_instance_id="ocid1.instance.oc1..stillbuilding",
            )
            session.add(region)
            await session.commit()
            await session.refresh(region)

        await _fully_configure_oracle_settings()

        async def fake_get_instance_state(settings_row, instance_id):
            return "RUNNING"

        async def fake_client_health_fails(self):
            raise Exception("Connection refused")

        monkeypatch.setattr(oracle_service, "get_instance_state", fake_get_instance_state)
        monkeypatch.setattr(region_service.RegionClient, "health", fake_client_health_fails)

        updated = await region_service.health_check_region(region)
        assert updated.health_status == "unreachable"
        assert "RUNNING" in updated.last_health_error
        assert "Connection refused" in updated.last_health_error

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

        async def fake_list_ads(config, compartment_id):
            return ["fake-AD-1"]

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..fake"

        async def fake_wait_for_public_ip(config, compartment_id, instance_id):
            return "198.51.100.2"

        async def fake_wait_healthy_times_out(slug, agent_url, agent_key, on_attempt=None):
            raise OracleProvisioningError("Agent never came up within 15 minutes - last error: connection refused")

        class FakeComputeClient:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.instance.oc1..timeout"))

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_list_availability_domains", fake_list_ads)
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


def test_provision_oracle_region_records_instance_id_even_if_public_ip_wait_fails(client, admin_headers, monkeypatch):
    """Regression test for the actual real-world incident: launch_instance
    succeeded (a real Oracle instance now exists and is running), but
    _wait_for_public_ip itself failed/timed out before oracle_instance_id
    was ever saved - with no ID recorded anywhere, that instance became
    permanently untrackable and undeletable via the dashboard. Every
    retry created another one, silently exhausting the tenant's entire
    Always Free instance quota after just two failed attempts. The ID
    must be saved the moment the instance exists, not after later steps
    also succeed."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-lifecycle-ipwaitfail",
                display_name="Lifecycle IP Wait Fail",
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

        async def fake_list_ads(config, compartment_id):
            return ["fake-AD-1"]

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..fake"

        async def fake_wait_for_public_ip_times_out(config, compartment_id, instance_id):
            raise OracleProvisioningError("Instance launched but no public IP appeared within 180s")

        class FakeComputeClient:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                return SimpleNamespace(data=SimpleNamespace(id="ocid1.instance.oc1..orphanwatch"))

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_list_availability_domains", fake_list_ads)
        monkeypatch.setattr(oracle_service, "_pick_ubuntu_image", fake_pick_image)
        monkeypatch.setattr(oracle_service, "_wait_for_public_ip", fake_wait_for_public_ip_times_out)
        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClient)

        await oracle_service.provision_oracle_region(region_id, "or-lifecycle-ipwaitfail", "Lifecycle IP Wait Fail", 51820, settings_row)

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "failed"
            # The critical assertion: even though everything after launch
            # failed, the real instance's ID must still be recorded so
            # DELETE /regions can actually find and terminate it.
            assert updated.oracle_instance_id == "ocid1.instance.oc1..orphanwatch"

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


def test_provision_oracle_region_launch_instance_error_includes_diagnostic_params(client, admin_headers, monkeypatch):
    """Regression test: a NotAuthorizedOrNotFound from launch_instance
    specifically is genuinely ambiguous between "no permission" and "one
    of these IDs doesn't exist" - this bit a real production attempt
    where the operator had full tenancy admin (confirmed via the actual
    OCI policy statement) yet launch_instance still failed. Without the
    exact AD/image/subnet values used, diagnosing that requires guessing
    or fetching container logs separately; they must be in the stored
    error itself."""
    async def scenario():
        async with AsyncSessionLocal() as session:
            region = Region(
                slug="or-lifecycle-launcherror",
                display_name="Lifecycle Launch Error",
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
            return "ocid1.vcn.oc1..fake", "ocid1.subnet.oc1..diagnostictest"

        async def fake_list_ads(config, compartment_id):
            return ["fake-AD-2"]

        async def fake_pick_image(config, compartment_id):
            return "ocid1.image.oc1..diagnostictest"

        class FakeComputeClientLaunchFails:
            def __init__(self, config):
                pass

            def launch_instance(self, details):
                raise oci.exceptions.ServiceError(
                    status=404, code="NotAuthorizedOrNotFound", headers={},
                    message="Authorization failed or requested resource not found.",
                    operation_name="launch_instance",
                )

        monkeypatch.setattr(oracle_service, "_ensure_network", fake_ensure_network)
        monkeypatch.setattr(oracle_service, "_list_availability_domains", fake_list_ads)
        monkeypatch.setattr(oracle_service, "_pick_ubuntu_image", fake_pick_image)
        monkeypatch.setattr(oracle_service.oci.core, "ComputeClient", FakeComputeClientLaunchFails)

        await oracle_service.provision_oracle_region(region_id, "or-lifecycle-launcherror", "Lifecycle Launch Error", 51820, settings_row)

        async with AsyncSessionLocal() as session:
            updated = await session.get(Region, region_id)
            assert updated.health_status == "failed"
            assert "launch_instance" in updated.last_health_error
            assert "fake-AD-2" in updated.last_health_error
            assert "ocid1.image.oc1..diagnostictest" in updated.last_health_error
            assert "ocid1.subnet.oc1..diagnostictest" in updated.last_health_error

    asyncio.get_event_loop().run_until_complete(scenario())

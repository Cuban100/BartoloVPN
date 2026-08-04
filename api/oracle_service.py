#!/usr/bin/env python3
"""
Oracle Cloud (OCI) region auto-provisioning: creates a real Compute
instance via Oracle's API using the credentials stored in Settings, and
boots it into a working BartoloVPN region with zero manual SSH - the
dashboard-driven counterpart to the manual scripts/provision-region.sh
flow (that script is still what generate_cloud_init's steps are adapted
from, minus the prompts and its own dashboard-registration dance, since
here the dashboard polls the agent itself after launch instead).

Verification note: unlike the rest of this codebase, the actual OCI API
calls here have not been exercised against a real Oracle account (no
sandboxed OCI access available) - the exact method/model signatures were
checked against the installed oci==2.184.0 package directly (not just
recalled), and error handling is deliberately generous so a real failure
surfaces a clear message instead of a silent crash, but review carefully
against real usage the first time.
"""

import asyncio
import logging
import secrets
from datetime import datetime
from typing import Optional, Tuple

import oci
from sqlalchemy import select

import region_service
from database import AsyncSessionLocal, Region, SystemSettings
from region_client import RegionClient

logger = logging.getLogger(__name__)

# AMD-based Always Free shape - chosen over VM.Standard.A1.Flex (Ampere,
# also Always Free but far more prone to "out of host capacity" errors in
# practice, per this operator's own repeated manual Oracle Cloud attempts
# earlier this session).
ORACLE_SHAPE = "VM.Standard.E2.1.Micro"

VCN_DISPLAY_NAME = "BartoloVCN"
SUBNET_DISPLAY_NAME = "BartoloVPN Public Subnet"
VCN_CIDR = "10.0.0.0/16"
SUBNET_CIDR = "10.0.0.0/24"

GITHUB_REPO_URL = "https://github.com/Cuban100/BartoloVPN.git"

# How long to wait for the instance's public IP to appear after launch,
# and separately for the agent to report healthy after that (cloud-init
# has to install Docker, clone the repo, build images, and get a real
# Let's Encrypt cert - this genuinely takes several minutes).
PUBLIC_IP_TIMEOUT_SECONDS = 180
AGENT_HEALTHY_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 15


class OracleProvisioningError(Exception):
    """Raised for any failure during Oracle provisioning. Message is
    always safe to show directly to the operator - never includes key
    material."""


def _require_oracle_config(s: SystemSettings) -> None:
    missing = [
        name for name, value in (
            ("Tenancy OCID", s.oracle_tenancy_ocid),
            ("User OCID", s.oracle_user_ocid),
            ("API Key Fingerprint", s.oracle_fingerprint),
            ("API Signing Key", s.oracle_api_key_encrypted),
            ("Home Region", s.oracle_region),
        ) if not value
    ]
    if missing:
        raise OracleProvisioningError(
            f"Oracle Cloud isn't fully configured in Settings - missing: {', '.join(missing)}"
        )


def build_oci_config(s: SystemSettings) -> dict:
    private_key_pem = region_service.decrypt_secret(s.oracle_api_key_encrypted)
    return {
        "user": s.oracle_user_ocid,
        "fingerprint": s.oracle_fingerprint,
        "tenancy": s.oracle_tenancy_ocid,
        "region": s.oracle_region,
        "key_content": private_key_pem,
    }


def _read_ssh_public_key(key_name: Optional[str]) -> Optional[str]:
    """SSH access is never required by BartoloVPN itself (the dashboard
    only ever talks to the agent over HTTPS) - this is purely a courtesy
    for the operator to have emergency shell access to a box they didn't
    manually create. Missing/unset is not an error."""
    if not key_name:
        return None
    path = f"/ssh-keys/{key_name}.pub"
    try:
        with open(path) as f:
            content = f.read().strip()
            return content or None
    except FileNotFoundError:
        logger.warning(f"Configured SSH key '{key_name}' not found at {path} - launching without one")
        return None


def generate_cloud_init(agent_api_key: str, wireguard_port: int) -> str:
    """Non-interactive counterpart to scripts/provision-region.sh's
    box-setup steps (Docker install, .env, firewall, docker compose up) -
    no prompts, and deliberately no dashboard auto-registration logic:
    the dashboard polls the freshly-booted agent itself (see
    _wait_for_agent_healthy below) instead of embedding any dashboard
    credentials into this script, so nothing sensitive beyond the agent's
    own key (which the agent needs regardless) ever reaches this VM."""
    return f"""#!/bin/bash
set -e
exec > /var/log/bartolovpn-provision.log 2>&1
echo "BartoloVPN region provisioning started: $(date -u)"

apt-get update -qq
apt-get install -y -qq docker.io docker-compose-plugin ufw curl git
systemctl enable --now docker

git clone --depth 1 {GITHUB_REPO_URL} /opt/bartolovpn
cd /opt/bartolovpn/region-agent

SERVER_IP=$(curl -s --max-time 10 ifconfig.me)
AGENT_HOSTNAME="${{SERVER_IP//./-}}.sslip.io"

cat > .env <<ENVEOF
AGENT_API_KEY={agent_api_key}
SERVER_IP=$SERVER_IP
WIREGUARD_PORT={wireguard_port}
WIREGUARD_SUBNET=10.13.13.0
AGENT_HOSTNAME=$AGENT_HOSTNAME
ENVEOF
chmod 600 .env

ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow {wireguard_port}/udp
ufw --force enable

# Oracle's stock Ubuntu images ship pre-existing iptables ACCEPT-SSH-only
# rules ahead of ufw's own chains - insert explicit ACCEPT rules at the
# top of INPUT so ufw's rules actually get reached (see
# scripts/provision-region.sh's interactive-flow equivalent of this).
if command -v iptables >/dev/null 2>&1; then
    iptables -I INPUT 1 -p udp --dport {wireguard_port} -j ACCEPT
    iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
    iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
    command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save || true
fi

docker compose up -d --build

echo "BartoloVPN region provisioning finished: $(date -u)"
touch /var/log/bartolovpn-provision-complete
"""


async def _run_sync(fn, *args, **kwargs):
    """OCI's SDK is synchronous - runs it off the event loop thread so a
    slow Oracle API call doesn't block the whole app."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _service_error_message(e: "oci.exceptions.ServiceError") -> str:
    # operation_name pinpoints exactly which OCI call failed (list_vcns vs
    # launch_instance vs get_availability_domains, etc.) - without it a
    # NotAuthorizedOrNotFound only says "something was denied," with no
    # way to tell whether that's a genuine permission gap or the wrong
    # compartment/resource, forcing pure guesswork to diagnose.
    op = f" [{e.operation_name}]" if getattr(e, "operation_name", None) else ""
    return f"Oracle API error ({e.code}){op}: {e.message}"


async def _ensure_network(config: dict, compartment_id: str) -> Tuple[str, str]:
    """Returns (vcn_id, subnet_id), creating a VCN/subnet/gateway if a
    'BartoloVCN' doesn't already exist, and opens SSH/80/443/WireGuard
    ingress on the default security list - the exact "second firewall"
    step that repeatedly tripped up manual Oracle setup this session (see
    [[oracle_free_tier_signup_troubleshooting]] memory) - so it never
    needs a manual OCI Console step for auto-provisioned regions."""
    vnet = oci.core.VirtualNetworkClient(config)

    existing = (await _run_sync(vnet.list_vcns, compartment_id=compartment_id, display_name=VCN_DISPLAY_NAME)).data
    if existing:
        vcn = existing[0]
        subnets = (await _run_sync(vnet.list_subnets, compartment_id=compartment_id, vcn_id=vcn.id)).data
        if subnets:
            return vcn.id, subnets[0].id
    else:
        vcn = (await _run_sync(
            vnet.create_vcn,
            oci.core.models.CreateVcnDetails(
                compartment_id=compartment_id,
                display_name=VCN_DISPLAY_NAME,
                cidr_block=VCN_CIDR,
            ),
        )).data

    igw = (await _run_sync(
        vnet.create_internet_gateway,
        oci.core.models.CreateInternetGatewayDetails(
            compartment_id=compartment_id,
            vcn_id=vcn.id,
            display_name="BartoloVPN Internet Gateway",
            is_enabled=True,
        ),
    )).data

    route_tables = (await _run_sync(vnet.list_route_tables, compartment_id=compartment_id, vcn_id=vcn.id)).data
    default_rt = route_tables[0]
    await _run_sync(
        vnet.update_route_table,
        default_rt.id,
        oci.core.models.UpdateRouteTableDetails(
            route_rules=[
                oci.core.models.RouteRule(
                    network_entity_id=igw.id,
                    destination="0.0.0.0/0",
                    destination_type="CIDR_BLOCK",
                )
            ]
        ),
    )

    security_lists = (await _run_sync(vnet.list_security_lists, compartment_id=compartment_id, vcn_id=vcn.id)).data
    default_sl = security_lists[0]
    tcp_ports = [22, 80, 443]
    ingress_rules = [
        oci.core.models.IngressSecurityRule(
            protocol="6",  # TCP
            source="0.0.0.0/0",
            source_type="CIDR_BLOCK",
            tcp_options=oci.core.models.TcpOptions(
                destination_port_range=oci.core.models.PortRange(min=p, max=p)
            ),
        )
        for p in tcp_ports
    ]
    ingress_rules.append(
        oci.core.models.IngressSecurityRule(
            protocol="17",  # UDP
            source="0.0.0.0/0",
            source_type="CIDR_BLOCK",
            udp_options=oci.core.models.UdpOptions(
                destination_port_range=oci.core.models.PortRange(min=51820, max=51820)
            ),
        )
    )
    await _run_sync(
        vnet.update_security_list,
        default_sl.id,
        oci.core.models.UpdateSecurityListDetails(ingress_security_rules=ingress_rules),
    )

    subnet = (await _run_sync(
        vnet.create_subnet,
        oci.core.models.CreateSubnetDetails(
            compartment_id=compartment_id,
            vcn_id=vcn.id,
            display_name=SUBNET_DISPLAY_NAME,
            cidr_block=SUBNET_CIDR,
            route_table_id=default_rt.id,
            security_list_ids=[default_sl.id],
            prohibit_public_ip_on_vnic=False,
        ),
    )).data
    return vcn.id, subnet.id


async def _list_availability_domains(config: dict, compartment_id: str) -> list:
    """Returns all AD names, not just one - Always Free shape capacity is
    unevenly distributed across a region's ADs and shifts over time, so
    launch_instance needs to be able to try more than the first one (see
    provision_oracle_region's launch loop). Confirmed in production: a
    real tenancy had capacity in AD-3 but not AD-1, and picking only the
    first AD caused every attempt to fail with a misleadingly generic
    NotAuthorizedOrNotFound instead of a capacity-specific error."""
    identity = oci.identity.IdentityClient(config)
    ads = (await _run_sync(identity.list_availability_domains, compartment_id=compartment_id)).data
    if not ads:
        raise OracleProvisioningError("Oracle returned no availability domains for this region")
    return [ad.name for ad in ads]


UBUNTU_VERSION = "20.04"

async def _pick_ubuntu_image(config: dict, compartment_id: str) -> str:
    """Pins to Ubuntu 20.04 specifically, rather than whatever happens to
    be the most-recently-published Canonical Ubuntu image for the shape
    - "newest wins" was untested and could just as easily land on a
    variant that behaves differently from the one actually verified to
    work. 24.04 Minimal was tried first and confirmed NOT available for
    VM.Standard.E2.1.Micro in a real tenancy (Minimal images are mainly
    published for newer flex/Ampere shapes) - 20.04 (non-Minimal) is
    what the operator's own manual, confirmed-working Console launch
    actually used for this exact shape."""
    compute = oci.core.ComputeClient(config)
    images = (await _run_sync(
        compute.list_images,
        compartment_id=compartment_id,
        operating_system="Canonical Ubuntu",
        operating_system_version=UBUNTU_VERSION,
        shape=ORACLE_SHAPE,
        lifecycle_state="AVAILABLE",
    )).data
    if not images:
        raise OracleProvisioningError(
            f"No available 'Canonical Ubuntu {UBUNTU_VERSION}' image found for shape {ORACLE_SHAPE} in this region"
        )
    images.sort(key=lambda img: img.time_created, reverse=True)
    return images[0].id


async def terminate_instance(settings_row: SystemSettings, instance_id: str) -> None:
    """Best-effort - called from DELETE /regions when the row being
    removed was Oracle-provisioned (region.oracle_instance_id set), so the
    dashboard "delete" doesn't silently orphan a real running instance.
    Raises OracleProvisioningError on failure; callers should log and
    continue rather than block the DB deletion on this, since the
    operator can always terminate manually via the OCI Console as a
    fallback."""
    config = build_oci_config(settings_row)
    compute = oci.core.ComputeClient(config)
    try:
        await _run_sync(compute.terminate_instance, instance_id)
    except oci.exceptions.ServiceError as e:
        raise OracleProvisioningError(_service_error_message(e))


async def _wait_for_public_ip(config: dict, compartment_id: str, instance_id: str) -> str:
    compute = oci.core.ComputeClient(config)
    vnet = oci.core.VirtualNetworkClient(config)
    deadline = asyncio.get_event_loop().time() + PUBLIC_IP_TIMEOUT_SECONDS
    while asyncio.get_event_loop().time() < deadline:
        attachments = (await _run_sync(
            compute.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance_id
        )).data
        for attachment in attachments:
            if attachment.lifecycle_state != "ATTACHED":
                continue
            vnic = (await _run_sync(vnet.get_vnic, attachment.vnic_id)).data
            if vnic.public_ip:
                return vnic.public_ip
        await asyncio.sleep(10)
    raise OracleProvisioningError(
        f"Instance launched but no public IP appeared within {PUBLIC_IP_TIMEOUT_SECONDS}s"
    )


async def _wait_for_agent_healthy(slug: str, agent_url: str, agent_key: str) -> None:
    """Polls the freshly-booted agent's /health until it responds - this
    is expected to take several minutes (Docker install, git clone, image
    build, first Let's Encrypt cert), so connection failures during that
    window are normal, not fatal, right up until the timeout."""
    client = RegionClient(slug, agent_url, agent_key, timeout_seconds=10.0)
    deadline = asyncio.get_event_loop().time() + AGENT_HEALTHY_TIMEOUT_SECONDS
    last_error = "unknown error"
    while asyncio.get_event_loop().time() < deadline:
        try:
            await client.health()
            return
        except Exception as e:
            last_error = str(e)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise OracleProvisioningError(
        f"Agent never came up within {AGENT_HEALTHY_TIMEOUT_SECONDS // 60} minutes - "
        f"last error: {last_error}. Check /var/log/bartolovpn-provision.log on the instance."
    )


def _b64(text: str) -> str:
    import base64
    return base64.b64encode(text.encode()).decode()


async def provision_oracle_region(
    region_id: int,
    slug: str,
    display_name: str,
    wireguard_port: int,
    settings_row: SystemSettings,
) -> None:
    """The entire Oracle provisioning lifecycle - network setup, image
    lookup, instance launch, waiting for a public IP, then waiting for
    the agent to report healthy - run as a single detached background
    task via asyncio.create_task from POST /regions/oracle.

    This used to be split into a synchronous "launch" phase (in the
    request/response cycle) and a backgrounded "finish" phase (just the
    health wait) - moved fully into the background after a real
    production failure: the network setup + launch + public-IP wait
    alone can take long enough that a reverse-proxy/CDN in front of the
    app (Cloudflare, haproxy) returns its own 502 before this function
    would have returned, regardless of whether the underlying Oracle
    calls actually succeeded. The route now returns immediately after
    creating a "provisioning" Region row; this function updates that row
    in place as it progresses, and the frontend polls for the result."""
    async def _set_fields(**fields) -> None:
        async with AsyncSessionLocal() as session:
            region = await session.get(Region, region_id)
            if region is None:
                return
            for key, value in fields.items():
                setattr(region, key, value)
            region.last_health_check = datetime.utcnow()
            await session.commit()

    try:
        config = build_oci_config(settings_row)
        compartment_id = settings_row.oracle_tenancy_ocid  # root compartment

        vcn_id, subnet_id = await _ensure_network(config, compartment_id)
        availability_domains = await _list_availability_domains(config, compartment_id)
        image_id = await _pick_ubuntu_image(config, compartment_id)

        agent_api_key = secrets.token_hex(32)
        ssh_public_key = _read_ssh_public_key(settings_row.oracle_ssh_key_name)
        metadata = {"user_data": _b64(generate_cloud_init(agent_api_key, wireguard_port))}
        if ssh_public_key:
            metadata["ssh_authorized_keys"] = ssh_public_key

        compute = oci.core.ComputeClient(config)
        instance_id = None
        launch_errors = []
        for availability_domain in availability_domains:
            logger.info(
                f"Oracle region '{slug}': trying to launch in "
                f"availability_domain={availability_domain!r} shape={ORACLE_SHAPE} "
                f"image_id={image_id} subnet_id={subnet_id}"
            )
            try:
                launch_response = await _run_sync(
                    compute.launch_instance,
                    oci.core.models.LaunchInstanceDetails(
                        compartment_id=compartment_id,
                        availability_domain=availability_domain,
                        shape=ORACLE_SHAPE,
                        display_name=display_name,
                        source_details=oci.core.models.InstanceSourceViaImageDetails(
                            source_type="image",
                            image_id=image_id,
                        ),
                        create_vnic_details=oci.core.models.CreateVnicDetails(
                            subnet_id=subnet_id,
                            assign_public_ip=True,
                        ),
                        metadata=metadata,
                    ),
                )
                instance_id = launch_response.data.id
                break
            except oci.exceptions.ServiceError as e:
                # Always Free shape capacity is unevenly distributed across
                # a region's ADs and shifts over time - confirmed in
                # production that the first AD in the list can reject a
                # launch (as a generic NotAuthorizedOrNotFound, not even a
                # capacity-specific error) while a later one succeeds with
                # the exact same image/subnet/shape. Try the rest before
                # giving up, rather than failing on the first rejection.
                launch_errors.append(f"{availability_domain}: {_service_error_message(e)}")
                continue

        if instance_id is None:
            raise OracleProvisioningError(
                f"Instance launch was rejected in every availability domain tried "
                f"(shape={ORACLE_SHAPE}, image_id={image_id}, subnet_id={subnet_id}): "
                + "; ".join(launch_errors)
            )

        # Record the instance ID the moment it exists, before anything else
        # that could fail (waiting for a public IP, waiting for the agent).
        # A real production incident: this used to only get saved after
        # _wait_for_public_ip also succeeded, so a timeout there left a
        # real, running, quota-consuming Oracle instance with literally no
        # record of its ID anywhere - undeletable via the dashboard, and
        # every retry created another one, silently exhausting the tenant's
        # entire Always Free instance quota (2 cores) after just two failed
        # attempts, which then made every subsequent attempt fail too.
        await _set_fields(oracle_instance_id=instance_id)

        public_ip = await _wait_for_public_ip(config, compartment_id, instance_id)
        agent_url = f"https://{public_ip.replace('.', '-')}.sslip.io"

        await _set_fields(
            wireguard_endpoint_host=public_ip,
            agent_url=agent_url,
            agent_key_encrypted=region_service.encrypt_agent_key(agent_api_key),
        )

        await _wait_for_agent_healthy(slug, agent_url, agent_api_key)
        await _set_fields(health_status="healthy", is_active=True, last_health_error=None)
        logger.info(f"Oracle region '{slug}' finished provisioning and is now active")

    except oci.exceptions.ServiceError as e:
        message = _service_error_message(e)
        await _set_fields(health_status="failed", last_health_error=message)
        logger.warning(f"Oracle region '{slug}' failed to provision: {message}")
    except OracleProvisioningError as e:
        await _set_fields(health_status="failed", last_health_error=str(e))
        logger.warning(f"Oracle region '{slug}' failed to provision: {e}")
    except Exception as e:
        await _set_fields(health_status="failed", last_health_error=f"Unexpected error: {e}")
        logger.exception(f"Oracle region '{slug}' provisioning hit an unexpected error")

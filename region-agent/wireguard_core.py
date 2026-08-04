#!/usr/bin/env python3
"""
WireGuard peer lifecycle for a single region agent.

Copied from BartoloVPN's api/main.py VPNManager class (the WireGuard-only
methods) as of the multi-region feature build. This is an intentional
fork, not a mistake or drift: the central dashboard's local/default region
keeps using the original code in api/main.py untouched, while every
additional region runs this copy on its own VPS. If a bug is fixed in one,
check whether the same fix applies to the other.

Every method here assumes it's running with the same network namespace as
this box's own `wireguard` container (network_mode: "service:wireguard" in
docker-compose.yml), exactly like vpn-api does for the local server today.
"""

import os
import re
import asyncio
import base64
import subprocess
from io import BytesIO
from typing import List, Optional, Dict, Any

import qrcode
from fastapi import HTTPException

from config import settings  # type: ignore  # Pylance: namespace collision with config dir


class WireGuardCore:
    """Manages WireGuard peers on this box only."""

    def __init__(self):
        # Serializes peer add/remove so IP allocation and wg_confs/wg0.conf
        # edits can't race each other.
        self.wireguard_peer_lock = asyncio.Lock()

    async def _get_wireguard_server_public_key(self) -> str:
        """The server's public key, read live from the running interface.

        This must never come from a separately-tracked file: wg0's actual
        private key lives in wg_confs/wg0.conf (owned by the wireguard
        container's own init scripts), and any app-side copy of "the server
        key" can silently drift from it (e.g. after the wireguard container
        regenerates its identity). Reading it live guarantees client configs
        always embed whatever key the interface is actually using right now.
        """
        result = await asyncio.create_subprocess_exec(
            'wg', 'show', 'wg0', 'public-key',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        public_key = stdout.decode().strip()
        if result.returncode != 0 or not public_key or public_key == "(none)":
            raise HTTPException(status_code=503, detail=f"Could not read live WireGuard server key: {stderr.decode().strip()}")
        return public_key

    async def get_wireguard_peer_stats(self) -> List[Dict[str, Any]]:
        """Real per-peer stats straight from the kernel (wg show wg0 dump),
        with peer names resolved from the app-managed peer conf files."""
        peers_dir = f"{settings.wireguard_config_path}/peers"
        ip_to_name = {}
        prefix = settings.wireguard_subnet_prefix
        if os.path.exists(peers_dir):
            for fname in os.listdir(peers_dir):
                if fname.endswith('.conf'):
                    with open(os.path.join(peers_dir, fname), 'r') as f:
                        content = f.read()
                    if f'Address = {prefix}.' in content:
                        ip_suffix = content.split(f'Address = {prefix}.')[1].split('/')[0].strip()
                        ip_to_name[f"{prefix}.{ip_suffix}"] = fname[:-5]

        result = await asyncio.create_subprocess_exec(
            'wg', 'show', 'wg0', 'dump',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await result.communicate()
        if result.returncode != 0:
            return []

        lines = stdout.decode().splitlines()
        peers = []
        # First line is the interface itself (private key, public key,
        # listen port, fwmark) - only [Peer] lines have 8 fields.
        for line in lines[1:]:
            parts = line.split('\t')
            if len(parts) < 8:
                continue
            public_key, _psk, _endpoint, allowed_ips, latest_handshake, rx, tx, _keepalive = parts
            ip = allowed_ips.split('/')[0] if allowed_ips else None
            peers.append({
                'public_key': public_key,
                'name': ip_to_name.get(ip, ip or public_key[:8]),
                'ip': ip,
                'latest_handshake': int(latest_handshake),
                'rx_bytes': int(rx),
                'tx_bytes': int(tx),
            })
        return peers

    async def get_status(self) -> Dict[str, Any]:
        try:
            result = await asyncio.create_subprocess_exec(
                'wg', 'show', 'wg0',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            if result.returncode == 0:
                connections = len([line for line in stdout.decode().split('\n') if 'peer:' in line])
                return {"status": "running", "connections": connections}
            return {"status": "stopped", "connections": 0}
        except Exception:
            return {"status": "error", "connections": 0}

    async def create_peer(self, peer_name: str, allowed_ips: str = "0.0.0.0/0") -> Dict[str, Any]:
        """Create a new WireGuard peer configuration."""
        prefix = settings.wireguard_subnet_prefix
        async with self.wireguard_peer_lock:
            try:
                result = await asyncio.create_subprocess_exec(
                    'wg', 'genkey',
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate()
                private_key = stdout.decode().strip()

                result = await asyncio.create_subprocess_exec(
                    'wg', 'pubkey',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate(input=private_key.encode())
                public_key = stdout.decode().strip()

                server_public_key = await self._get_wireguard_server_public_key()

                peer_ip = await self._get_next_peer_ip()
                peer_config = f"""[Interface]
PrivateKey = {private_key}
Address = {prefix}.{peer_ip}/24
DNS = {prefix}.1

[Peer]
PublicKey = {server_public_key}
Endpoint = {settings.server_ip}:{settings.wireguard_port}
AllowedIPs = {allowed_ips}
PersistentKeepalive = 25
"""

                peers_dir = f"{settings.wireguard_config_path}/peers"
                os.makedirs(peers_dir, exist_ok=True)
                peer_file = f"{peers_dir}/{peer_name}.conf"

                with open(peer_file, 'w') as f:
                    f.write(peer_config)

                await self._add_peer_to_server(public_key, peer_name, peer_ip)

                qr_code = await self._generate_qr_code(peer_config)

                return {
                    'peer_name': peer_name,
                    'public_key': public_key,
                    'ip': f"{prefix}.{peer_ip}",
                    'config': peer_config,
                    'qr_code': qr_code,
                }
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to create WireGuard peer: {str(e)}")

    async def _get_next_peer_ip(self) -> int:
        """Get next available IP for peer, avoiding collisions with both
        app-managed peer files and peers already registered on the live
        interface (e.g. the container's own auto-provisioned PEERS)."""
        prefix = settings.wireguard_subnet_prefix
        existing_ips = []

        peers_dir = f"{settings.wireguard_config_path}/peers"
        if os.path.exists(peers_dir):
            for file in os.listdir(peers_dir):
                if file.endswith('.conf'):
                    with open(os.path.join(peers_dir, file), 'r') as f:
                        content = f.read()
                        if f'Address = {prefix}.' in content:
                            ip = content.split(f'Address = {prefix}.')[1].split('/')[0].strip()
                            existing_ips.append(int(ip))

        try:
            result = await asyncio.create_subprocess_exec(
                'wg', 'show', 'wg0', 'allowed-ips',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await result.communicate()
            if result.returncode == 0:
                for line in stdout.decode().splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].startswith(f'{prefix}.'):
                        octet = parts[1].split('/')[0].split('.')[-1]
                        if octet.isdigit():
                            existing_ips.append(int(octet))
        except Exception:
            pass

        return max(existing_ips + [1]) + 1

    async def _add_peer_to_server(self, public_key: str, peer_name: str, peer_ip: int):
        """Add peer to the live WireGuard server configuration (requires the
        agent to share the wireguard container's network namespace)."""
        prefix = settings.wireguard_subnet_prefix
        server_config = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"

        if not os.path.exists(server_config):
            os.makedirs(os.path.dirname(server_config), exist_ok=True)
            canonical_key_path = f"{settings.wireguard_config_path}/server/privatekey-server"
            if os.path.exists(canonical_key_path):
                with open(canonical_key_path, 'r') as f:
                    server_private_key = f.read().strip()
            else:
                server_private_key = subprocess.run(['wg', 'genkey'], capture_output=True, text=True).stdout.strip()
                os.makedirs(os.path.dirname(canonical_key_path), exist_ok=True)
                with open(canonical_key_path, 'w') as f:
                    f.write(server_private_key)

            server_config_content = f"""[Interface]
Address = {prefix}.1
ListenPort = {settings.wireguard_port}
PrivateKey = {server_private_key}
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth+ -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth+ -j MASQUERADE
"""
            with open(server_config, 'w') as f:
                f.write(server_config_content)

        with open(server_config, 'a') as f:
            f.write(f"\n[Peer]\n")
            f.write(f"# {peer_name}\n")
            f.write(f"PublicKey = {public_key}\n")
            f.write(f"AllowedIPs = {prefix}.{peer_ip}/32\n")

        # A failure here means the file and the running tunnel have gone out
        # of sync - that must surface as an error, not a silently-ignored
        # warning, or the peer ends up "created" on disk while never
        # actually reachable.
        proc = await asyncio.create_subprocess_exec(
            'bash', '-c', f'wg syncconf wg0 <(wg-quick strip {server_config})',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"wg syncconf failed for new peer {peer_name}: {stderr.decode().strip()}")

        # wg syncconf only updates WireGuard's own crypto-key routing table,
        # not the kernel's IP routing table - without an explicit route,
        # return traffic for this peer's address falls through to the
        # default route and is silently lost.
        route_proc = await asyncio.create_subprocess_exec(
            'ip', 'route', 'add', f'{prefix}.{peer_ip}/32', 'dev', 'wg0',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, route_stderr = await route_proc.communicate()
        if route_proc.returncode != 0 and b'File exists' not in route_stderr:
            raise HTTPException(status_code=500, detail=f"Failed to add route for new peer {peer_name}: {route_stderr.decode().strip()}")

        # Verify the IP we assigned actually landed on this peer and wasn't
        # silently handed to (or stolen from) a different one.
        verify = await asyncio.create_subprocess_exec(
            'wg', 'show', 'wg0', 'allowed-ips',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await verify.communicate()
        live_ip_for_key = None
        for line in stdout.decode().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == public_key:
                live_ip_for_key = parts[1]
        expected = f"{prefix}.{peer_ip}/32"
        if live_ip_for_key != expected:
            raise HTTPException(
                status_code=500,
                detail=f"Peer {peer_name} did not register at {expected} (got {live_ip_for_key!r}) - likely an IP collision with an existing peer"
            )

    async def _generate_qr_code(self, config_data: str) -> str:
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(config_data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, 'PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode()

    async def update_peer(self, peer_name: str, new_name: str, allowed_ips: str) -> Dict[str, Any]:
        """Rename a peer's saved config and/or change its own AllowedIPs.
        Purely bookkeeping - WireGuard itself only knows peers by public
        key, and the server's per-peer registration always keeps its fixed
        /32, so nothing here touches the live interface or needs a resync."""
        async with self.wireguard_peer_lock:
            peers_dir = f"{settings.wireguard_config_path}/peers"
            old_path = f"{peers_dir}/{peer_name}.conf"
            new_path = f"{peers_dir}/{new_name}.conf"

            if not os.path.exists(old_path):
                raise HTTPException(status_code=404, detail=f"Peer {peer_name} not found")

            if new_name != peer_name and os.path.exists(new_path):
                raise HTTPException(status_code=409, detail=f"A peer named {new_name} already exists")

            with open(old_path, 'r') as f:
                content = f.read()
            content = re.sub(r'^AllowedIPs = .*$', f'AllowedIPs = {allowed_ips}', content, flags=re.MULTILINE)

            with open(new_path, 'w') as f:
                f.write(content)
            if new_name != peer_name:
                os.remove(old_path)

            server_config = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"
            if new_name != peer_name and os.path.exists(server_config):
                with open(server_config, 'r') as f:
                    server_content = f.read()
                server_content = server_content.replace(f"# {peer_name}\n", f"# {new_name}\n")
                with open(server_config, 'w') as f:
                    f.write(server_content)

            return {"message": f"Peer {peer_name} updated successfully", "peer_name": new_name}

    async def delete_peer(self, peer_name: str) -> Dict[str, str]:
        async with self.wireguard_peer_lock:
            try:
                peer_config_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"
                if os.path.exists(peer_config_file):
                    os.remove(peer_config_file)

                server_config = f"{settings.wireguard_config_path}/wg_confs/wg0.conf"
                if os.path.exists(server_config):
                    await self._remove_peer_from_server(peer_name, server_config)

                return {"message": f"Peer {peer_name} deleted successfully"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to delete peer: {str(e)}")

    async def _remove_peer_from_server(self, peer_name: str, server_config: str):
        with open(server_config, 'r') as f:
            content = f.read()

        # Split on the [Peer] marker so each peer's block (comment, keys,
        # AllowedIPs) is handled as a unit instead of line-by-line, which
        # can't look ahead to know a block belongs to the peer being removed.
        sections = content.split('[Peer]')
        header = sections[0]
        peer_blocks = sections[1:]

        removed_blocks = [block for block in peer_blocks if f"# {peer_name}" in block]
        kept_blocks = [block for block in peer_blocks if f"# {peer_name}" not in block]

        new_content = header + ''.join(f"[Peer]{block}" for block in kept_blocks)

        with open(server_config, 'w') as f:
            f.write(new_content)

        proc = await asyncio.create_subprocess_exec(
            'bash', '-c', f'wg syncconf wg0 <(wg-quick strip {server_config})',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(status_code=500, detail=f"wg syncconf failed while removing peer: {stderr.decode().strip()}")

        # Clean up the matching route added in _add_peer_to_server
        # (best-effort - a leftover route to a now-unassigned IP is harmless
        # since nothing on wg0 will claim it, but don't leave clutter).
        for block in removed_blocks:
            for line in block.splitlines():
                if line.strip().startswith('AllowedIPs'):
                    ip_cidr = line.split('=', 1)[1].strip()
                    del_proc = await asyncio.create_subprocess_exec(
                        'ip', 'route', 'del', ip_cidr, 'dev', 'wg0',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    await del_proc.communicate()

    async def list_peers(self) -> List[Dict[str, Any]]:
        """List every peer this box knows about, from its conf files."""
        peers_dir = f"{settings.wireguard_config_path}/peers"
        prefix = settings.wireguard_subnet_prefix
        peers = []
        if not os.path.exists(peers_dir):
            return peers

        for fname in sorted(os.listdir(peers_dir)):
            if not fname.endswith('.conf'):
                continue
            peer_name = fname[:-5]
            with open(os.path.join(peers_dir, fname), 'r') as f:
                content = f.read()

            address = None
            if f'Address = {prefix}.' in content:
                address = f"{prefix}." + content.split(f'Address = {prefix}.')[1].split('/')[0].strip()

            private_key_match = re.search(r'^PrivateKey = (.+)$', content, flags=re.MULTILINE)
            public_key = None
            if private_key_match:
                result = await asyncio.create_subprocess_exec(
                    'wg', 'pubkey',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE
                )
                stdout, _ = await result.communicate(input=private_key_match.group(1).encode())
                public_key = stdout.decode().strip()

            allowed_ips_match = re.search(r'^AllowedIPs = (.+)$', content, flags=re.MULTILINE)

            peers.append({
                'peer_name': peer_name,
                'ip': address,
                'public_key': public_key,
                'allowed_ips': allowed_ips_match.group(1).strip() if allowed_ips_match else None,
            })
        return peers

    def get_peer_config(self, peer_name: str) -> str:
        peer_file = f"{settings.wireguard_config_path}/peers/{peer_name}.conf"
        if not os.path.exists(peer_file):
            raise HTTPException(status_code=404, detail=f"Peer {peer_name} not found")
        with open(peer_file, 'r') as f:
            return f.read()

    async def get_peer_qrcode(self, peer_name: str) -> str:
        config_data = self.get_peer_config(peer_name)
        return await self._generate_qr_code(config_data)

#!/usr/bin/env python3
"""
BartoloVPN Setup Script
Helps configure and deploy the VPN server
"""

import os
import sys
import subprocess
import shutil
import secrets
import socket
import time
import urllib.request
import webbrowser
from pathlib import Path


def get_api_port():
    """Read API_PORT back out of .env (falls back to 5000 if missing)"""
    try:
        with open('.env') as f:
            for line in f:
                if line.strip().startswith('API_PORT='):
                    return line.strip().split('=', 1)[1].strip() or "5000"
    except FileNotFoundError:
        pass
    return "5000"


def wait_for_service(port, timeout=15):
    """Poll until the dashboard is actually accepting connections, not just
    until 'docker-compose up -d' returns - that only means the container
    started, not that the app inside has finished its own startup (DB init,
    admin user creation, etc take a few seconds). Best-effort: gives up and
    moves on after `timeout` seconds either way, doesn't hard-fail setup."""
    print(f"⏳ Waiting for the dashboard to come up (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("localhost", int(port)), timeout=1):
                print("✅ Dashboard is up")
                return True
        except (OSError, ValueError):
            time.sleep(1)
    print("⚠️  Dashboard didn't respond in time - it may still be starting up")
    return False


def open_browser(port):
    """Best-effort opening of the dashboard in the default browser - no-op
    (not an error) on headless servers with no display/browser available"""
    url = f"http://localhost:{port}"
    print(f"🌐 Opening Web UI on {url} ...")
    try:
        if webbrowser.open(url):
            print(f"✅ Opened {url} in your default browser")
        else:
            print(f"⚠️  Couldn't auto-open a browser - visit {url} manually")
    except webbrowser.Error:
        print(f"🌐 No browser available here (headless server?) - visit {url} manually")


def get_local_ip():
    """Best-effort detection of this machine's local network IP (no
    traffic is actually sent - just used to pick a source address)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def get_public_ip():
    """Auto-detect this server's external/public IP via an external echo
    service, so the user never has to be asked for it"""
    try:
        with urllib.request.urlopen('https://api.ipify.org', timeout=5) as resp:
            ip = resp.read().decode().strip()
            return ip or None
    except Exception:
        return None


def generate_ikev2_psk():
    """Auto-generate an IKEv2 pre-shared key: BVPN<year>-IKEV2-<10 random
    alphanumeric chars>, e.g. BVPN2026-IKEV2-A7B3K9P2QX"""
    import datetime
    year = datetime.datetime.now().year
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    suffix = ''.join(secrets.choice(alphabet) for _ in range(10))
    return f"BVPN{year}-IKEV2-{suffix}"


def generate_ikev2_password():
    """Auto-generate a strong random IKEv2 user password"""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    return ''.join(secrets.choice(alphabet) for _ in range(16))

def print_banner():
    """Print setup banner"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║                    BartoloVPN Setup                          ║
║              Multi-Protocol VPN Server                       ║
╚══════════════════════════════════════════════════════════════╝
    """)

def detect_os():
    """Detect the host OS/distro so we know which package manager to use.
    This is the first real thing setup does, before asking anything."""
    import platform
    system = platform.system()
    if system == 'Darwin':
        return {'family': 'macos', 'id': 'macos', 'pretty_name': 'macOS'}
    if system == 'Windows':
        return {'family': 'windows', 'id': 'windows', 'pretty_name': 'Windows'}
    if system != 'Linux':
        return {'family': 'unknown', 'id': system.lower(), 'pretty_name': system}

    os_release = {}
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if '=' in line:
                    key, _, value = line.strip().partition('=')
                    os_release[key] = value.strip('"')
    except FileNotFoundError:
        pass

    distro_id = os_release.get('ID', '').lower()
    id_like = os_release.get('ID_LIKE', '').lower()
    pretty_name = os_release.get('PRETTY_NAME', 'Linux')

    if distro_id in ('ubuntu', 'debian') or 'debian' in id_like:
        family = 'debian'
    elif distro_id in ('fedora', 'rhel', 'centos', 'rocky', 'almalinux') or 'rhel' in id_like or 'fedora' in id_like:
        family = 'rhel'
    elif distro_id == 'arch' or 'arch' in id_like:
        family = 'arch'
    else:
        family = 'unknown'

    return {'family': family, 'id': distro_id, 'pretty_name': pretty_name}


# Maps our internal requirement keys to the actual package name/ID per OS
# family. Windows has no strongSwan/ipsec equivalent - IKEv2 support is
# built natively into the OS, so 'ipsec' is intentionally absent there.
PACKAGE_NAMES = {
    'debian': {'docker': 'docker.io', 'docker-compose': 'docker-compose',
               'wg': 'wireguard-tools', 'openvpn': 'openvpn', 'ipsec': 'strongswan'},
    'rhel': {'docker': 'docker', 'docker-compose': 'docker-compose',
             'wg': 'wireguard-tools', 'openvpn': 'openvpn', 'ipsec': 'strongswan'},
    'arch': {'docker': 'docker', 'docker-compose': 'docker-compose',
             'wg': 'wireguard-tools', 'openvpn': 'openvpn', 'ipsec': 'strongswan'},
    'windows': {'docker': 'Docker.DockerDesktop', 'wg': 'WireGuard.WireGuard',
                'openvpn': 'OpenVPNTechnologies.OpenVPN'},
}

# The command each requirement key actually resolves to, per OS - differs on
# Windows (e.g. WireGuard's CLI ships as wireguard.exe, not wg.exe)
COMMAND_NAMES = {
    'windows': {'docker': 'docker', 'docker-compose': 'docker-compose', 'wg': 'wireguard', 'openvpn': 'openvpn'},
}

PACKAGE_MANAGERS = {
    'debian': {'update': ['sudo', 'apt-get', 'update'],
               'install': ['sudo', 'apt-get', 'install', '-y']},
    'rhel': {'update': None,
             'install': ['sudo', 'dnf', 'install', '-y']},
    'arch': {'update': None,
             'install': ['sudo', 'pacman', '-S', '--noconfirm']},
    'windows': {'update': None, 'install': None},  # handled specially below - winget installs one package per invocation
}


def install_winget():
    """Auto-install winget itself via Microsoft's official App Installer
    bundle (the same aka.ms/getwinget link used in most provisioning
    scripts), for Windows systems that don't already have it."""
    print("winget not found - attempting to install it automatically...")
    bundle_path = os.path.join(os.environ.get('TEMP', '.'), 'Microsoft.DesktopAppInstaller.msixbundle')
    try:
        urllib.request.urlretrieve('https://aka.ms/getwinget', bundle_path)
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', f'Add-AppxPackage -Path "{bundle_path}"'],
            check=True
        )
    except Exception as e:
        print(f"WARNING: Automatic winget install failed: {e}")
        print("Please install 'App Installer' manually from the Microsoft Store, then re-run setup.")
        return False
    finally:
        if os.path.exists(bundle_path):
            os.remove(bundle_path)

    if shutil.which('winget') is None:
        print("WARNING: winget still not found on PATH after install - you may need to restart your terminal.")
        return False
    print("winget installed successfully")
    return True


def install_missing_requirements(missing_keys, os_info):
    """Best-effort automatic install of missing requirements using the
    detected OS's package manager (apt/dnf/pacman/winget)."""
    family = os_info['family']
    if family not in PACKAGE_MANAGERS:
        print(f"WARNING: Don't know how to auto-install on {os_info['pretty_name']}. "
              f"Please install manually: {', '.join(missing_keys)}")
        return

    print(f"\nAuto-installing missing requirements for {os_info['pretty_name']}...")

    if family == 'windows':
        if shutil.which('winget') is None and not install_winget():
            return
        for key in missing_keys:
            pkg_id = PACKAGE_NAMES['windows'].get(key)
            if not pkg_id:
                print(f"WARNING: No winget package known for '{key}' on Windows - skipping")
                continue
            print(f"Installing {pkg_id} via winget...")
            try:
                subprocess.run(
                    ['winget', 'install', '-e', '--id', pkg_id,
                     '--accept-source-agreements', '--accept-package-agreements'],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                print(f"WARNING: winget install of {pkg_id} failed: {e}")
            except FileNotFoundError:
                print("ERROR: 'winget' isn't available even after install attempt - install "
                      "Docker Desktop / WireGuard / OpenVPN manually.")
                return
        if 'docker' in missing_keys:
            print("NOTE: Docker Desktop may require a restart/manual launch and WSL2 to be enabled "
                  "before 'docker' becomes available on the command line.")
        return

    mgr = PACKAGE_MANAGERS[family]
    if mgr['update']:
        try:
            subprocess.run(mgr['update'], check=True)
        except subprocess.CalledProcessError as e:
            print(f"WARNING: Package list update failed: {e}")

    packages = [PACKAGE_NAMES[family][key] for key in missing_keys if key in PACKAGE_NAMES[family]]
    if packages:
        try:
            subprocess.run(mgr['install'] + packages, check=True)
        except subprocess.CalledProcessError as e:
            print(f"WARNING: Package install failed: {e}")

    if 'docker-compose' in missing_keys and shutil.which('docker-compose') is None:
        # Distro repos don't always ship a working docker-compose - fall back
        # to the portable pip install
        print("Falling back to 'pip install docker-compose'...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--user', 'docker-compose'], check=True)
        except subprocess.CalledProcessError as e:
            print(f"WARNING: pip fallback failed: {e}")

    if 'docker' in missing_keys:
        try:
            subprocess.run(['sudo', 'systemctl', 'enable', '--now', 'docker'], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        current_user = os.environ.get('USER', '')
        if current_user:
            try:
                subprocess.run(['sudo', 'usermod', '-aG', 'docker', current_user], check=True)
                print("NOTE: Added current user to the 'docker' group - log out and back in for this to take effect")
            except subprocess.CalledProcessError:
                pass

    if 'ipsec' in missing_keys:
        # Installing strongswan auto-starts its own IKE daemon (charon) on
        # UDP 500/4500 - BartoloVPN runs IKEv2 in its own Docker container
        # on those same ports, so the host service has to be disabled or it
        # blocks the container from ever starting ("address already in use")
        for service in ('strongswan-starter', 'strongswan'):
            try:
                subprocess.run(['sudo', 'systemctl', 'disable', '--now', service],
                                check=True, stderr=subprocess.DEVNULL)
                print(f"NOTE: Disabled the host's {service} service (BartoloVPN runs IKEv2 in Docker on the same ports)")
                break
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue


def check_requirements():
    """Detect the OS first, then check - and auto-install if missing - the
    tools this project actually needs"""
    os_info = detect_os()
    print(f"Detected OS: {os_info['pretty_name']}")

    print("\nChecking requirements...")

    requirements = {
        'docker': 'docker',
        'docker-compose': 'docker-compose',
        'wg': 'wg',
        'openvpn': 'openvpn',
        'ipsec': 'ipsec',
    }
    # Windows has no ipsec/strongSwan equivalent (IKEv2 is native to the OS),
    # and some commands ship under different names there
    if os_info['family'] == 'windows':
        requirements = {k: v for k, v in requirements.items() if k != 'ipsec'}
        requirements.update(COMMAND_NAMES['windows'])

    missing = []
    for key, cmd in requirements.items():
        if shutil.which(cmd) is None:
            missing.append(key)
        else:
            print(f"OK: {cmd} found")

    if not missing:
        return True

    print(f"Missing: {', '.join(requirements[k] for k in missing)}")

    if os_info['family'] == 'macos':
        print("ERROR: Automatic install isn't supported on macOS - please install Docker Desktop "
              "(https://www.docker.com/products/docker-desktop) and re-run setup.")
        return False

    install_missing_requirements(missing, os_info)

    still_missing = [requirements[k] for k in missing if shutil.which(requirements[k]) is None]
    if still_missing:
        print(f"ERROR: Still missing after auto-install attempt: {', '.join(still_missing)}")
        print("Please install these manually and run setup again.")
        return False

    print("All requirements installed successfully")
    return True


def get_user_input():
    """Get configuration from user"""
    print("\n📝 Configuration Setup")
    print("Please provide the following information:")
    
    config = {}
    
    # Server configuration
    public_ip = get_public_ip()
    if public_ip:
        config['server_ip'] = public_ip
        print(f"🌐 Detected external IP automatically: {public_ip}")
    else:
        local_ip = get_local_ip()
        print("⚠️  Could not auto-detect external IP (no internet access?)")
        if local_ip:
            config['server_ip'] = input(f"🌐 Server IP (default: {local_ip}): ").strip() or local_ip
        else:
            config['server_ip'] = input("🌐 Server IP: ").strip()
    if not config['server_ip']:
        print("❌ Server IP is required!")
        return None
    
    config['domain'] = input("🌍 Domain (optional): ").strip()
    
    # Web interface

    config['web_username'] = input("👤 Admin Username (default: admin): ").strip() or "admin"
    config['web_password'] = input("🔒 Admin Password: ").strip()
    if not config['web_password']:
        print("❌ Admin password is required!")
        return None

    port_input = input("🔌 Web UI port (default: 5000): ").strip()
    if port_input:
        if not port_input.isdigit() or not (1 <= int(port_input) <= 65535):
            print("❌ Port must be a number between 1 and 65535!")
            return None
        config['api_port'] = port_input
    else:
        config['api_port'] = "5000"

    # Security
    config['encryption_level'] = input("🔐 Encryption Level (128/256, default: 256): ").strip() or "256"
    config['dns_servers'] = input("📡 DNS Servers (default: 1.1.1.1,8.8.8.8): ").strip() or "1.1.1.1,8.8.8.8"
    
    return config

def create_env_file(config):
    """Create .env file from configuration"""
    if os.path.exists('.env'):
        backup_path = f".env.backup.{int(__import__('time').time())}"
        shutil.copy('.env', backup_path)
        print(f"\n⚠️  Existing .env found — backed up to {backup_path} before overwriting")

    print("\n📄 Creating .env file...")

    jwt_secret = secrets.token_hex(32)
    print("🔑 Generated a random JWT_SECRET_KEY")

    region_agent_encryption_key = secrets.token_hex(32)
    print("🔑 Generated a random REGION_AGENT_ENCRYPTION_KEY")

    compose_project_name = "bartolovpn"

    ikev2_psk = generate_ikev2_psk()
    print(f"🔑 Generated IKEv2 pre-shared key: {ikev2_psk}")

    ikev2_password = generate_ikev2_password()
    print("🔑 Generated a random IKEv2 password")

    env_content = f"""# BartoloVPN Configuration

# Server Configuration
SERVER_IP={config['server_ip']}
DOMAIN={config['domain']}

# Web Interface

WEB_USERNAME={config['web_username']}
WEB_PASSWORD={config['web_password']}
API_PORT={config['api_port']}

# WireGuard Configuration
WIREGUARD_ENABLED=true
WIREGUARD_PORT=51820
WIREGUARD_PEERS=10
WIREGUARD_DNS={config['dns_servers']}
WIREGUARD_SUBNET=10.13.13.0
WIREGUARD_ALLOWED_IPS=0.0.0.0/0

# OpenVPN Configuration
OPENVPN_ENABLED=true
OPENVPN_PORT=1194
OPENVPN_PROTOCOL=udp
OPENVPN_CIPHER=AES-{config['encryption_level']}-GCM
OPENVPN_AUTH=SHA256

# IKEv2 Configuration
IKEV2_ENABLED=true
IKEV2_PSK={ikev2_psk}
IKEV2_USER=vpnuser
IKEV2_PASSWORD={ikev2_password}


# Security Settings
ENCRYPTION_LEVEL={config['encryption_level']}
DNS_SERVERS={config['dns_servers']}
KILL_SWITCH_ENABLED=true

# Logging
LOG_LEVEL=INFO
LOG_RETENTION_DAYS=30

# Monitoring
MONITORING_ENABLED=true
BANDWIDTH_LIMIT_MB=1000

# JWT Secret (auto-generated per install)
JWT_SECRET_KEY={jwt_secret}
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=10080

# Encrypts remote-region agent API keys at rest (multi-region feature,
# see api/region_service.py). Auto-generated per install.
REGION_AGENT_ENCRYPTION_KEY={region_agent_encryption_key}

# Fixed Docker Compose project name, so container names stay clean
# (bartolovpn-wireguard, not a directory-derived or numbered name).
COMPOSE_PROJECT_NAME={compose_project_name}

# Network Configuration
LOCAL_IP={config['server_ip']}
LOCAL_IPV6=::1
PREVIOUS_IPS=

# Configuration Paths (must match the volume mounts in docker-compose.yml)
WIREGUARD_CONFIG_PATH=/config/wireguard
OPENVPN_CONFIG_PATH=/config/openvpn
IKEV2_CONFIG_PATH=/config/ikev2

# Database Configuration
DATABASE_URL=sqlite+aiosqlite:///./data/bartolovpn.db
"""
    
    with open('.env', 'w') as f:
        f.write(env_content)
    
    print("✅ .env file created successfully")

def generate_oracle_api_key():
    """Generates the RSA key pair the Settings page's Oracle Cloud
    Integration section uses to sign requests to Oracle's API, if one
    isn't already there. Oracle's API isn't a simple secret-string scheme
    like AWS's - every request has to be signed with an RSA private key,
    with the matching public key uploaded to the OCI Console - so this
    just prepares the pair ahead of time; it's inert (never read by
    anything) unless the operator later enables Oracle Cloud Services and
    clicks Import in Settings. Skipped silently if openssl isn't
    available - the operator can still paste a key manually in Settings."""
    key_dir = Path('.ssh')
    private_path = key_dir / 'oracle-api-private.pem'
    public_path = key_dir / 'oracle-api-public.pem'

    if private_path.exists():
        return

    if shutil.which('openssl') is None:
        print("⚠️  openssl not found - skipping Oracle API key generation "
              "(you can still paste a key manually in Settings, or install "
              "openssl and re-run setup)")
        return

    key_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(['openssl', 'genrsa', '-out', str(private_path), '2048'],
                        check=True, capture_output=True)
        os.chmod(private_path, 0o600)
        subprocess.run(['openssl', 'rsa', '-pubout', '-in', str(private_path), '-out', str(public_path)],
                        check=True, capture_output=True)
        print(f"🔑 Generated an Oracle Cloud API signing key pair in {key_dir}/ "
              f"(only used if you enable Oracle Cloud Services in Settings)")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors='replace') if e.stderr else str(e)
        print(f"⚠️  Failed to generate Oracle API key pair: {stderr}")


def create_directories():
    """Create necessary directories"""
    print("\n📁 Creating directories...")
    
    directories = [
        'config/wireguard/peers',
        'config/openvpn/clients',
        'config/ikev2',
        'logs',
        'data'
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✅ Created {directory}/")

def build_and_start():
    """Build and start the services"""
    print("\n🚀 Building and starting services...")
    
    try:
        # Build images
        print("📦 Building Docker images...")
        subprocess.run(['docker-compose', 'build'], check=True)
        
        # Start services
        print("▶️  Starting services...")
        subprocess.run(['docker-compose', 'up', '-d'], check=True)
        
        print("✅ Services started successfully!")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start services: {e}")
        return False
    
    return True

def show_status():
    """Show service status"""
    print("\n📊 Service Status:")
    
    try:
        result = subprocess.run(['docker-compose', 'ps'], capture_output=True, text=True)
        print(result.stdout)
    except subprocess.CalledProcessError:
        print("❌ Failed to get service status")

def show_next_steps(port):
    """Show next steps for the user"""
    print(f"""
🎉 Setup Complete!

Next Steps:
1. 🌐 Access the web interface: http://your-server-ip:{port}
2. 👤 Login with the admin credentials you provided
3. 🔧 Configure additional endpoints and users
4. 📱 Generate client configurations for your friends
5. 🔄 Set up IP rotation to avoid detection

Important Notes:
- 🔒 Change default passwords immediately
- 🌍 Configure your domain DNS if you have one
- 📊 Monitor usage and performance
- 🔄 Regularly rotate IP addresses
- 📝 Keep backups of configurations

For support and documentation:
- 📖 Read the README.md file
- 🐛 Check logs: docker-compose logs
- 🔧 Restart services: docker-compose restart

Happy VPN-ing! 🚀
    """)

def main():
    """Main setup function"""
    print_banner()
    
    # Check requirements
    if not check_requirements():
        sys.exit(1)
    
    # Skip reconfiguration if .env already exists - re-running vpn-setup.py
    # shouldn't force the user through every prompt (and overwrite their
    # settings) again on every restart
    if os.path.exists('.env'):
        reconfigure = input("\n📄 .env already exists. Reconfigure from scratch? (y/N): ").strip().lower() == 'y'
        if not reconfigure:
            print("✅ Keeping existing .env")
        else:
            config = get_user_input()
            if not config:
                sys.exit(1)
            create_env_file(config)
    else:
        config = get_user_input()
        if not config:
            sys.exit(1)
        create_env_file(config)

    # Create directories
    create_directories()

    # Prepare the Oracle API signing key pair ahead of time, regardless of
    # whether this operator will ever use it - see generate_oracle_api_key
    generate_oracle_api_key()

    # Build and start services
    if build_and_start():
        show_status()
        port = get_api_port()
        wait_for_service(port)
        open_browser(port)
        show_next_steps(port)
    else:
        print("❌ Setup failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()

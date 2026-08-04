#!/bin/bash
# BartoloVPN bootstrap installer.
#
# Single entry point for both setup paths, so "git clone && cd BartoloVPN
# && ./install.sh" is always the right first command regardless of which
# one you're doing:
#   1) Main dashboard - detects/installs Python itself (needed since
#      vpn-setup.py can't do that check on its own), then hands off to it.
#   2) A new region for an EXISTING dashboard - hands off directly to
#      scripts/provision-region.sh (pure bash, no Python needed).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "BartoloVPN Installer"
echo "===================="
echo
echo "What are you setting up on this machine?"
echo "  1) Main BartoloVPN dashboard (the full VPN server + web UI)"
echo "  2) A new region for an EXISTING BartoloVPN dashboard (lightweight agent only)"
read -rp "Choice [1/2]: " SETUP_MODE
echo

# Asked once here, regardless of which path above - both a main dashboard
# and a region can be running on an Oracle Cloud box, and both need the
# same OCI-specific firewall handling (see apply_oracle_fixes below).
read -rp "Is this an Oracle Cloud (OCI) VPS? [y/N]: " IS_ORACLE
IS_ORACLE="${IS_ORACLE:-n}"
export IS_ORACLE
echo

# Oracle's stock Ubuntu images ship their own iptables rules (persisted via
# netfilter-persistent/iptables-persistent) that only allow SSH and REJECT
# everything else, on top of whatever ufw does - inserting ACCEPT rules at
# the very top of INPUT guarantees they're hit before any REJECT rule
# further down, regardless of where it is. Call with every port that
# should be reachable from the internet on this box.
apply_oracle_fixes() {
    if [ "$(id -u)" -ne 0 ]; then
        SUDO="sudo"
    else
        SUDO=""
    fi

    echo "Oracle Cloud detected - adjusting the pre-installed iptables rules..."
    if command -v iptables >/dev/null 2>&1; then
        for port_proto in "$@"; do
            port="${port_proto%%/*}"
            proto="${port_proto##*/}"
            $SUDO iptables -I INPUT 1 -p "$proto" --dport "$port" -j ACCEPT
        done
        if command -v netfilter-persistent >/dev/null 2>&1; then
            $SUDO netfilter-persistent save >/dev/null 2>&1 || true
        elif [ -d /etc/iptables ]; then
            $SUDO sh -c 'iptables-save > /etc/iptables/rules.v4' 2>/dev/null || true
        fi
        echo "iptables rules updated and saved."
    else
        echo "WARNING: iptables not found - skipping (this image may not need it)."
    fi

    echo
    echo "WARNING: Oracle Cloud has a SECOND firewall you must open in the console (this script cannot reach it):"
    echo "  Networking -> Virtual Cloud Networks -> your VCN -> Security Lists -> Default Security List -> Add Ingress Rules"
    echo "  for: $* (source 0.0.0.0/0)."
    echo "  Nothing will be reachable from the internet until this is done, even though everything on the box itself is correctly configured."
}

if [ "$SETUP_MODE" = "2" ]; then
    REGION_SCRIPT="$SCRIPT_DIR/scripts/provision-region.sh"
    if [ ! -f "$REGION_SCRIPT" ]; then
        echo "ERROR: Could not find $REGION_SCRIPT - is this a full clone of the repo?"
        exit 1
    fi
    echo "Handing off to scripts/provision-region.sh (needs root for package installs and firewall rules)..."
    exec sudo -E "$REGION_SCRIPT" "$@"
fi

detect_distro() {
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "macos"
        return
    fi
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "${ID} ${ID_LIKE:-}" in
            *debian*|*ubuntu*) echo "debian" ;;
            *rhel*|*fedora*|*centos*) echo "rhel" ;;
            *arch*) echo "arch" ;;
            *) echo "unknown" ;;
        esac
    else
        echo "unknown"
    fi
}

find_python() {
    for cmd in python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            read -r major minor < <("$cmd" -c 'import sys; print(sys.version_info[0], sys.version_info[1])' 2>/dev/null) || continue
            if [ "$major" = "3" ] && [ "$minor" -ge 8 ] 2>/dev/null; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

install_python_debian() {
    echo "Installing Python 3 via apt..."
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip python3-venv
}

install_python_rhel() {
    echo "Installing Python 3 via dnf..."
    sudo dnf install -y python3 python3-pip
}

install_python_arch() {
    echo "Installing Python 3 via pacman..."
    sudo pacman -S --noconfirm python python-pip
}

install_python_macos() {
    # Homebrew is the most widely-used package manager for this on macOS
    if ! command -v brew >/dev/null 2>&1; then
        echo "Homebrew not found - installing it first..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)" || true
    fi
    echo "Installing Python 3 via Homebrew..."
    brew install python3
}

compile_python_from_source() {
    # Package manager install unavailable or failed (rare) - compile from
    # source, same approach as ~/Documents/Scripts/compile-python.sh
    echo "Falling back to compiling Python from source (this can take a while)..."

    VERSION=$(curl -s https://endoflife.date/api/python.json | grep -o '"latest":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -z "$VERSION" ]; then
        VERSION="3.12.7"  # known-good fallback if the API is unreachable
    fi
    echo "Compiling Python $VERSION from source..."

    case "$(detect_distro)" in
        debian)
            sudo apt-get update
            sudo apt-get install -y build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev \
                libsqlite3-dev wget curl llvm libncurses5-dev libncursesw5-dev xz-utils tk-dev liblzma-dev
            ;;
        rhel)
            sudo dnf groupinstall -y "Development Tools"
            sudo dnf install -y openssl-devel bzip2-devel libffi-devel zlib-devel wget
            ;;
        arch)
            sudo pacman -S --noconfirm base-devel openssl zlib wget
            ;;
        *)
            echo "ERROR: Don't know how to install build dependencies on this OS - please install Python 3.8+ manually."
            exit 1
            ;;
    esac

    INSTALL_DIR="/opt/python/$VERSION"
    ( cd /tmp
      if [ ! -f "Python-$VERSION.tgz" ]; then
          wget -q "https://www.python.org/ftp/python/$VERSION/Python-$VERSION.tgz"
      fi
      tar -xzf "Python-$VERSION.tgz"
      cd "Python-$VERSION"
      sudo ./configure --prefix="$INSTALL_DIR" --enable-optimizations --with-lto
      sudo make -j"$(nproc)"
      sudo make altinstall
    )

    SHORT_VER="${VERSION%.*}"
    sudo ln -sf "$INSTALL_DIR/bin/python$SHORT_VER" /usr/local/bin/python3
}

PYTHON_CMD=""
if found=$(find_python); then
    PYTHON_CMD="$found"
fi

if [ -z "$PYTHON_CMD" ]; then
    echo "Python 3.8+ not found - installing it automatically..."
    DISTRO=$(detect_distro)
    case "$DISTRO" in
        debian) install_python_debian ;;
        rhel) install_python_rhel ;;
        arch) install_python_arch ;;
        macos) install_python_macos ;;
        *) echo "WARNING: Unrecognized OS ($DISTRO) - can't auto-install via a package manager" ;;
    esac

    if found=$(find_python); then
        PYTHON_CMD="$found"
    fi

    if [ -z "$PYTHON_CMD" ] && [ "$DISTRO" != "macos" ]; then
        compile_python_from_source
        if found=$(find_python); then
            PYTHON_CMD="$found"
        fi
    fi

    if [ -z "$PYTHON_CMD" ]; then
        echo "ERROR: Failed to install Python automatically. Please install Python 3.8+ manually and re-run this script."
        exit 1
    fi
fi

echo "Using Python: $("$PYTHON_CMD" --version)"
echo ""
"$PYTHON_CMD" vpn-setup.py "$@"
SETUP_EXIT=$?

if [ "$SETUP_EXIT" -eq 0 ] && [[ "$IS_ORACLE" =~ ^[Yy] ]]; then
    echo
    # Read back the ports vpn-setup.py actually configured (interactively,
    # during its own prompts) rather than assuming defaults - .env now
    # exists since setup just succeeded.
    api_port=$(grep -m1 '^API_PORT=' .env | cut -d= -f2)
    wg_port=$(grep -m1 '^WIREGUARD_PORT=' .env | cut -d= -f2)
    ovpn_port=$(grep -m1 '^OPENVPN_PORT=' .env | cut -d= -f2)
    apply_oracle_fixes \
        "${api_port:-5000}/tcp" \
        "${wg_port:-51820}/udp" \
        "${ovpn_port:-1194}/udp" \
        "500/udp" "4500/udp"
fi

exit "$SETUP_EXIT"

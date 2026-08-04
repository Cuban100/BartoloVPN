#!/bin/bash
# BartoloVPN bootstrap installer.
#
# This is deliberately plain bash with no Python dependency - it exists
# specifically to detect/install Python itself, then hand off to the real
# setup script (vpn-setup.py). vpn-setup.py can't do this check on its own
# since it needs Python to even start running.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "BartoloVPN Installer"
echo "===================="

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
exec "$PYTHON_CMD" vpn-setup.py "$@"

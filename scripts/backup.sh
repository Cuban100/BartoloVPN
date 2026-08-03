#!/bin/bash
# Backup BartoloVPN: VPN peer configs/keys (config/) and the SQLite database.
# Does NOT include .env (JWT secret, admin password) - back that up separately
# and store it apart from this archive, since this archive alone contains
# private keys and certs that are enough to impersonate/connect as any peer.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}INFO:${NC} $1"; }
log_warn()  { echo -e "${YELLOW}WARN:${NC} $1"; }
log_error() { echo -e "${RED}ERROR:${NC} $1"; }
log_step()  { echo -e "${BLUE}STEP:${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="bartolovpn-backup-${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

log_step "Backing up config/ (WireGuard/OpenVPN/IKEv2 configs and keys) and the database..."

TAR_TARGETS=()
[ -d config ] && TAR_TARGETS+=(config)
[ -f api/data/bartolovpn.db ] && TAR_TARGETS+=(api/data/bartolovpn.db)

if [ ${#TAR_TARGETS[@]} -eq 0 ]; then
    log_error "Nothing found to back up (no config/ directory or api/data/bartolovpn.db). Run this from the BartoloVPN project root."
    exit 1
fi

if ! tar -czf "$BACKUP_DIR/$ARCHIVE_NAME" "${TAR_TARGETS[@]}" 2>/tmp/bartolovpn-backup-err; then
    if grep -q "Permission denied" /tmp/bartolovpn-backup-err; then
        log_error "Permission denied reading some files. The WireGuard container creates config/wireguard/* as root - re-run with sudo:"
        log_error "  sudo $0"
    fi
    cat /tmp/bartolovpn-backup-err >&2
    rm -f /tmp/bartolovpn-backup-err "$BACKUP_DIR/$ARCHIVE_NAME"
    exit 1
fi
rm -f /tmp/bartolovpn-backup-err

SIZE=$(du -h "$BACKUP_DIR/$ARCHIVE_NAME" | cut -f1)
log_info "Backup created: $BACKUP_DIR/$ARCHIVE_NAME ($SIZE)"
log_warn "This archive contains VPN private keys and certs - store it securely and off this host."
log_warn ".env (JWT secret, admin password) is NOT included - back it up separately if you need it."

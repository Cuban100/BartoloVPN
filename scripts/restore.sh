#!/bin/bash
# Restore a backup created by scripts/backup.sh: overwrites config/ and the
# SQLite database with the archive's contents. Stop the stack first
# (docker-compose down) so nothing is writing to the DB mid-restore.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}INFO:${NC} $1"; }
log_warn()  { echo -e "${YELLOW}WARN:${NC} $1"; }
log_error() { echo -e "${RED}ERROR:${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

ARCHIVE="$1"
if [ -z "$ARCHIVE" ]; then
    log_error "Usage: $0 <backup-archive.tar.gz>"
    exit 1
fi
if [ ! -f "$ARCHIVE" ]; then
    log_error "File not found: $ARCHIVE"
    exit 1
fi

log_warn "This will overwrite the current config/ directory and database with the contents of:"
log_warn "  $ARCHIVE"
log_warn "Make sure the stack is stopped first: docker-compose down"
read -p "Continue? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    log_info "Aborted, nothing changed."
    exit 0
fi

tar -xzf "$ARCHIVE" -C "$PROJECT_ROOT"

log_info "Restore complete."
log_info "Start the stack with: docker-compose up -d"

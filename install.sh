#!/bin/bash
# BartoloVPN region setup entry point.
#
# Sets up this VPS as a new region for an EXISTING BartoloVPN dashboard.
# First question is always whether this is Oracle Cloud (skips all
# Oracle-specific handling if not); everything else - continent/city,
# public IP, hostname, WireGuard port, dashboard auto-registration -
# follows via scripts/provision-region.sh.
#
# To install a brand new main BartoloVPN dashboard instead (rare - most
# setups already have one and are only adding a region), run
# `python3 vpn-setup.py` directly instead of this script.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REGION_SCRIPT="$SCRIPT_DIR/scripts/provision-region.sh"
if [ ! -f "$REGION_SCRIPT" ]; then
    echo "ERROR: Could not find $REGION_SCRIPT - is this a full clone of the repo?"
    exit 1
fi

exec sudo "$REGION_SCRIPT" "$@"

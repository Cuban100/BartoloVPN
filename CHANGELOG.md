# Changelog

All notable changes to BartoloVPN will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Multi-region WireGuard support** - a new `region-agent/` service deployable on any additional VPS, plus a `Region` model, `RegionClient`/`region_service` in the dashboard, and a Regions tab in the UI. Peer create/list/edit/delete all take an optional `region`, defaulting to today's local-only behavior. See `MULTI-REGION.md`.
- **One-click Oracle Cloud region provisioning** (`POST /regions/oracle`) - creates a real Always Free `VM.Standard.E2.1.Micro` instance via the OCI SDK, installs Docker and the region agent via cloud-init, and polls until healthy, all as a background task with no manual SSH.
- Region health checks now query Oracle's real instance state via the OCI API in addition to pinging the agent, so a genuinely running-but-still-booting instance is distinguishable from an actually terminated one.
- Active Connections table and the VPN Performance widget on the Monitoring page now include peers connected through remote regions, not just the local WireGuard server.
- Export/Import buttons on the Settings page, plus Oracle API key auto-detection from `~/.ssh/`.

### Changed
- All native `<select>` dropdowns across the app now render a custom-themed dropdown panel instead of the browser's native popup, which Linux Chrome renders unstyleable (white-on-white text) regardless of CSS.
- Bandwidth/speed widgets (Network Activity, WireGuard, OpenVPN, IKEv2) now auto-scale to KB/s below 1 MB/s instead of rounding low-but-real traffic down to a misleading "0.0 MB/s".

### Fixed
- DNS Activity tab was showing garbage numeric "domains" from `127.0.0.1` instead of real peer queries - the local WireGuard CoreDNS instance never had query logging enabled, and what was being captured was actually its internal loop-detection probe. Real query logging is now enabled, and the forwarder no longer loops back on itself.
- `/api/system/connections` and `/api/system/resources` no longer fail entirely when one data source (e.g. a Docker sidecar) is temporarily unreachable - each source degrades independently instead of blanking the whole response.

### Added (earlier)
- User registration and authentication system
- Web-based management interface with Jinja2 templates
- Real-time system monitoring dashboard
- Multi-protocol VPN support (WireGuard, OpenVPN, IKEv2)
- Load balancing with HAProxy
- IP rotation capabilities
- Geo-spoofing functionality
- Cloudflare Tunnel integration
- Docker containerization
- SQLite database with SQLAlchemy ORM
- JWT-based authentication
- RESTful API with FastAPI
- Comprehensive logging system
- Health check endpoints
- User management interface
- VPN configuration generation
- QR code generation for mobile clients
- System statistics monitoring
- Network bandwidth tracking
- Service status monitoring

### Changed
- Migrated from Flask to FastAPI for better performance
- Improved Docker networking architecture
- Enhanced security with proper password hashing
- Updated UI with modern responsive design
- Optimized container resource usage

### Fixed
- OpenVPN initialization issues
- Docker network conflicts
- HAProxy configuration problems
- IPv6 forwarding issues
- Container permission problems

## [1.0.0] - 2025-08-28

### Added
- Initial release of BartoloVPN
- Multi-protocol VPN server (WireGuard, OpenVPN, IKEv2)
- Web-based management interface
- Docker containerization
- User authentication system
- Real-time monitoring
- Load balancing capabilities
- IP rotation features
- Geo-spoofing support
- Cloudflare Tunnel integration

---

## Version History

### Version 1.0.0 (2025-08-28)
- **Initial Release**
  - Complete VPN server solution
  - Web management interface
  - Docker deployment
  - Multi-user support
  - Advanced networking features

---

## Contributing

To add entries to this changelog:

1. Add your changes under the appropriate section in [Unreleased]
2. Use the following categories:
   - **Added** for new features
   - **Changed** for changes in existing functionality
   - **Deprecated** for soon-to-be removed features
   - **Removed** for now removed features
   - **Fixed** for any bug fixes
   - **Security** for security-related changes

3. When releasing a new version:
   - Move [Unreleased] changes to the new version
   - Update the version number and date
   - Create a new [Unreleased] section

---

**Note**: This changelog follows the [Keep a Changelog](https://keepachangelog.com/) format and [Semantic Versioning](https://semver.org/) principles.

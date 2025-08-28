# Changelog

All notable changes to BartoloVPN will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

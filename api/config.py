#!/usr/bin/env python3
"""
Configuration management for BartoloVPN
Loads all settings from environment variables
"""

import os
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Literal defaults shipped in env.example - refusing to boot with these
# catches the single most common self-hosting mistake (copy .env, forget
# to change the secrets) before the service is ever exposed.
_PLACEHOLDER_SECRETS = {
    "jwt_secret_key": "your-super-secret-jwt-key-change-this-in-production",
    "web_password": "your-secure-password-change-this",
    "ikev2_psk": "your-ikev2-pre-shared-key-change-this",
    "ikev2_password": "vpnpass-change-this",
}

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Server Configuration
    server_ip: str = Field(...)
    domain: Optional[str] = Field(default=None)
    
    # Web Interface

    web_username: str = Field(...)
    web_password: str = Field(...)
    
    # WireGuard Configuration
    wireguard_enabled: bool = Field(...)
    wireguard_port: int = Field(...)
    wireguard_peers: int = Field(...)
    wireguard_dns: str = Field(...)
    wireguard_subnet: str = Field(...)
    wireguard_allowed_ips: str = Field(...)
    
    # OpenVPN Configuration
    openvpn_enabled: bool = Field(...)
    openvpn_port: int = Field(...)
    openvpn_protocol: str = Field(...)
    openvpn_cipher: str = Field(...)
    openvpn_auth: str = Field(...)
    
    # IKEv2 Configuration
    ikev2_enabled: bool = Field(...)
    ikev2_psk: str = Field(...)
    ikev2_user: str = Field(default="vpnuser")
    ikev2_password: str = Field(...)

    
    # Security Settings
    encryption_level: int = Field(...)
    dns_servers: str = Field(...)
    kill_switch_enabled: bool = Field(...)
    
    # Logging
    log_level: str = Field(...)
    log_retention_days: int = Field(...)
    
    # Monitoring
    monitoring_enabled: bool = Field(...)
    bandwidth_limit_mb: int = Field(...)
    
    # JWT Configuration
    jwt_secret_key: str = Field(...)
    jwt_algorithm: str = Field(...)
    jwt_expire_minutes: int = Field(...)

    # Set to true once the app is only reachable over HTTPS (e.g. behind
    # Cloudflare Tunnel or a TLS-terminating reverse proxy). Browsers refuse
    # to send secure cookies over plain HTTP, so flipping this on for a
    # LAN-only plain-HTTP deployment would silently break login.
    cookie_secure: bool = Field(default=False)
    
    # Local Network Configuration
    local_ip: str = Field(...)
    local_ipv6: str = Field(...)
    
    # Previous IPs for rotation
    previous_ips: str = Field(...)
    
    # Database Configuration
    database_url: str = Field(...)
    
    # Configuration paths
    wireguard_config_path: str = Field(...)
    openvpn_config_path: str = Field(...)
    ikev2_config_path: str = Field(...)
    
    @field_validator('wireguard_dns', 'dns_servers', 'previous_ips')
    def parse_comma_separated(cls, v):
        """Parse comma-separated strings into lists"""
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(',') if ip.strip()]
        return v
    
    @field_validator('encryption_level')
    def validate_encryption_level(cls, v):
        """Validate encryption level"""
        if v not in [128, 256]:
            raise ValueError("Encryption level must be 128 or 256")
        return v
    
    @field_validator('openvpn_protocol')
    def validate_openvpn_protocol(cls, v):
        """Validate OpenVPN protocol"""
        if v not in ['udp', 'tcp']:
            raise ValueError("OpenVPN protocol must be 'udp' or 'tcp'")
        return v

    @field_validator('jwt_secret_key', 'web_password', 'ikev2_psk', 'ikev2_password')
    @classmethod
    def reject_placeholder_secrets(cls, v, info):
        placeholder = _PLACEHOLDER_SECRETS.get(info.field_name)
        if placeholder and v == placeholder:
            raise ValueError(
                f"{info.field_name} is still set to the example placeholder value from "
                f"env.example. Set a real secret before starting the service."
            )
        return v

    @field_validator('web_password', 'jwt_secret_key')
    @classmethod
    def warn_on_weak_secret(cls, v, info):
        min_len = 12 if info.field_name == "web_password" else 32
        if len(v) < min_len:
            print(
                f"WARNING: {info.field_name} is only {len(v)} characters - "
                f"recommend at least {min_len} for a self-hosted VPN admin panel."
            )
        return v
    
    @property
    def dns_servers_list(self) -> List[str]:
        """Get DNS servers as a list"""
        if isinstance(self.dns_servers, str):
            return [ip.strip() for ip in self.dns_servers.split(',') if ip.strip()]
        return self.dns_servers
    
    @property
    def previous_ips_list(self) -> List[str]:
        """Get previous IPs as a list"""
        if isinstance(self.previous_ips, str):
            return [ip.strip() for ip in self.previous_ips.split(',') if ip.strip()]
        return self.previous_ips
    
    @property
    def wireguard_dns_list(self) -> List[str]:
        """Get WireGuard DNS servers as a list"""
        if isinstance(self.wireguard_dns, str):
            return [ip.strip() for ip in self.wireguard_dns.split(',') if ip.strip()]
        return self.wireguard_dns
    
    def get_endpoint_urls(self) -> dict:
        """Get all endpoint URLs for the VPN server"""
        return {
            "wireguard": f"{self.server_ip}:{self.wireguard_port}",
            "openvpn": f"{self.server_ip}:{self.openvpn_port}",
            "ikev2": f"{self.server_ip}:500"
        }
    
    def get_available_protocols(self) -> List[str]:
        """Get list of enabled protocols"""
        protocols = []
        if self.wireguard_enabled:
            protocols.append("wireguard")
        if self.openvpn_enabled:
            protocols.append("openvpn")
        if self.ikev2_enabled:
            protocols.append("ikev2")
        return protocols
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

# Global settings instance
settings = Settings()  # Loads all required fields from environment variables

# Export commonly used settings for convenience
SERVER_IP = settings.server_ip

WEB_USERNAME = settings.web_username
WEB_PASSWORD = settings.web_password
JWT_SECRET_KEY = settings.jwt_secret_key
DATABASE_URL = settings.database_url

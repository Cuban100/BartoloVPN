#!/usr/bin/env python3
"""
Configuration management for BartoloVPN
Loads all settings from environment variables
"""

import os
from typing import List, Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Server Configuration
    server_ip: str = Field(..., env="SERVER_IP")
    domain: Optional[str] = Field("", env="DOMAIN")
    
    # Web Interface

    web_username: str = Field("admin", env="WEB_USERNAME")
    web_password: str = Field(..., env="WEB_PASSWORD")
    
    # WireGuard Configuration
    wireguard_enabled: bool = Field(True, env="WIREGUARD_ENABLED")
    wireguard_port: int = Field(51820, env="WIREGUARD_PORT")
    wireguard_peers: int = Field(10, env="WIREGUARD_PEERS")
    wireguard_dns: str = Field("1.1.1.1,8.8.8.8", env="WIREGUARD_DNS")
    wireguard_subnet: str = Field("10.13.13.0", env="WIREGUARD_SUBNET")
    wireguard_allowed_ips: str = Field("0.0.0.0/0", env="WIREGUARD_ALLOWED_IPS")
    
    # OpenVPN Configuration
    openvpn_enabled: bool = Field(True, env="OPENVPN_ENABLED")
    openvpn_port: int = Field(1194, env="OPENVPN_PORT")
    openvpn_protocol: str = Field("udp", env="OPENVPN_PROTOCOL")
    openvpn_cipher: str = Field("AES-256-GCM", env="OPENVPN_CIPHER")
    openvpn_auth: str = Field("SHA256", env="OPENVPN_AUTH")
    
    # IKEv2 Configuration
    ikev2_enabled: bool = Field(True, env="IKEV2_ENABLED")
    ikev2_psk: str = Field(..., env="IKEV2_PSK")

    
    # Security Settings
    encryption_level: int = Field(256, env="ENCRYPTION_LEVEL")
    dns_servers: str = Field("1.1.1.1,8.8.8.8", env="DNS_SERVERS")
    kill_switch_enabled: bool = Field(True, env="KILL_SWITCH_ENABLED")
    
    # Logging
    log_level: str = Field("INFO", env="LOG_LEVEL")
    log_retention_days: int = Field(30, env="LOG_RETENTION_DAYS")
    
    # Monitoring
    monitoring_enabled: bool = Field(True, env="MONITORING_ENABLED")
    bandwidth_limit_mb: int = Field(1000, env="BANDWIDTH_LIMIT_MB")
    
    # JWT Configuration
    jwt_secret_key: str = Field(..., env="JWT_SECRET_KEY")
    jwt_algorithm: str = Field("HS256", env="JWT_ALGORITHM")
    jwt_expire_minutes: int = Field(1440, env="JWT_EXPIRE_MINUTES")  # 24 hours
    
    # Local Network Configuration
    local_ip: str = Field("", env="LOCAL_IP")
    local_ipv6: str = Field("", env="LOCAL_IPV6")
    
    # Previous IPs for rotation
    previous_ips: str = Field("", env="PREVIOUS_IPS")
    
    # Database Configuration
    database_url: str = Field("sqlite+aiosqlite:///./bartolovpn.db", env="DATABASE_URL")
    
    # Configuration paths
    wireguard_config_path: str = Field("/config/wireguard", env="WIREGUARD_CONFIG_PATH")
    openvpn_config_path: str = Field("/config/openvpn", env="OPENVPN_CONFIG_PATH")
    ikev2_config_path: str = Field("/config/ikev2", env="IKEV2_CONFIG_PATH")
    
    @validator('wireguard_dns', 'dns_servers', 'previous_ips')
    def parse_comma_separated(cls, v):
        """Parse comma-separated strings into lists"""
        if isinstance(v, str):
            return [ip.strip() for ip in v.split(',') if ip.strip()]
        return v
    
    @validator('encryption_level')
    def validate_encryption_level(cls, v):
        """Validate encryption level"""
        if v not in [128, 256]:
            raise ValueError("Encryption level must be 128 or 256")
        return v
    
    @validator('openvpn_protocol')
    def validate_openvpn_protocol(cls, v):
        """Validate OpenVPN protocol"""
        if v not in ['udp', 'tcp']:
            raise ValueError("OpenVPN protocol must be 'udp' or 'tcp'")
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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

# Global settings instance
settings = Settings()

# Export commonly used settings for convenience
SERVER_IP = settings.server_ip

WEB_USERNAME = settings.web_username
WEB_PASSWORD = settings.web_password
JWT_SECRET_KEY = settings.jwt_secret_key
DATABASE_URL = settings.database_url

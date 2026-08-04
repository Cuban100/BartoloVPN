#!/usr/bin/env python3
"""
Database models and configuration for BartoloVPN
"""

import os
from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
import json

Base = declarative_base()

class User(Base):
    """User model for VPN management"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="user")  # admin, user
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    preferences = Column(JSON, default=dict)  # User preferences
    
    # Relationships
    vpn_configs = relationship("VPNConfig", back_populates="user")
    sessions = relationship("UserSession", back_populates="user")
    usage_logs = relationship("UsageLog", back_populates="user")

class VPNConfig(Base):
    """VPN configuration for each user"""
    __tablename__ = "vpn_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    protocol = Column(String(20), nullable=False)  # wireguard, openvpn, ikev2
    config_name = Column(String(100), nullable=False)
    config_data = Column(Text, nullable=False)  # Actual config content
    qr_code = Column(Text, nullable=True)  # Base64 QR code
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="vpn_configs")

class UserSession(Base):
    """User session tracking"""
    __tablename__ = "user_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")

class UsageLog(Base):
    """VPN usage logging"""
    __tablename__ = "usage_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    protocol = Column(String(20), nullable=False)
    bytes_sent = Column(Integer, default=0)
    bytes_received = Column(Integer, default=0)
    connection_start = Column(DateTime, default=datetime.utcnow)
    connection_end = Column(DateTime, nullable=True)
    ip_address = Column(String(45), nullable=True)
    country = Column(String(2), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="usage_logs")

class ServerEndpoint(Base):
    """VPN server endpoints for IP rotation"""
    __tablename__ = "server_endpoints"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(45), nullable=False)
    port = Column(Integer, nullable=False)
    protocol = Column(String(20), nullable=False)  # wireguard, openvpn, ikev2
    country = Column(String(2), nullable=True)
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=1)  # Lower number = higher priority
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)

class DnsQueryLog(Base):
    """DNS query activity per WireGuard peer (domain-level browsing visibility)"""
    __tablename__ = "dns_query_logs"

    id = Column(Integer, primary_key=True, index=True)
    peer_ip = Column(String(45), nullable=False, index=True)
    domain = Column(String(255), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

class IPRotation(Base):
    """IP rotation configuration"""
    __tablename__ = "ip_rotations"

    id = Column(Integer, primary_key=True, index=True)
    endpoint_id = Column(Integer, ForeignKey("server_endpoints.id"), nullable=False)
    rotation_interval = Column(Integer, default=3600)  # seconds
    last_rotation = Column(DateTime, nullable=True)
    next_rotation = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, default=True)

class Region(Base):
    """A real WireGuard server location a peer can connect through.

    Deliberately separate from ServerEndpoint/IPRotation above: those model
    "rotate this one endpoint's IP for evasion" (their own IP-rotation
    logic is an admitted placeholder, api/ip_rotation.py) and aren't wired
    into peer creation at all today. Region models "one of N real,
    permanently-distinct servers a user picks to exit from" - a different
    concept, and conflating the two tables would make both harder to
    reason about.
    """
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(30), unique=True, nullable=False, index=True)  # "local", "de-fra1"
    display_name = Column(String(100), nullable=False)  # "Germany - Frankfurt"
    country_code = Column(String(2), nullable=False)
    city = Column(String(100), nullable=True)

    # True only for the single seeded row representing this box's own
    # local WireGuard server - peer routes branch on this instead of
    # calling out to an agent, since the local server is managed in-process
    # (see VPNManager in main.py) and was working before this feature existed.
    is_local = Column(Boolean, default=False)

    # Null for the local region. For remote regions, agent_url points at
    # the region agent's HTTPS endpoint and agent_key_encrypted holds its
    # API key, Fernet-encrypted at rest (see region_service.py) - never
    # stored or logged in plaintext.
    agent_url = Column(String(255), nullable=True)
    agent_key_encrypted = Column(Text, nullable=True)

    wireguard_endpoint_host = Column(String(255), nullable=False)
    wireguard_endpoint_port = Column(Integer, default=51820)

    is_active = Column(Boolean, default=True)
    health_status = Column(String(20), default="unknown")  # unknown, healthy, unreachable
    last_health_check = Column(DateTime, nullable=True)
    last_health_error = Column(Text, nullable=True)
    peer_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

# Import configuration
from config import settings

# For sqlite, ensure the database file's directory actually exists - sqlite
# will happily create the .db file itself but not its parent directory, and
# this app doesn't otherwise guarantee that directory is ever created
if settings.database_url.startswith("sqlite"):
    _db_path = settings.database_url.split("///", 1)[-1]
    _db_dir = os.path.dirname(_db_path)
    if _db_dir:
        os.makedirs(_db_dir, exist_ok=True)

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Dependency to get database session
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Database initialization
async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Helper functions
async def create_default_admin():
    """Create default admin user if not exists"""
    from passlib.context import CryptContext
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    async with AsyncSessionLocal() as session:
        # Check if admin exists
        admin = await session.get(User, 1)
        if not admin:
            admin_user = User(
                id=1,
                username=settings.web_username,
                email=f"{settings.web_username}@bartolovpn.com",
                hashed_password=pwd_context.hash(settings.web_password),
                role="admin",
                is_active=True,
                created_at=datetime.utcnow(),
                preferences={
                    "theme": "dark",
                    "language": "en",
                    "notifications": True,
                    "auto_connect": False
                }
            )
            session.add(admin_user)
            await session.commit()
            print(f"Created default admin user ({settings.web_username})")

async def create_default_endpoints():
    """Create default server endpoints"""
    async with AsyncSessionLocal() as session:
        # Check if endpoints exist
        result = await session.execute(select(ServerEndpoint))
        endpoints = result.scalars().all()
        if not endpoints:
            default_endpoints = [
                ServerEndpoint(
                    name="Primary WireGuard",
                    ip_address=settings.server_ip,
                    port=settings.wireguard_port,
                    protocol="wireguard",
                    country="US",
                    priority=1
                ),
                ServerEndpoint(
                    name="Primary OpenVPN",
                    ip_address=settings.server_ip,
                    port=settings.openvpn_port,
                    protocol="openvpn",
                    country="US",
                    priority=1
                ),
                ServerEndpoint(
                    name="Primary IKEv2",
                    ip_address=settings.server_ip,
                    port=500,
                    protocol="ikev2",
                    country="US",
                    priority=1
                )
            ]
            
            for endpoint in default_endpoints:
                session.add(endpoint)

            await session.commit()
            print("Created default server endpoints")

async def create_default_region():
    """Register this box's own local WireGuard server as the 'local'
    Region, if it doesn't already exist. Peer routes treat is_local=True
    as the signal to keep using the existing in-process VPNManager code
    path instead of dispatching to a region agent."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Region).where(Region.is_local == True))
        local_region = result.scalar_one_or_none()
        if not local_region:
            session.add(Region(
                slug="local",
                display_name="Local (this server)",
                country_code="US",
                is_local=True,
                agent_url=None,
                agent_key_encrypted=None,
                wireguard_endpoint_host=settings.server_ip,
                wireguard_endpoint_port=settings.wireguard_port,
                is_active=True,
                health_status="healthy",
            ))
            await session.commit()
            print("Created default local region")

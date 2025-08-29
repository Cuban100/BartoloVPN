#!/usr/bin/env python3
"""
Database models and configuration for BartoloVPN
"""

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

class IPRotation(Base):
    """IP rotation configuration"""
    __tablename__ = "ip_rotations"
    
    id = Column(Integer, primary_key=True, index=True)
    endpoint_id = Column(Integer, ForeignKey("server_endpoints.id"), nullable=False)
    rotation_interval = Column(Integer, default=3600)  # seconds
    last_rotation = Column(DateTime, nullable=True)
    next_rotation = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, default=True)

# Import configuration
from config import settings

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

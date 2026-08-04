#!/usr/bin/env python3
"""
Configuration for a BartoloVPN region agent.

A region agent runs on one remote VPS, alongside its own WireGuard
container, and owns that box's peer lifecycle. It has no database, no
user auth, and no knowledge of other regions - it's intentionally the
smallest possible service that can create/list/delete WireGuard peers
on the box it's running on.
"""

import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_AGENT_KEY = "change-this-agent-key"


class Settings(BaseSettings):
    """Region agent settings, loaded from environment variables."""

    # The public IP (or hostname) clients should use as the WireGuard
    # Endpoint for peers created on this box.
    server_ip: str = Field(...)
    wireguard_port: int = Field(default=51820)

    # Shared secret the central BartoloVPN dashboard must present as
    # X-Agent-Key on every authenticated request.
    agent_api_key: str = Field(...)

    wireguard_config_path: str = Field(default="/config/wireguard")
    wireguard_subnet_prefix: str = Field(default="10.13.13")

    @field_validator("agent_api_key")
    @classmethod
    def reject_placeholder_key(cls, v):
        if v == _PLACEHOLDER_AGENT_KEY:
            raise ValueError(
                "agent_api_key is still set to the example placeholder value "
                "from env.example. Generate a real secret (e.g. `openssl rand "
                "-hex 32`) before starting the agent."
            )
        if len(v) < 32:
            print(
                f"WARNING: agent_api_key is only {len(v)} characters - "
                "recommend at least 32 for a secret that crosses the public internet."
            )
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()  # Loads all required fields from environment variables

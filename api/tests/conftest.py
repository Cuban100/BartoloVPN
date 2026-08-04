"""
Test configuration: sets a self-contained env (temp sqlite DB, dummy
secrets) before any application module is imported, since config.py builds
its Settings() at import time and would otherwise read the real .env.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parent.parent
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

_TEST_DIR = tempfile.mkdtemp(prefix="bartolovpn_test_")
for _sub in ("wireguard", "openvpn", "ikev2"):
    os.makedirs(os.path.join(_TEST_DIR, _sub), exist_ok=True)

os.environ["SERVER_IP"] = "127.0.0.1"
os.environ["DOMAIN"] = "test.local"
os.environ["WEB_USERNAME"] = "testadmin"
os.environ["WEB_PASSWORD"] = "TestAdminPassw0rd!"
os.environ["WIREGUARD_ENABLED"] = "true"
os.environ["WIREGUARD_PORT"] = "51820"
os.environ["WIREGUARD_PEERS"] = "10"
os.environ["WIREGUARD_DNS"] = "1.1.1.1,8.8.8.8"
os.environ["WIREGUARD_SUBNET"] = "10.13.13.0"
os.environ["WIREGUARD_ALLOWED_IPS"] = "0.0.0.0/0"
os.environ["OPENVPN_ENABLED"] = "true"
os.environ["OPENVPN_PORT"] = "1194"
os.environ["OPENVPN_PROTOCOL"] = "udp"
os.environ["OPENVPN_CIPHER"] = "AES-256-GCM"
os.environ["OPENVPN_AUTH"] = "SHA256"
os.environ["IKEV2_ENABLED"] = "true"
os.environ["IKEV2_PSK"] = "test-psk-not-a-real-secret"
os.environ["IKEV2_USER"] = "vpnuser"
os.environ["IKEV2_PASSWORD"] = "test-ikev2-password"
os.environ["ENCRYPTION_LEVEL"] = "256"
os.environ["DNS_SERVERS"] = "1.1.1.1,8.8.8.8"
os.environ["KILL_SWITCH_ENABLED"] = "true"
os.environ["LOG_LEVEL"] = "INFO"
os.environ["LOG_RETENTION_DAYS"] = "30"
os.environ["MONITORING_ENABLED"] = "true"
os.environ["BANDWIDTH_LIMIT_MB"] = "1000"
os.environ["JWT_SECRET_KEY"] = "test-jwt-secret-key-not-for-production-use-only"
os.environ["JWT_ALGORITHM"] = "HS256"
os.environ["JWT_EXPIRE_MINUTES"] = "60"
os.environ["REGION_AGENT_ENCRYPTION_KEY"] = "test-region-agent-encryption-key-not-for-prod"
os.environ["COOKIE_SECURE"] = "false"
os.environ["LOCAL_IP"] = "127.0.0.1"
os.environ["LOCAL_IPV6"] = "::1"
os.environ["PREVIOUS_IPS"] = ""
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DIR}/test.db"
os.environ["WIREGUARD_CONFIG_PATH"] = os.path.join(_TEST_DIR, "wireguard")
os.environ["OPENVPN_CONFIG_PATH"] = os.path.join(_TEST_DIR, "openvpn")
os.environ["IKEV2_CONFIG_PATH"] = os.path.join(_TEST_DIR, "ikev2")

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402

ADMIN_USERNAME = os.environ["WEB_USERNAME"]
ADMIN_PASSWORD = os.environ["WEB_PASSWORD"]


@pytest.fixture(scope="session")
def client():
    """Runs the app's real lifespan (DB init, default admin creation)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_token(client):
    resp = client.post("/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture()
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}

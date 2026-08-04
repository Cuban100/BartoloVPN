"""Tests for the Settings page's /settings API - previously entirely
unimplemented (the Settings page's Save button had no backend at all)."""

import main
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def test_get_settings_returns_defaults_on_first_load(client, admin_headers):
    resp = client.get("/settings", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["timezone"] == "UTC"
    assert body["dns_servers"] == "1.1.1.1,8.8.8.8"
    assert body["encryption_level"] == 256
    assert body["kill_switch_enabled"] is True
    assert body["log_level"] == "INFO"
    assert body["log_retention_days"] == 30
    assert body["oracle_enabled"] is False
    assert body["oracle_api_key_configured"] is False
    # Read-only, sourced from config/.env, not the settings table
    assert body["server_ip"] == "127.0.0.1"
    assert body["domain"] == "test.local"


def test_update_general_settings(client, admin_headers):
    resp = client.put(
        "/settings",
        json={"timezone": "America/New_York", "dns_servers": "9.9.9.9", "log_retention_days": 90},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "America/New_York"
    assert body["dns_servers"] == "9.9.9.9"
    assert body["log_retention_days"] == 90

    # Confirm it actually persisted, not just echoed back
    get_resp = client.get("/settings", headers=admin_headers)
    assert get_resp.json()["timezone"] == "America/New_York"


def test_non_admin_cannot_update_settings(client):
    client.post("/auth/register", json={"username": "settings_test_user", "password": "SettingsTestPassw0rd!"})
    login = client.post("/auth/login", json={"username": "settings_test_user", "password": "SettingsTestPassw0rd!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.put("/settings", json={"timezone": "UTC"}, headers=headers)
    assert resp.status_code == 403


def test_oracle_api_key_never_returned_but_configured_flag_updates(client, admin_headers):
    resp = client.put(
        "/settings",
        json={
            "oracle_enabled": True,
            "oracle_tenancy_ocid": "ocid1.tenancy.oc1..fake",
            "oracle_user_ocid": "ocid1.user.oc1..fake",
            "oracle_fingerprint": "aa:bb:cc:dd",
            "oracle_api_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
            "oracle_region": "us-ashburn-1",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["oracle_enabled"] is True
    assert body["oracle_tenancy_ocid"] == "ocid1.tenancy.oc1..fake"
    assert body["oracle_api_key_configured"] is True
    # The actual key content must never appear anywhere in the response
    assert "BEGIN PRIVATE KEY" not in resp.text
    assert "oracle_api_key" not in body


def test_put_settings_strips_whitespace_from_pasted_values(client, admin_headers):
    # An invisible trailing newline/space from copy-pasting an OCID looks
    # correct in the UI but silently fails Oracle API authentication -
    # this must never reach the stored value.
    resp = client.put(
        "/settings",
        json={
            "oracle_tenancy_ocid": "  ocid1.tenancy.oc1..whitespacetest\n",
            "oracle_user_ocid": "ocid1.user.oc1..whitespacetest \t",
            "oracle_fingerprint": " aa:bb:cc:dd \n",
            "oracle_api_key": "\n-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n\n",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["oracle_tenancy_ocid"] == "ocid1.tenancy.oc1..whitespacetest"
    assert body["oracle_user_ocid"] == "ocid1.user.oc1..whitespacetest"
    assert body["oracle_fingerprint"] == "aa:bb:cc:dd"


def test_omitting_oracle_api_key_leaves_stored_key_unchanged(client, admin_headers):
    # From the previous test, a key is already stored - updating an
    # unrelated field without oracle_api_key must not clear it.
    resp = client.put("/settings", json={"oracle_region": "eu-frankfurt-1"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["oracle_api_key_configured"] is True
    assert resp.json()["oracle_region"] == "eu-frankfurt-1"


def test_ssh_keys_endpoint_returns_empty_list_when_no_ssh_dir_mounted(client, admin_headers):
    # Test environment has no /ssh-keys bind mount (that's production-only,
    # see docker-compose.yml) - must degrade gracefully, not error.
    resp = client.get("/settings/ssh-keys", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"keys": []}


def test_oracle_api_key_status_not_detected_when_no_ssh_dir_mounted(client, admin_headers):
    resp = client.get("/settings/oracle-api-key", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {"detected": False, "public_key": None}


def test_oracle_api_key_import_404s_when_no_key_file_present(client, admin_headers):
    resp = client.post("/settings/oracle-api-key/import", headers=admin_headers)
    assert resp.status_code == 404


def test_oracle_api_key_import_non_admin_forbidden(client):
    login = client.post("/auth/login", json={"username": "settings_test_user", "password": "SettingsTestPassw0rd!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.post("/settings/oracle-api-key/import", headers=headers)
    assert resp.status_code == 403


def test_oracle_api_key_import_reads_real_key_and_computes_fingerprint(client, admin_headers, tmp_path, monkeypatch):
    # Generate a real RSA key pair (same shape vpn-setup.py's openssl call
    # produces) and point the endpoint's hardcoded /ssh-keys/* paths at it
    # via monkeypatch, since there's no real bind mount in this test env.
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    import hashlib
    expected_fingerprint_hex = hashlib.md5(public_der).hexdigest()
    expected_fingerprint = ":".join(expected_fingerprint_hex[i:i + 2] for i in range(0, len(expected_fingerprint_hex), 2))

    private_path = tmp_path / "oracle-api-private.pem"
    public_path = tmp_path / "oracle-api-public.pem"
    private_path.write_bytes(private_pem)
    public_path.write_bytes(private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))

    monkeypatch.setattr(main, "_ORACLE_API_PRIVATE_KEY_PATH", str(private_path))
    monkeypatch.setattr(main, "_ORACLE_API_PUBLIC_KEY_PATH", str(public_path))

    status_resp = client.get("/settings/oracle-api-key", headers=admin_headers)
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["detected"] is True
    assert "BEGIN PUBLIC KEY" in status_body["public_key"]

    import_resp = client.post("/settings/oracle-api-key/import", headers=admin_headers)
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    assert body["oracle_api_key_configured"] is True
    assert body["oracle_fingerprint"] == expected_fingerprint
    # The private key content must never appear in any response
    assert "BEGIN RSA PRIVATE KEY" not in import_resp.text

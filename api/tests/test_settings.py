"""Tests for the Settings page's /settings API - previously entirely
unimplemented (the Settings page's Save button had no backend at all)."""


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

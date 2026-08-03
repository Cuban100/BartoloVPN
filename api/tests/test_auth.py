import main as main_module

from .conftest import ADMIN_USERNAME, ADMIN_PASSWORD


def test_login_success(client):
    resp = client.post("/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_login_wrong_password(client):
    resp = client.post("/auth/login", json={"username": ADMIN_USERNAME, "password": "wrong-password"})
    assert resp.status_code == 401


def test_login_unknown_user(client):
    resp = client.post("/auth/login", json={"username": "nobody-here", "password": "whatever"})
    assert resp.status_code == 401


def test_login_sets_httponly_cookie(client):
    resp = client.post("/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert "auth_token" in resp.cookies


def test_get_current_user_requires_token(client):
    resp = client.get("/users/me")
    assert resp.status_code in (401, 403)


def test_get_current_user_with_token(client, admin_headers):
    resp = client.get("/users/me", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == ADMIN_USERNAME


def test_register_new_user(client):
    resp = client.post(
        "/auth/register",
        json={"username": "regular_user", "password": "RegularPassw0rd!"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "user"


def test_login_rate_limit_blocks_after_max_failures(client):
    """After LOGIN_RATE_LIMIT_MAX_ATTEMPTS failures from a client, the login
    endpoint itself should 429 the next attempt (even with correct
    credentials), and recover once the window is cleared.

    Uses "testclient", Starlette TestClient's fixed request.client.host,
    so this manipulates the exact same bucket the endpoint reads from
    the real HTTP call below - and cleans up in `finally` so a failure
    here can't bleed rate-limit state into other tests sharing this
    session-scoped client.
    """
    test_client_ip = "testclient"
    main_module._login_rate_limit_clear(test_client_ip)
    try:
        for _ in range(main_module.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
            main_module._login_rate_limit_record_failure(test_client_ip)

        resp = client.post("/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert resp.status_code == 429
    finally:
        main_module._login_rate_limit_clear(test_client_ip)

    resp = client.post("/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert resp.status_code == 200


def test_non_admin_cannot_self_promote_role(client):
    """Regression test for a privilege-escalation bug: a non-admin user
    could PUT their own /api/users/{id} with role=admin and it would be
    silently applied. See update_user() in main.py."""
    register_resp = client.post(
        "/auth/register",
        json={"username": "escalation_test_user", "password": "EscalateMe123!"},
    )
    assert register_resp.status_code == 200
    user_id = register_resp.json()["id"]

    login_resp = client.post(
        "/auth/login",
        json={"username": "escalation_test_user", "password": "EscalateMe123!"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    escalate_resp = client.put(
        f"/api/users/{user_id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert escalate_resp.status_code == 403

    me_resp = client.get("/users/me", headers=headers)
    assert me_resp.json()["role"] == "user"

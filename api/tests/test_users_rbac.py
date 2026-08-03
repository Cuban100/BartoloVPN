from .conftest import ADMIN_USERNAME


def _register_and_login(client, username, password="RbacTestPassw0rd!"):
    reg = client.post("/auth/register", json={"username": username, "password": password})
    assert reg.status_code == 200, reg.text
    login = client.post("/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return reg.json()["id"], {"Authorization": f"Bearer {token}"}


def test_admin_can_list_users(client, admin_headers):
    resp = client.get("/users", headers=admin_headers)
    assert resp.status_code == 200
    usernames = [u["username"] for u in resp.json()]
    assert ADMIN_USERNAME in usernames


def test_non_admin_cannot_list_users(client):
    _, headers = _register_and_login(client, "rbac_list_test_user")
    resp = client.get("/users", headers=headers)
    assert resp.status_code == 403


def test_non_admin_cannot_delete_other_user(client, admin_headers):
    victim_id, _ = _register_and_login(client, "rbac_victim_user")
    _, attacker_headers = _register_and_login(client, "rbac_attacker_user")

    resp = client.delete(f"/api/users/{victim_id}", headers=attacker_headers)
    assert resp.status_code == 403

    # Confirm the victim account is untouched
    resp = client.get(f"/api/users/{victim_id}", headers=admin_headers)
    assert resp.status_code == 200


def test_admin_cannot_delete_own_account(client, admin_headers):
    me = client.get("/users/me", headers=admin_headers).json()
    resp = client.delete(f"/api/users/{me['id']}", headers=admin_headers)
    assert resp.status_code == 400


def test_admin_can_create_and_delete_user(client, admin_headers):
    create_resp = client.post(
        "/users",
        json={"username": "rbac_admin_created_user", "password": "CreatedByAdmin1!"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 200
    user_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/api/users/{user_id}", headers=admin_headers)
    assert delete_resp.status_code == 200


def test_non_admin_can_update_own_email_but_not_role(client):
    user_id, headers = _register_and_login(client, "rbac_self_update_user")

    ok_resp = client.put(f"/api/users/{user_id}", json={"email": "me@example.com"}, headers=headers)
    assert ok_resp.status_code == 200
    assert ok_resp.json()["email"] == "me@example.com"

    role_resp = client.put(f"/api/users/{user_id}", json={"role": "admin"}, headers=headers)
    assert role_resp.status_code == 403

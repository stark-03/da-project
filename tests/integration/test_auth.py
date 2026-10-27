from app.models import Owner
from tests.conftest import make_owner


def test_register_creates_owner_and_logs_in(client, app):
    response = client.post(
        "/auth/register",
        data={"name": "Asha", "email": "Asha@Example.com", "phone": "+91 98765 43210",
              "password": "long-password", "confirm": "long-password"},
    )
    assert response.status_code == 302
    owner = Owner.query.filter_by(email="asha@example.com").one()
    assert owner.password_hash != "long-password"
    assert client.get("/").status_code == 200


def test_register_rejects_duplicate_email_and_short_password(client, owner):
    response = client.post(
        "/auth/register",
        data={"name": "X", "email": owner.email, "password": "short", "confirm": "short"},
    )
    assert response.status_code == 200
    assert Owner.query.count() == 1


def test_login_failure_is_generic(client, owner):
    response = client.post("/auth/login", data={"email": owner.email, "password": "wrong"})
    assert b"Invalid email or password" in response.data
    response = client.post("/auth/login", data={"email": "nobody@example.com", "password": "wrong"})
    assert b"Invalid email or password" in response.data


def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302 and "/auth/login" in response.headers["Location"]


def test_login_ignores_external_next_url(client, owner):
    response = client.post(
        "/auth/login?next=https://evil.example/phish",
        data={"email": owner.email, "password": "correct-horse"},
    )
    assert response.headers["Location"] == "/"


def test_logout_requires_post(logged_in):
    assert logged_in.get("/auth/logout").status_code == 405
    assert logged_in.post("/auth/logout").status_code == 302
    assert logged_in.get("/").status_code == 302


def test_other_owner_cannot_see_dashboard_entries(client, app, logged_in, document_png):
    from tests.conftest import upload

    upload(logged_in, document_png, filename="private-card.png")
    logged_in.post("/auth/logout")
    make_owner(email="other@example.com")
    client.post("/auth/login", data={"email": "other@example.com", "password": "correct-horse"})
    assert b"private-card.png" not in client.get("/").data

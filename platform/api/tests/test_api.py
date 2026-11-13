"""HTTP-level tests (need fastapi + httpx: `pip install -r requirements-dev.txt`)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.providers.fake import FakeProvider  # noqa: E402
from app.repo_memory import InMemoryRepository  # noqa: E402
from app.service import PlatformService  # noqa: E402
from tests.conftest import make_settings  # noqa: E402

IMG = "ghcr.io/acme/api@sha256:" + "a" * 64


@pytest.fixture
def client():
    service = PlatformService(InMemoryRepository(), FakeProvider(ready_after=1), make_settings())
    with TestClient(create_app(service)) as c:
        yield c


def as_user(user="alice"):
    return {"X-Authenticated-User-Id": user}


def test_requires_gateway_identity(client):
    assert client.get("/v1/account").status_code == 403
    assert client.get("/v1/account", headers=as_user("bad id")).status_code == 403
    assert client.get("/v1/health/").status_code == 200


def test_regions(client):
    r = client.get("/v1/regions", headers=as_user())
    assert r.status_code == 200 and r.json()[0] == {"id": "fsn1", "name": "Falkenstein, DE", "is_default": True}


def test_project_lifecycle_over_http(client):
    r = client.post("/v1/projects", json={"name": "Shop"}, headers=as_user())
    assert r.status_code == 202, r.text
    pid = r.json()["project"]["id"]

    # Background task ran the first reconcile: the fake server is already running
    r = client.get(f"/v1/projects/{pid}", headers=as_user())
    assert r.json()["project"]["status"] == "running"
    assert "enrollment_token_hash" not in r.json()["server"]

    r = client.post("/v1/projects", json={"name": "Second"}, headers=as_user())
    assert r.status_code == 403 and r.json()["error"]["code"] == "quota_exceeded"
    assert r.json()["message"] == "Your plan allows 1 project(s)"  # what @ogna/js shows as error.msg

    r = client.post(f"/v1/projects/{pid}/deployments", json={"backend_image": IMG}, headers=as_user())
    assert r.status_code == 201 and r.json()["version"] == 1
    r = client.post(f"/v1/projects/{pid}/deployments", json={"backend_image": "nope"}, headers=as_user())
    assert r.status_code == 422
    assert r.json()["message"].startswith("backend_image: ")
    assert r.json()["error_code"] == "invalid_request"

    r = client.get(f"/v1/projects/{pid}/desired-state", headers=as_user())
    assert r.json()["backend_image"] == IMG

    assert client.get(f"/v1/projects/{pid}", headers=as_user("mallory")).status_code == 404
    assert client.delete(f"/v1/projects/{pid}", headers=as_user()).status_code == 202

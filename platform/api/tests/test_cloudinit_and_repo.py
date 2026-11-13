import json

import pytest
import yaml

from app.cloudinit import render_user_data
from app.errors import Conflict, QuotaExceeded, RepositoryError
from app.http import HttpResponse
from app.models import Deployment, Project
from app.repo_hasura import HasuraRepository
from tests.conftest import FakeHttp, make_settings

PROJECT = Project(id="11111111-2222-3333-4444-555555555555", owner_id="alice", name="App", slug="app-abc123",
                  plan_id="hobby", server_type="cx23", region="fsn1")


# ------------------------------------------------------------------ cloud-init
def test_user_data_is_valid_cloud_config():
    text = render_user_data(PROJECT, "tok-XYZ", make_settings())
    assert text.startswith("#cloud-config\n")
    doc = yaml.safe_load(text)
    files = {f["path"]: f for f in doc["write_files"]}

    agent = files["/etc/ogna/agent.env"]
    assert agent["permissions"] == "0600"
    assert "OGNA_ENROLLMENT_TOKEN=tok-XYZ" in agent["content"]
    assert f"OGNA_PROJECT_ID={PROJECT.id}" in agent["content"]
    assert "OGNA_CONTROL_PLANE_URL=https://platform.ogna.app" in agent["content"]
    assert "PasswordAuthentication no" in files["/etc/ssh/sshd_config.d/99-ogna.conf"]["content"]
    assert doc["hostname"] == "ogna-app-abc123"
    assert any("get.docker.com" in c for c in doc["runcmd"])
    assert "ufw --force enable" in doc["runcmd"]
    # The token only appears in the root-only agent.env file
    assert text.count("tok-XYZ") == 1


def test_agent_installer_only_when_configured():
    without = yaml.safe_load(render_user_data(PROJECT, "t", make_settings()))
    assert not any("install-agent" in c for c in without["runcmd"])
    with_agent = yaml.safe_load(render_user_data(
        PROJECT, "t", make_settings(agent_install_url="https://get.ogna.app/agent.sh")))
    assert any("https://get.ogna.app/agent.sh" in c for c in with_agent["runcmd"])


# --------------------------------------------------------------- hasura repo
URL = "http://hasura:8080/v1/graphql"
pytestmark_anyio = pytest.mark.anyio


def gql(data=None, errors=None, status=200):
    body = {"data": data} if errors is None else {"errors": errors}
    return HttpResponse(status, body)


@pytest.mark.anyio
async def test_requests_use_admin_secret_and_variables():
    http = FakeHttp({("POST", URL): lambda body, _: gql({"platform_projects_by_pk": None})})
    repo = HasuraRepository(http, URL, "s3cret")
    assert await repo.get_project(PROJECT.id) is None
    req = http.requests[0]
    assert req["headers"]["x-hasura-admin-secret"] == "s3cret"
    assert req["json"]["variables"] == {"id": PROJECT.id}


@pytest.mark.anyio
async def test_quota_trigger_error_maps_to_quota_exceeded():
    errors = [{"message": "database query error",
               "extensions": {"code": "constraint-violation",
                              "internal": {"error": {"message": "quota_exceeded: plan allows 1 project(s)"}}}}]
    http = FakeHttp({("POST", URL): gql(errors=errors)})
    with pytest.raises(QuotaExceeded, match="allows 1"):
        await HasuraRepository(http, URL, "s").create_project(PROJECT)
    sent = http.requests[0]["json"]["variables"]["o"]
    assert "id" not in sent and "current_version" not in sent and sent["slug"] == "app-abc123"


@pytest.mark.anyio
async def test_slug_uniqueness_maps_to_conflict():
    errors = [{"message": 'Uniqueness violation. duplicate key value violates unique constraint "projects_slug_key"'}]
    http = FakeHttp({("POST", URL): gql(errors=errors)})
    with pytest.raises(Conflict):
        await HasuraRepository(http, URL, "s").create_project(PROJECT)


@pytest.mark.anyio
async def test_other_errors_are_repository_errors():
    http = FakeHttp({("POST", URL): gql(errors=[{"message": "field not found"}])})
    with pytest.raises(RepositoryError, match="field not found"):
        await HasuraRepository(http, URL, "s").list_projects("alice")
    http = FakeHttp({("POST", URL): HttpResponse(502, None)})
    with pytest.raises(RepositoryError):
        await HasuraRepository(http, URL, "s").list_projects("alice")


@pytest.mark.anyio
async def test_create_deployment_lets_the_trigger_assign_the_version():
    row = {"id": "d1", "project_id": PROJECT.id, "owner_id": "alice", "version": 7, "stack_version": "main",
           "backend_image": "ghcr.io/a/b:1", "config": {"A": "1"}, "reason": "deploy",
           "rolled_back_from": None, "created_by": "alice", "created_at": "2026-11-12T12:00:00+00:00"}
    http = FakeHttp({("POST", URL): gql({"insert_platform_deployments_one": row})})
    dep = await HasuraRepository(http, URL, "s").create_deployment(Deployment(
        project_id=PROJECT.id, owner_id="alice", stack_version="main", backend_image="ghcr.io/a/b:1",
        config={"A": "1"}, created_by="alice"))
    sent = http.requests[0]["json"]["variables"]["o"]
    assert sent["version"] == 0 and "id" not in sent and sent["config"] == {"A": "1"}
    assert dep.version == 7


@pytest.mark.anyio
async def test_server_token_hash_is_persisted_but_never_serialized():
    from app.models import Server
    s = Server(project_id=PROJECT.id, owner_id="alice", provider="hetzner", name="n", server_type="cx23",
               location="fsn1", enrollment_token_hash="abc")
    assert "enrollment_token_hash" not in json.loads(s.model_dump_json())
    http = FakeHttp({("POST", URL): lambda body, _: gql({"insert_platform_servers_one": {
        **body["variables"]["o"], "id": "s1", "created_at": None, "updated_at": None}})})
    await HasuraRepository(http, URL, "s").create_server(s)
    assert http.requests[0]["json"]["variables"]["o"]["enrollment_token_hash"] == "abc"

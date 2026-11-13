import asyncio
import hashlib

import pytest
from pydantic import ValidationError

from app.errors import Conflict, Forbidden, InvalidRequest, NotFound, ProviderError, QuotaExceeded
from app.models import CreateProjectRequest, DeployRequest
from app.providers import PROJECT_LABEL

pytestmark = pytest.mark.anyio

IMG = "ghcr.io/acme/api@sha256:" + "a" * 64


async def create(service, user="alice", name="My App", region=None):
    return await service.create_project(user, CreateProjectRequest(name=name, region=region))


# --------------------------------------------------------------- plans/account
async def test_account_is_created_on_default_plan(env):
    service, repo, _ = env
    view = await service.get_account("alice")
    assert view.plan.id == "hobby"
    assert (view.projects_used, view.projects_allowed, view.is_admin) == (0, 1, False)
    assert "alice" in repo.accounts


async def test_regions_come_from_settings(env):
    service, _, _ = env
    regions = service.list_regions()
    assert [(r.id, r.name, r.is_default) for r in regions] == [
        ("fsn1", "Falkenstein, DE", True), ("nbg1", "Nuremberg, DE", False)]


async def test_invalid_user_id_is_rejected(env):
    service, _, _ = env
    with pytest.raises(Forbidden):
        await service.get_account("bad id; drop table")


async def test_only_admins_change_plans_and_downgrades_respect_usage(env):
    service, _, _ = env
    with pytest.raises(Forbidden):
        await service.set_plan("alice", "alice", "pro")

    await service.set_plan("admin", "alice", "pro")
    for i in range(3):
        await create(service, name=f"app {i}")
    with pytest.raises(QuotaExceeded):
        await create(service, name="one too many")
    with pytest.raises(Conflict):
        await service.set_plan("admin", "alice", "hobby")
    with pytest.raises(InvalidRequest):
        await service.set_plan("admin", "alice", "nope")


# ------------------------------------------------------------------- projects
async def test_create_project_records_server_and_event(env):
    service, repo, _ = env
    view = await create(service)
    p = view.project
    assert p.status == "provisioning"
    assert p.slug == "my-app-000001"
    assert (p.plan_id, p.server_type, p.region) == ("hobby", "cx23", "fsn1")
    assert view.url == "https://my-app-000001.ogna.app"
    assert view.server.name == "ogna-my-app-000001" and view.server.status == "pending"
    assert [e.kind for e in repo.events] == ["created"]


async def test_quota_is_enforced_and_freed_after_deletion(env):
    service, _, _ = env
    view = await create(service)
    with pytest.raises(QuotaExceeded):
        await create(service, name="second")

    await service.delete_project("alice", view.project.id)
    await service.reconcile_project(view.project.id)   # nothing to delete yet -> deleted
    assert (await service.get_account("alice")).projects_used == 0
    await create(service, name="second")


async def test_concurrent_creates_cannot_exceed_quota(env):
    service, repo, _ = env
    await service.get_account("alice")
    # Bypass the service's friendly pre-check: the repository must hold the line
    from app.models import Project
    results = await asyncio.gather(*[
        repo.create_project(Project(id="", owner_id="alice", name=f"p{i}", slug=f"p-{i}", plan_id="hobby",
                                    server_type="cx23", region="fsn1"))
        for i in range(5)
    ], return_exceptions=True)
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert all(isinstance(r, QuotaExceeded) for r in results if isinstance(r, Exception))


async def test_unknown_region_is_rejected(env):
    service, _, _ = env
    with pytest.raises(InvalidRequest):
        await create(service, region="mars1")


async def test_projects_are_private_to_their_owner(env):
    service, _, _ = env
    view = await create(service)
    with pytest.raises(NotFound):
        await service.get_project("mallory", view.project.id)
    with pytest.raises(NotFound):
        await service.delete_project("mallory", view.project.id)
    with pytest.raises(NotFound):
        await service.deploy("mallory", view.project.id, DeployRequest(backend_image=IMG))
    assert await service.list_projects("mallory") == []


def test_project_name_validation():
    with pytest.raises(ValidationError):
        CreateProjectRequest(name="   ")
    with pytest.raises(ValidationError):
        CreateProjectRequest(name="x" * 64)
    with pytest.raises(ValidationError):
        CreateProjectRequest(name="ok", owner_id="someone-else")  # extra fields rejected


# -------------------------------------------------------------- provisioning
async def test_provisioning_creates_one_labelled_server_then_runs(env):
    service, repo, provider = env
    pid = (await create(service)).project.id

    await service.reconcile_project(pid)
    creates = [c for c in provider.calls if c[0] == "create"]
    assert len(creates) == 1
    spec = next(iter(provider.servers.values()))["spec"]
    assert spec.labels[PROJECT_LABEL] == pid
    assert (spec.server_type, spec.location) == ("cx23", "fsn1")
    assert "OGNA_ENROLLMENT_TOKEN=token-1" in spec.user_data
    server = repo.servers[pid]
    assert server.enrollment_token_hash == hashlib.sha256(b"token-1").hexdigest()
    assert server.status == "creating" and server.ipv4
    assert repo.projects[pid].status == "provisioning"

    await service.reconcile_project(pid)
    assert repo.projects[pid].status == "running"
    assert repo.servers[pid].status == "running"
    assert len([c for c in provider.calls if c[0] == "create"]) == 1  # found by label, not recreated
    assert [e.kind for e in repo.events][-2:] == ["server_created", "running"]


async def test_reconcile_once_handles_every_project_in_transition(env):
    service, repo, provider = env
    await service.set_plan("admin", "alice", "pro")
    ids = [(await create(service, name=f"a{i}")).project.id for i in range(2)]
    await service.reconcile_once()
    await service.reconcile_once()
    assert all(repo.projects[i].status == "running" for i in ids)


async def test_retryable_provider_error_keeps_provisioning(env):
    service, repo, provider = env
    pid = (await create(service)).project.id
    provider.fail_next_create = ProviderError("Hetzner resource_unavailable: try later", retryable=True)
    await service.reconcile_project(pid)
    assert repo.projects[pid].status == "provisioning"
    assert "Retrying" in repo.projects[pid].status_detail

    await service.reconcile_project(pid)  # next tick succeeds
    assert len(provider.servers) == 1


async def test_permanent_provider_error_fails_project(env):
    service, repo, provider = env
    pid = (await create(service)).project.id
    provider.fail_next_create = ProviderError("Hetzner invalid_input: server_type", retryable=False)
    await service.reconcile_project(pid)
    assert repo.projects[pid].status == "failed"
    assert repo.events[-1].kind == "failed"


async def test_provisioning_times_out(env, clock):
    service, repo, provider = env
    provider.ready_after = 10_000
    pid = (await create(service)).project.id
    await service.reconcile_project(pid)
    clock.advance(601)
    await service.reconcile_project(pid)
    assert repo.projects[pid].status == "failed"
    assert "timeout" in repo.projects[pid].status_detail


async def test_delete_removes_server_then_project(env):
    service, repo, provider = env
    pid = (await create(service)).project.id
    await service.reconcile_project(pid)
    await service.reconcile_project(pid)
    sid = repo.servers[pid].provider_server_id

    await service.delete_project("alice", pid)
    await service.reconcile_project(pid)
    assert ("delete", sid) in provider.calls
    assert repo.projects[pid].status == "deleting"

    await service.reconcile_project(pid)
    assert repo.projects[pid].status == "deleted"
    assert repo.servers[pid].status == "deleted"
    with pytest.raises(NotFound):
        await service.get_project("alice", pid)
    assert await service.list_projects("alice") == []


async def test_concurrent_reconciles_create_a_single_server(env):
    service, _, provider = env
    pid = (await create(service)).project.id
    await asyncio.gather(*[service.reconcile_project(pid) for _ in range(5)])
    assert len([c for c in provider.calls if c[0] == "create"]) == 1


# ----------------------------------------------------------------- deployments
async def test_deploy_versions_rollback_and_desired_state(env):
    service, repo, _ = env
    pid = (await create(service)).project.id

    empty = await service.desired_state("alice", pid)
    assert (empty.version, empty.backend_image) == (0, None)

    d1 = await service.deploy("alice", pid, DeployRequest(backend_image=IMG, config={"LOG_LEVEL": "info"}))
    d2 = await service.deploy("alice", pid, DeployRequest(backend_image="ghcr.io/acme/api:2.0.0", stack_version="1.4.2"))
    assert (d1.version, d1.stack_version, d2.version) == (1, "main", 2)
    assert "not digest" in repo.events[-1].message  # tag-only image is flagged

    with pytest.raises(Conflict):
        await service.rollback("alice", pid, 2)
    with pytest.raises(NotFound):
        await service.rollback("alice", pid, 9)

    d3 = await service.rollback("alice", pid, 1)
    assert (d3.version, d3.reason, d3.rolled_back_from, d3.backend_image) == (3, "rollback", 1, IMG)
    assert d3.config == {"LOG_LEVEL": "info"}

    state = await service.desired_state("alice", pid)
    assert (state.version, state.backend_image, state.stack_version) == (3, IMG, "main")
    assert state.domains == [f"{repo.projects[pid].slug}.ogna.app"]
    assert state.server == {"provider": "fake", "server_type": "cx23", "location": "fsn1"}

    history = await service.list_deployments("alice", pid)
    assert [d.version for d in history] == [3, 2, 1]
    view = await service.get_project("alice", pid)
    assert view.current_deployment.version == 3


async def test_concurrent_deploys_get_distinct_versions(env):
    service, _, _ = env
    pid = (await create(service)).project.id
    deps = await asyncio.gather(*[
        service.deploy("alice", pid, DeployRequest(backend_image=f"ghcr.io/acme/api:{i}.0.0")) for i in range(10)
    ])
    assert sorted(d.version for d in deps) == list(range(1, 11))


async def test_cannot_deploy_to_a_project_being_deleted(env):
    service, _, _ = env
    pid = (await create(service)).project.id
    await service.delete_project("alice", pid)
    with pytest.raises(Conflict):
        await service.deploy("alice", pid, DeployRequest(backend_image=IMG))


@pytest.mark.parametrize("bad", [
    {"backend_image": "ghcr.io/acme/api"},                      # no tag/digest
    {"backend_image": "ghcr.io/acme/API:1.0"},                  # uppercase repo
    {"backend_image": "ghcr.io/acme/api:1.0; rm -rf /"},        # injection
    {"backend_image": IMG, "stack_version": "latest"},
    {"backend_image": IMG, "config": {"lowercase": "x"}},
    {"backend_image": IMG, "config": {"HASURA_GRAPHQL_ADMIN_SECRET": "x"}},
    {"backend_image": IMG, "config": {"OGNA_INTERNAL_JWT_SECRET": "x"}},
    {"backend_image": IMG, "config": {f"K{i}": "v" for i in range(51)}},
    {"backend_image": IMG, "extra": "field"},
])
def test_deploy_request_validation(bad):
    with pytest.raises(ValidationError):
        DeployRequest(**bad)


@pytest.mark.parametrize("good", [
    "ghcr.io/acme/api:1.2.3",
    "registry.example.com:5000/team/svc:v2",
    "acme/api:latest",
    IMG,
    "ghcr.io/acme/api:1.0@sha256:" + "b" * 64,
])
def test_deploy_request_accepts_images(good):
    assert DeployRequest(backend_image=good).backend_image == good

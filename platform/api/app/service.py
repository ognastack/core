"""Control-plane business logic, independent of HTTP and storage details."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Callable, Optional

from .cloudinit import render_user_data
from .config import Settings
from .errors import Conflict, Forbidden, InvalidRequest, NotFound, ProviderError, QuotaExceeded
from .models import (
    AccountView, CreateProjectRequest, DeployRequest, Deployment, DesiredState, Event,
    Plan, Project, ProjectView, Server,
)
from .providers import PROJECT_LABEL, Provider, ProviderServer, ServerSpec
from .repository import Repository

log = logging.getLogger("ogna.platform")

USER_ID = re.compile(r"^[A-Za-z0-9_.@-]{1,128}$")
_IN_TRANSITION = ("provisioning", "deleting")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return base or "project"


class PlatformService:
    def __init__(self, repo: Repository, provider: Provider, settings: Settings, *,
                 clock: Callable[[], datetime] = utcnow,
                 token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
                 suffix_factory: Callable[[], str] = lambda: secrets.token_hex(3)):
        self.repo = repo
        self.provider = provider
        self.settings = settings
        self._clock = clock
        self._token = token_factory
        self._suffix = suffix_factory
        # One reconcile at a time per project in this process. Running several
        # API replicas would need a database lease instead (see README).
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ helpers
    def is_admin(self, user_id: str) -> bool:
        return user_id in self.settings.admin_user_ids

    async def _event(self, project: Project, kind: str, message: str) -> None:
        try:
            await self.repo.add_event(Event(project_id=project.id, owner_id=project.owner_id,
                                            kind=kind, message=message))
        except Exception:  # events are best-effort; never fail the operation for them
            log.exception("could not record event %s for project %s", kind, project.id)

    async def _default_plan(self) -> Plan:
        plans = await self.repo.list_plans()
        plan = next((p for p in plans if p.is_default), None) or (plans[0] if plans else None)
        if plan is None:
            raise Conflict("No plans are configured")
        return plan

    async def _ensure_account(self, user_id: str):
        if not USER_ID.match(user_id):
            raise Forbidden("Invalid user id")
        account = await self.repo.get_account(user_id)
        if account is None:
            account = await self.repo.create_account(user_id, (await self._default_plan()).id)
        return account

    async def _owned_project(self, user_id: str, project_id: str) -> Project:
        project = await self.repo.get_project(project_id)
        # Same answer for "doesn't exist" and "not yours": don't leak other users' ids
        if project is None or project.owner_id != user_id or project.status == "deleted":
            raise NotFound("Project not found")
        return project

    def _url(self, project: Project) -> str:
        return f"https://{project.slug}.{self.settings.base_domain}"

    async def _view(self, project: Project) -> ProjectView:
        server = await self.repo.get_server(project.id)
        current = (await self.repo.get_deployment(project.id, project.current_version)
                   if project.current_version else None)
        return ProjectView(project=project, server=server, current_deployment=current, url=self._url(project))

    # ------------------------------------------------------------ plans/account
    async def list_plans(self) -> list[Plan]:
        return await self.repo.list_plans()

    async def get_account(self, user_id: str) -> AccountView:
        account = await self._ensure_account(user_id)
        plan = await self.repo.get_plan(account.plan_id)
        used = await self.repo.count_active_projects(user_id)
        return AccountView(user_id=user_id, plan=plan, projects_used=used,
                           projects_allowed=plan.max_projects, is_admin=self.is_admin(user_id))

    async def set_plan(self, admin_id: str, target_user_id: str, plan_id: str) -> AccountView:
        if not self.is_admin(admin_id):
            raise Forbidden("Only platform admins can change plans")
        plan = await self.repo.get_plan(plan_id)
        if plan is None or not plan.active:
            raise InvalidRequest(f"Unknown plan {plan_id!r}")
        await self._ensure_account(target_user_id)
        used = await self.repo.count_active_projects(target_user_id)
        if used > plan.max_projects:
            raise Conflict(f"User has {used} projects; plan {plan.id!r} allows {plan.max_projects}")
        await self.repo.set_account_plan(target_user_id, plan.id)
        return await self.get_account(target_user_id)

    # ----------------------------------------------------------------- projects
    async def create_project(self, user_id: str, req: CreateProjectRequest) -> ProjectView:
        account = await self._ensure_account(user_id)
        plan = await self.repo.get_plan(account.plan_id)
        region = req.region or self.settings.default_region
        if region not in self.settings.regions:
            raise InvalidRequest(f"Region must be one of: {', '.join(self.settings.regions)}")

        # Friendly early answer; the database trigger is what actually guarantees it
        if await self.repo.count_active_projects(user_id) >= plan.max_projects:
            raise QuotaExceeded(f"Your plan allows {plan.max_projects} project(s)")

        project: Optional[Project] = None
        for _ in range(3):  # random suffix makes slug collisions rare; retry if one happens
            slug = f"{slugify(req.name)}-{self._suffix()}"
            try:
                project = await self.repo.create_project(Project(
                    id="", owner_id=user_id, name=req.name, slug=slug, plan_id=plan.id,
                    server_type=plan.server_type, region=region, status="provisioning",
                ))
                break
            except Conflict:
                continue
        if project is None:
            raise Conflict("Could not allocate a project slug, try again")

        await self.repo.create_server(Server(
            project_id=project.id, owner_id=user_id, provider=self.provider.name,
            name=f"ogna-{project.slug}", server_type=plan.server_type, location=region,
        ))
        await self._event(project, "created", f"Project created on plan {plan.id} ({plan.server_type}, {region})")
        return await self._view(project)

    async def list_projects(self, user_id: str) -> list[ProjectView]:
        return [await self._view(p) for p in await self.repo.list_projects(user_id)]

    async def get_project(self, user_id: str, project_id: str) -> ProjectView:
        return await self._view(await self._owned_project(user_id, project_id))

    async def list_events(self, user_id: str, project_id: str) -> list[Event]:
        await self._owned_project(user_id, project_id)
        return await self.repo.list_events(project_id)

    async def delete_project(self, user_id: str, project_id: str) -> ProjectView:
        project = await self._owned_project(user_id, project_id)
        if project.status != "deleting":
            project = await self.repo.update_project(project.id, status="deleting", status_detail=None)
            await self._event(project, "deleting", "Deletion requested")
        return await self._view(project)

    async def sync_project(self, user_id: str, project_id: str) -> ProjectView:
        project = await self._owned_project(user_id, project_id)
        await self.reconcile_project(project.id)
        return await self._view(await self.repo.get_project(project.id))

    # -------------------------------------------------------------- deployments
    async def deploy(self, user_id: str, project_id: str, req: DeployRequest) -> Deployment:
        project = await self._owned_project(user_id, project_id)
        if project.status == "deleting":
            raise Conflict("Project is being deleted")
        deployment = await self.repo.create_deployment(Deployment(
            project_id=project.id, owner_id=user_id, stack_version=req.stack_version or self.settings.default_stack_version,
            backend_image=req.backend_image, config=req.config, reason="deploy", created_by=user_id,
        ))
        pinned = "@sha256:" in deployment.backend_image
        await self._event(project, "deployed",
                          f"v{deployment.version}: {deployment.backend_image}"
                          + ("" if pinned else " (tag, not digest: the image could change under the same name)"))
        return deployment

    async def list_deployments(self, user_id: str, project_id: str) -> list[Deployment]:
        await self._owned_project(user_id, project_id)
        return await self.repo.list_deployments(project_id)

    async def rollback(self, user_id: str, project_id: str, version: int) -> Deployment:
        project = await self._owned_project(user_id, project_id)
        if project.status == "deleting":
            raise Conflict("Project is being deleted")
        target = await self.repo.get_deployment(project.id, version)
        if target is None:
            raise NotFound(f"Version {version} not found")
        if version == project.current_version:
            raise Conflict(f"Version {version} is already current")
        deployment = await self.repo.create_deployment(Deployment(
            project_id=project.id, owner_id=user_id, stack_version=target.stack_version,
            backend_image=target.backend_image, config=target.config, reason="rollback",
            rolled_back_from=version, created_by=user_id,
        ))
        await self._event(project, "rolled_back", f"v{deployment.version}: rollback to v{version}")
        return deployment

    async def desired_state(self, user_id: str, project_id: str) -> DesiredState:
        project = await self._owned_project(user_id, project_id)
        return await self.build_desired_state(project)

    async def build_desired_state(self, project: Project) -> DesiredState:
        current = (await self.repo.get_deployment(project.id, project.current_version)
                   if project.current_version else None)
        server = await self.repo.get_server(project.id)
        return DesiredState(
            project_id=project.id,
            version=project.current_version,
            stack_version=current.stack_version if current else None,
            backend_image=current.backend_image if current else None,
            config=current.config if current else {},
            domains=[f"{project.slug}.{self.settings.base_domain}"],
            server=({"provider": server.provider, "server_type": server.server_type, "location": server.location}
                    if server else None),
            generated_at=self._clock(),
        )

    # ---------------------------------------------------------------- reconcile
    async def reconcile_once(self) -> None:
        """Moves every project in transition one step towards its target state."""
        for project in await self.repo.list_projects_by_status(_IN_TRANSITION):
            try:
                await self.reconcile_project(project.id)
            except Exception:
                log.exception("reconcile failed for project %s", project.id)

    async def reconcile_project(self, project_id: str) -> None:
        lock = self._locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            project = await self.repo.get_project(project_id)  # re-read under the lock
            if project is None:
                return
            if project.status == "provisioning":
                await self._reconcile_provisioning(project)
            elif project.status == "deleting":
                await self._reconcile_deleting(project)
            elif project.status == "running":
                remote = await self.provider.find_server(project.id)
                if remote:
                    await self._mirror(project, remote)

    def _timed_out(self, project: Project) -> bool:
        started = project.created_at or self._clock()
        return (self._clock() - started).total_seconds() > self.settings.provision_timeout_seconds

    async def _mirror(self, project: Project, remote: ProviderServer) -> None:
        await self.repo.update_server(project.id, provider_server_id=remote.provider_server_id,
                                      status=remote.status, ipv4=remote.ipv4, ipv6=remote.ipv6)

    async def _fail(self, project: Project, detail: str) -> None:
        await self.repo.update_project(project.id, status="failed", status_detail=detail)
        await self._event(project, "failed", detail)

    async def _reconcile_provisioning(self, project: Project) -> None:
        # Look the server up by label first, so a crash between "create" and
        # "save the id" never produces a second server.
        remote = await self.provider.find_server(project.id)
        if remote is None:
            if self._timed_out(project):
                await self._fail(project, "Server was not created before the provisioning timeout")
                return
            token = self._token()
            spec = ServerSpec(
                name=f"ogna-{project.slug}", server_type=project.server_type, location=project.region,
                user_data=render_user_data(project, token, self.settings),
                labels={PROJECT_LABEL: project.id, "ogna-owner-hash": hashlib.sha256(project.owner_id.encode()).hexdigest()[:16]},
            )
            try:
                remote = await self.provider.create_server(spec)
            except ProviderError as exc:
                if not exc.retryable:
                    await self._fail(project, exc.message)
                else:
                    await self.repo.update_project(project.id, status_detail=f"Retrying: {exc.message}")
                return
            await self.repo.update_server(project.id, enrollment_token_hash=hashlib.sha256(token.encode()).hexdigest())
            await self._event(project, "server_created", f"Server {remote.name} created ({remote.provider_server_id})")

        await self._mirror(project, remote)
        if remote.status == "running":
            await self.repo.update_project(project.id, status="running", status_detail=None)
            await self._event(project, "running", f"Server is running at {remote.ipv4 or remote.ipv6}")
        elif self._timed_out(project):
            await self._fail(project, f"Server still '{remote.status}' after the provisioning timeout")

    async def _reconcile_deleting(self, project: Project) -> None:
        remote = await self.provider.find_server(project.id)
        if remote is not None:
            if remote.status != "deleting":
                await self.provider.delete_server(remote.provider_server_id)
            await self.repo.update_server(project.id, status="deleting")
            return
        if await self.repo.get_server(project.id):
            await self.repo.update_server(project.id, status="deleted")
        await self.repo.update_project(project.id, status="deleted", deleted_at=self._clock(), status_detail=None)
        await self._event(project, "deleted", "Server deleted; project removed")

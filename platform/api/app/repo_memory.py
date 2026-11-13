"""In-memory repository: for tests and local experiments (OGNA_PLATFORM_REPOSITORY=memory).

Mirrors the SQL triggers (plan quota, deployment versions) under a lock.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from .errors import Conflict, NotFound, QuotaExceeded
from .models import Account, Deployment, Event, Plan, Project, Server

DEFAULT_PLANS = [
    Plan(id="hobby", name="Hobby", server_type="cx23", max_projects=1, is_default=True, sort_order=10),
    Plan(id="pro", name="Pro", server_type="cx33", max_projects=3, monthly_price_cents=2000, sort_order=20),
    Plan(id="business", name="Business", server_type="cx43", max_projects=10, monthly_price_cents=6000, sort_order=30),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryRepository:
    def __init__(self, plans: Optional[list[Plan]] = None):
        self._lock = asyncio.Lock()
        self.plans = {p.id: p for p in (plans or DEFAULT_PLANS)}
        self.accounts: dict[str, Account] = {}
        self.projects: dict[str, Project] = {}
        self.servers: dict[str, Server] = {}
        self.deployments: list[Deployment] = []
        self.events: list[Event] = []

    # plans & accounts --------------------------------------------------------
    async def list_plans(self, *, active_only: bool = True) -> list[Plan]:
        plans = [p for p in self.plans.values() if p.active or not active_only]
        return sorted(plans, key=lambda p: (p.sort_order, p.id))

    async def get_plan(self, plan_id: str) -> Optional[Plan]:
        return self.plans.get(plan_id)

    async def get_account(self, user_id: str) -> Optional[Account]:
        return self.accounts.get(user_id)

    async def create_account(self, user_id: str, plan_id: str) -> Account:
        async with self._lock:
            return self.accounts.setdefault(user_id, Account(user_id=user_id, plan_id=plan_id))

    async def set_account_plan(self, user_id: str, plan_id: str) -> Account:
        if user_id not in self.accounts:
            raise NotFound("account not found")
        self.accounts[user_id] = Account(user_id=user_id, plan_id=plan_id)
        return self.accounts[user_id]

    # projects ----------------------------------------------------------------
    def _active_count(self, owner_id: str) -> int:
        return sum(1 for p in self.projects.values() if p.owner_id == owner_id and p.status != "deleted")

    async def count_active_projects(self, owner_id: str) -> int:
        return self._active_count(owner_id)

    async def create_project(self, project: Project) -> Project:
        async with self._lock:
            account = self.accounts.get(project.owner_id)
            if account is None:
                raise NotFound("account not found")
            allowed = self.plans[account.plan_id].max_projects
            if self._active_count(project.owner_id) >= allowed:
                raise QuotaExceeded(f"Your plan allows {allowed} project(s)")
            if any(p.slug == project.slug for p in self.projects.values()):
                raise Conflict("slug already taken")
            now = _now()
            stored = project.model_copy(update={
                "id": project.id or str(uuid.uuid4()), "created_at": now, "updated_at": now,
            })
            self.projects[stored.id] = stored
            return stored

    async def get_project(self, project_id: str) -> Optional[Project]:
        return self.projects.get(project_id)

    async def list_projects(self, owner_id: str) -> list[Project]:
        items = [p for p in self.projects.values() if p.owner_id == owner_id and p.status != "deleted"]
        return sorted(items, key=lambda p: p.created_at or _now())

    async def list_projects_by_status(self, statuses: Sequence[str]) -> list[Project]:
        return [p for p in self.projects.values() if p.status in statuses]

    async def update_project(self, project_id: str, **fields) -> Project:
        if project_id not in self.projects:
            raise NotFound("project not found")
        updated = self.projects[project_id].model_copy(update={**fields, "updated_at": _now()})
        self.projects[project_id] = updated
        return updated

    # servers -----------------------------------------------------------------
    async def create_server(self, server: Server) -> Server:
        if server.project_id in self.servers:
            raise Conflict("server already exists for project")
        stored = server.model_copy(update={"id": server.id or str(uuid.uuid4()), "created_at": _now()})
        self.servers[server.project_id] = stored
        return stored

    async def get_server(self, project_id: str) -> Optional[Server]:
        return self.servers.get(project_id)

    async def update_server(self, project_id: str, **fields) -> Server:
        if project_id not in self.servers:
            raise NotFound("server not found")
        updated = self.servers[project_id].model_copy(update={**fields, "updated_at": _now()})
        self.servers[project_id] = updated
        return updated

    # deployments -------------------------------------------------------------
    async def create_deployment(self, deployment: Deployment) -> Deployment:
        async with self._lock:
            project = self.projects.get(deployment.project_id)
            if project is None:
                raise NotFound("project not found")
            version = project.current_version + 1
            stored = deployment.model_copy(update={
                "id": str(uuid.uuid4()), "version": version, "created_at": _now(),
            })
            self.deployments.append(stored)
            self.projects[project.id] = project.model_copy(update={"current_version": version})
            return stored

    async def get_deployment(self, project_id: str, version: int) -> Optional[Deployment]:
        return next((d for d in self.deployments if d.project_id == project_id and d.version == version), None)

    async def list_deployments(self, project_id: str, limit: int = 50) -> list[Deployment]:
        items = [d for d in self.deployments if d.project_id == project_id]
        return sorted(items, key=lambda d: d.version, reverse=True)[:limit]

    # events ------------------------------------------------------------------
    async def add_event(self, event: Event) -> None:
        self.events.append(event.model_copy(update={"id": len(self.events) + 1, "created_at": _now()}))

    async def list_events(self, project_id: str, limit: int = 50) -> list[Event]:
        items = [e for e in self.events if e.project_id == project_id]
        return list(reversed(items))[:limit]

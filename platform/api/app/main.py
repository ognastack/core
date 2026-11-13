"""HTTP API for the OGNA control plane.

Runs as the `api` service of an OGNA stack: the gateway authenticates every
request and forwards the user as X-Authenticated-User-Id, so this service has
no auth code of its own. It must only be reachable through the gateway.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .errors import Forbidden, PlatformError
from .http import HttpxClient
from .models import (
    AccountView, CreateProjectRequest, DeployRequest, Deployment, DesiredState, Event,
    Plan, ProjectView, SetPlanRequest,
)
from .providers.fake import FakeProvider
from .providers.hetzner import HetznerProvider
from .repo_hasura import HasuraRepository
from .repo_memory import InMemoryRepository
from .service import USER_ID, PlatformService

log = logging.getLogger("ogna.platform")


def build_service(settings: Settings, http) -> PlatformService:
    repo = (InMemoryRepository() if settings.repository == "memory"
            else HasuraRepository(http, settings.hasura_url, settings.hasura_admin_secret))
    provider = (FakeProvider() if settings.provider == "fake"
                else HetznerProvider(http, settings.hetzner_token, api_url=settings.hetzner_api_url,
                                     image=settings.hetzner_image, ssh_key_ids=settings.hetzner_ssh_key_ids))
    return PlatformService(repo, provider, settings)


async def _reconcile_loop(service: PlatformService, interval: int) -> None:
    while True:
        try:
            await service.reconcile_once()
        except Exception:
            log.exception("reconcile loop iteration failed")
        await asyncio.sleep(interval)


def create_app(service: Optional[PlatformService] = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        http = None
        if service is None:
            settings = Settings.from_env()
            http = HttpxClient()
            app.state.service = build_service(settings, http)
        else:
            app.state.service = service
        svc: PlatformService = app.state.service
        task = None
        if svc.settings.reconcile_interval_seconds > 0:
            task = asyncio.create_task(_reconcile_loop(svc, svc.settings.reconcile_interval_seconds))
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if http:
                await http.aclose()

    app = FastAPI(title="OGNA platform API", root_path="/api", lifespan=lifespan)

    @app.exception_handler(PlatformError)
    async def _platform_error(_: Request, exc: PlatformError):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message}})

    def svc(request: Request) -> PlatformService:
        return request.app.state.service

    def current_user(x_authenticated_user_id: Optional[str] = Header(default=None)) -> str:
        # Set by the OGNA gateway after it verified the caller's token (clients can't spoof it)
        if not x_authenticated_user_id or not USER_ID.match(x_authenticated_user_id):
            raise Forbidden("Missing or invalid authenticated user")
        return x_authenticated_user_id

    @app.get("/v1/health/")
    async def health():
        return {"status": "healthy"}

    @app.get("/v1/plans", response_model=list[Plan])
    async def list_plans(s: PlatformService = Depends(svc), _: str = Depends(current_user)):
        return await s.list_plans()

    @app.get("/v1/account", response_model=AccountView)
    async def get_account(s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.get_account(user)

    @app.put("/v1/admin/accounts/{user_id}/plan", response_model=AccountView)
    async def set_plan(user_id: str, body: SetPlanRequest, s: PlatformService = Depends(svc),
                       user: str = Depends(current_user)):
        return await s.set_plan(user, user_id, body.plan_id)

    @app.post("/v1/projects", response_model=ProjectView, status_code=202)
    async def create_project(body: CreateProjectRequest, background: BackgroundTasks,
                             s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        view = await s.create_project(user, body)
        # Start provisioning now instead of waiting for the next loop tick
        background.add_task(s.reconcile_project, view.project.id)
        return view

    @app.get("/v1/projects", response_model=list[ProjectView])
    async def list_projects(s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.list_projects(user)

    @app.get("/v1/projects/{project_id}", response_model=ProjectView)
    async def get_project(project_id: str, s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.get_project(user, project_id)

    @app.delete("/v1/projects/{project_id}", response_model=ProjectView, status_code=202)
    async def delete_project(project_id: str, background: BackgroundTasks,
                             s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        view = await s.delete_project(user, project_id)
        background.add_task(s.reconcile_project, project_id)
        return view

    @app.post("/v1/projects/{project_id}/sync", response_model=ProjectView)
    async def sync_project(project_id: str, s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.sync_project(user, project_id)

    @app.get("/v1/projects/{project_id}/events", response_model=list[Event])
    async def list_events(project_id: str, s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.list_events(user, project_id)

    @app.post("/v1/projects/{project_id}/deployments", response_model=Deployment, status_code=201)
    async def deploy(project_id: str, body: DeployRequest, s: PlatformService = Depends(svc),
                     user: str = Depends(current_user)):
        return await s.deploy(user, project_id, body)

    @app.get("/v1/projects/{project_id}/deployments", response_model=list[Deployment])
    async def list_deployments(project_id: str, s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.list_deployments(user, project_id)

    @app.post("/v1/projects/{project_id}/deployments/{version}/rollback", response_model=Deployment, status_code=201)
    async def rollback(project_id: str, version: int, s: PlatformService = Depends(svc),
                       user: str = Depends(current_user)):
        return await s.rollback(user, project_id, version)

    @app.get("/v1/projects/{project_id}/desired-state", response_model=DesiredState)
    async def desired_state(project_id: str, s: PlatformService = Depends(svc), user: str = Depends(current_user)):
        return await s.desired_state(user, project_id)

    return app


app = create_app()

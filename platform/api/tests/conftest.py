from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from app.config import Settings
from app.http import HttpResponse
from app.providers.fake import FakeProvider
from app.repo_memory import InMemoryRepository
from app.service import PlatformService


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds: int):
        self.now += timedelta(seconds=seconds)


class FakeHttp:
    """Records requests and replays queued or routed responses."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.requests = []

    async def request(self, method, url, *, headers=None, json=None, params=None):
        self.requests.append({"method": method, "url": url, "headers": headers, "json": json, "params": params})
        handler = self.routes.get((method, url))
        if handler is None:
            return HttpResponse(404, {"error": {"code": "not_found", "message": "no route"}})
        result = handler(json, params) if callable(handler) else handler
        return result if isinstance(result, HttpResponse) else HttpResponse(200, result)

    async def aclose(self):
        pass


def make_settings(**overrides) -> Settings:
    base = dict(repository="memory", provider="fake", regions=("fsn1", "nbg1"),
                base_domain="ogna.app", control_plane_url="https://platform.ogna.app",
                admin_user_ids=frozenset({"admin"}), provision_timeout_seconds=600,
                reconcile_interval_seconds=0)
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def env(clock):
    repo = InMemoryRepository()
    provider = FakeProvider(ready_after=1)
    tokens = (f"token-{i}" for i in itertools.count(1))
    suffixes = (f"{i:06x}" for i in itertools.count(1))
    service = PlatformService(repo, provider, make_settings(), clock=clock,
                              token_factory=lambda: next(tokens), suffix_factory=lambda: next(suffixes))

    # Projects are timestamped by the repository; align them with the fake clock
    original = repo.create_project

    async def create_project(project):
        stored = await original(project)
        stored = stored.model_copy(update={"created_at": clock()})
        repo.projects[stored.id] = stored
        return stored

    repo.create_project = create_project
    return service, repo, provider

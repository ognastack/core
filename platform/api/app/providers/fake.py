"""Simulated provider for tests and local runs (OGNA_PLATFORM_PROVIDER=fake)."""

from __future__ import annotations

import itertools
from typing import Optional

from ..errors import ProviderError
from . import PROJECT_LABEL, ProviderServer, ServerSpec


class FakeProvider:
    name = "fake"

    def __init__(self, *, ready_after: int = 1):
        # A server reports "running" after this many find_server calls
        self.ready_after = ready_after
        self.servers: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_next_create: Optional[ProviderError] = None
        self._ids = itertools.count(1000)

    def _view(self, sid: str) -> ProviderServer:
        s = self.servers[sid]
        return ProviderServer(provider_server_id=sid, name=s["spec"].name, status=s["status"],
                              ipv4=s["ipv4"], ipv6=s["ipv6"])

    async def create_server(self, spec: ServerSpec) -> ProviderServer:
        self.calls.append(("create", spec.name))
        if self.fail_next_create:
            err, self.fail_next_create = self.fail_next_create, None
            raise err
        sid = str(next(self._ids))
        n = int(sid) % 250
        self.servers[sid] = {"spec": spec, "status": "creating", "polls": 0,
                             "ipv4": f"203.0.113.{n}", "ipv6": f"2001:db8::{n:x}"}
        return self._view(sid)

    async def find_server(self, project_id: str) -> Optional[ProviderServer]:
        self.calls.append(("find", project_id))
        for sid, s in self.servers.items():
            if s["spec"].labels.get(PROJECT_LABEL) == project_id:
                if s["status"] == "deleting":
                    del self.servers[sid]  # deletion completes on the next look
                    return None
                s["polls"] += 1
                if s["status"] == "creating" and s["polls"] >= self.ready_after:
                    s["status"] = "running"
                return self._view(sid)
        return None

    async def delete_server(self, provider_server_id: str) -> None:
        self.calls.append(("delete", provider_server_id))
        if provider_server_id in self.servers:
            self.servers[provider_server_id]["status"] = "deleting"

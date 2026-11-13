"""Infrastructure providers (where customer VPSs are created)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

# Every server carries this label so it can be found again after a crash
PROJECT_LABEL = "ogna-project"


@dataclass
class ServerSpec:
    name: str
    server_type: str
    location: str
    user_data: str
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderServer:
    provider_server_id: str
    name: str
    # Normalized: creating | running | off | deleting | unknown
    status: str
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None


class Provider(Protocol):
    name: str

    async def create_server(self, spec: ServerSpec) -> ProviderServer: ...

    async def find_server(self, project_id: str) -> Optional[ProviderServer]:
        """The server labelled with this project, if any."""

    async def delete_server(self, provider_server_id: str) -> None:
        """Idempotent: deleting a server that is already gone is not an error."""

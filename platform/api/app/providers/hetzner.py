"""Hetzner Cloud provider (https://docs.hetzner.cloud)."""

from __future__ import annotations

from typing import Any, Optional

from ..errors import ProviderError
from ..http import HttpClient, TransportError
from . import PROJECT_LABEL, ProviderServer, ServerSpec

_STATUS = {
    "initializing": "creating",
    "starting": "creating",
    "running": "running",
    "stopping": "off",
    "off": "off",
    "deleting": "deleting",
    "migrating": "unknown",
    "rebuilding": "unknown",
    "unknown": "unknown",
}
# Errors that won't go away by retrying the same request
_PERMANENT = {"invalid_input", "uniqueness_error", "forbidden", "unauthorized", "not_found", "json_error"}


def _to_server(raw: dict[str, Any]) -> ProviderServer:
    net = raw.get("public_net") or {}
    ipv4 = (net.get("ipv4") or {}).get("ip")
    ipv6 = (net.get("ipv6") or {}).get("ip")
    return ProviderServer(
        provider_server_id=str(raw["id"]),
        name=raw.get("name", ""),
        status=_STATUS.get(raw.get("status", "unknown"), "unknown"),
        ipv4=ipv4,
        ipv6=ipv6,
    )


class HetznerProvider:
    name = "hetzner"

    def __init__(self, http: HttpClient, token: str, *, api_url: str = "https://api.hetzner.cloud/v1",
                 image: str = "ubuntu-24.04", ssh_key_ids: tuple[str, ...] = ()):
        self._http = http
        self._api = api_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self._image = image
        # Numeric ids are sent as ints, anything else as key names
        self._ssh_keys = [int(k) if k.isdigit() else k for k in ssh_key_ids]

    async def _call(self, method: str, path: str, *, json: Any = None, params: Optional[dict] = None,
                    allow_404: bool = False) -> Optional[dict]:
        try:
            response = await self._http.request(method, f"{self._api}{path}", headers=self._headers,
                                                json=json, params=params)
        except TransportError as exc:
            raise ProviderError(f"Hetzner unreachable: {exc}") from exc
        if response.status == 404 and allow_404:
            return None
        if response.status >= 400:
            err = (response.body or {}).get("error", {}) if isinstance(response.body, dict) else {}
            code = err.get("code", f"http_{response.status}")
            message = err.get("message", "request failed")
            raise ProviderError(f"Hetzner {code}: {message}",
                                retryable=code not in _PERMANENT and response.status != 401)
        return response.body or {}

    async def create_server(self, spec: ServerSpec) -> ProviderServer:
        body: dict[str, Any] = {
            "name": spec.name,
            "server_type": spec.server_type,
            "image": self._image,
            "location": spec.location,
            "user_data": spec.user_data,
            "labels": spec.labels,
            "start_after_create": True,
            "public_net": {"enable_ipv4": True, "enable_ipv6": True},
        }
        if self._ssh_keys:
            # Without SSH keys Hetzner emails a root password; cloud-init disables
            # password logins anyway, so configure keys for break-glass access.
            body["ssh_keys"] = self._ssh_keys
        data = await self._call("POST", "/servers", json=body)
        return _to_server(data["server"])

    async def find_server(self, project_id: str) -> Optional[ProviderServer]:
        data = await self._call("GET", "/servers", params={"label_selector": f"{PROJECT_LABEL}={project_id}"})
        servers = data.get("servers") or []
        return _to_server(servers[0]) if servers else None

    async def delete_server(self, provider_server_id: str) -> None:
        await self._call("DELETE", f"/servers/{provider_server_id}", allow_404=True)

"""Minimal async HTTP abstraction so providers and the Hasura client are testable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol


@dataclass
class HttpResponse:
    status: int
    body: Any  # parsed JSON, or None for empty bodies


class TransportError(Exception):
    """The request never got an HTTP response (DNS, connect, timeout)."""


class HttpClient(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        json: Any = None,
        params: Optional[Mapping[str, str]] = None,
    ) -> HttpResponse: ...

    async def aclose(self) -> None: ...


class HttpxClient:
    """Production implementation backed by httpx."""

    def __init__(self, timeout: float = 20.0):
        import httpx  # imported lazily so tests run without httpx installed

        self._httpx = httpx
        self._client = httpx.AsyncClient(timeout=timeout)

    async def request(self, method, url, *, headers=None, json=None, params=None) -> HttpResponse:
        try:
            response = await self._client.request(method, url, headers=headers, json=json, params=params)
        except self._httpx.HTTPError as exc:  # timeouts, connection errors
            raise TransportError(f"{method} {url}: {exc.__class__.__name__}") from exc
        body: Any = None
        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = {"raw": response.text[:500]}
        return HttpResponse(status=response.status_code, body=body)

    async def aclose(self) -> None:
        await self._client.aclose()

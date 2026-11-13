"""Settings for the control-plane API, read from the environment (.env)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping

_REGION = re.compile(r"^[a-z0-9-]{2,16}$")


def _csv(value: str | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or "").split(",") if v.strip())


@dataclass(frozen=True)
class Settings:
    # Data access: "hasura" (production) or "memory" (local experiments, tests)
    repository: str = "hasura"
    hasura_url: str = "http://hasura:8080/v1/graphql"
    hasura_admin_secret: str = ""

    # Infrastructure provider: "hetzner" or "fake" (simulated servers)
    provider: str = "hetzner"
    hetzner_token: str = ""
    hetzner_api_url: str = "https://api.hetzner.cloud/v1"
    hetzner_image: str = "ubuntu-24.04"
    hetzner_ssh_key_ids: tuple[str, ...] = ()

    regions: tuple[str, ...] = ("fsn1", "nbg1", "hel1")
    default_stack_version: str = "main"
    # Projects are reachable at <slug>.<base_domain> once DNS is wired up
    base_domain: str = "ogna.local"
    # Public URL the future agent will call; written into each VPS's cloud-init
    control_plane_url: str = "http://localhost:8000"
    agent_install_url: str = ""

    admin_user_ids: frozenset[str] = frozenset()
    provision_timeout_seconds: int = 900
    reconcile_interval_seconds: int = 30

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        e = os.environ if env is None else env
        settings = cls(
            repository=e.get("OGNA_PLATFORM_REPOSITORY", "hasura").strip().lower(),
            hasura_url=e.get("OGNA_PLATFORM_HASURA_URL", "http://hasura:8080/v1/graphql"),
            hasura_admin_secret=e.get("HASURA_GRAPHQL_ADMIN_SECRET", ""),
            provider=e.get("OGNA_PLATFORM_PROVIDER", "hetzner").strip().lower(),
            hetzner_token=e.get("HETZNER_API_TOKEN", ""),
            hetzner_api_url=e.get("HETZNER_API_URL", "https://api.hetzner.cloud/v1").rstrip("/"),
            hetzner_image=e.get("HETZNER_IMAGE", "ubuntu-24.04"),
            hetzner_ssh_key_ids=_csv(e.get("HETZNER_SSH_KEY_IDS")),
            regions=_csv(e.get("OGNA_PLATFORM_REGIONS")) or ("fsn1", "nbg1", "hel1"),
            default_stack_version=e.get("OGNA_PLATFORM_DEFAULT_STACK_VERSION", "main"),
            base_domain=e.get("OGNA_PLATFORM_BASE_DOMAIN", "ogna.local").strip().lower(),
            control_plane_url=e.get("OGNA_PLATFORM_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
            agent_install_url=e.get("OGNA_AGENT_INSTALL_URL", ""),
            admin_user_ids=frozenset(_csv(e.get("OGNA_PLATFORM_ADMIN_USER_IDS"))),
            provision_timeout_seconds=int(e.get("OGNA_PLATFORM_PROVISION_TIMEOUT", "900")),
            reconcile_interval_seconds=int(e.get("OGNA_PLATFORM_RECONCILE_INTERVAL", "30")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.repository not in ("hasura", "memory"):
            raise ValueError("OGNA_PLATFORM_REPOSITORY must be 'hasura' or 'memory'")
        if self.repository == "hasura" and not self.hasura_admin_secret:
            raise ValueError("HASURA_GRAPHQL_ADMIN_SECRET is required with the hasura repository")
        if self.provider not in ("hetzner", "fake"):
            raise ValueError("OGNA_PLATFORM_PROVIDER must be 'hetzner' or 'fake'")
        if self.provider == "hetzner" and not self.hetzner_token:
            raise ValueError("HETZNER_API_TOKEN is required with the hetzner provider")
        if not self.regions or not all(_REGION.match(r) for r in self.regions):
            raise ValueError("OGNA_PLATFORM_REGIONS must be a comma-separated list of region ids")
        if self.provision_timeout_seconds < 60:
            raise ValueError("OGNA_PLATFORM_PROVISION_TIMEOUT must be at least 60 seconds")
        if self.reconcile_interval_seconds < 0:
            raise ValueError("OGNA_PLATFORM_RECONCILE_INTERVAL must be >= 0 (0 disables the loop)")
        if not re.match(r"^https?://", self.control_plane_url):
            raise ValueError("OGNA_PLATFORM_PUBLIC_URL must be an http(s) URL")
        if self.agent_install_url and not self.agent_install_url.startswith("https://"):
            raise ValueError("OGNA_AGENT_INSTALL_URL must be an https URL")

    @property
    def default_region(self) -> str:
        return self.regions[0]

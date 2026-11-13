"""Domain models and request/response schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProjectStatus = Literal["provisioning", "running", "failed", "deleting", "deleted"]
# Normalized server states (providers map their own states onto these)
ServerStatus = Literal["pending", "creating", "running", "off", "deleting", "deleted", "unknown"]
DeploymentReason = Literal["deploy", "rollback"]

# registry/path/name with a tag and/or a sha256 digest, e.g.
#   ghcr.io/acme/api:1.2.0   ghcr.io/acme/api@sha256:<64 hex>
_IMAGE = re.compile(
    r"^(?:[a-z0-9]+(?:[._-][a-z0-9]+)*(?::[0-9]{1,5})?/)?"
    r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)*"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?"
    r"(?:@sha256:[a-f0-9]{64})?$"
)
_STACK_VERSION = re.compile(r"^(main|\d+\.\d+\.\d+)$")
_CONFIG_KEY = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
# Settings the platform controls; a deploy must not override them
_RESERVED_PREFIXES = ("OGNA_", "POSTGRES_", "HASURA_", "GOTRUE_", "ZITADEL_", "KONG_")
MAX_CONFIG_ENTRIES = 50
MAX_CONFIG_VALUE = 4096


class Plan(BaseModel):
    id: str
    name: str
    server_type: str
    max_projects: int
    monthly_price_cents: int = 0
    is_default: bool = False
    active: bool = True
    sort_order: int = 0


class Account(BaseModel):
    user_id: str
    plan_id: str


class Project(BaseModel):
    id: str
    owner_id: str
    name: str
    slug: str
    plan_id: str
    server_type: str
    region: str
    status: ProjectStatus = "provisioning"
    status_detail: Optional[str] = None
    current_version: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class Server(BaseModel):
    id: Optional[str] = None
    project_id: str
    owner_id: str
    provider: str
    provider_server_id: Optional[str] = None
    name: str
    server_type: str
    location: str
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    status: ServerStatus = "pending"
    # Never serialized in API responses; repositories persist it explicitly
    enrollment_token_hash: Optional[str] = Field(default=None, exclude=True)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Deployment(BaseModel):
    id: Optional[str] = None
    project_id: str
    owner_id: str
    version: int = 0
    stack_version: str
    backend_image: str
    config: dict[str, str] = Field(default_factory=dict)
    reason: DeploymentReason = "deploy"
    rolled_back_from: Optional[int] = None
    created_by: str
    created_at: Optional[datetime] = None


class Event(BaseModel):
    id: Optional[int] = None
    project_id: str
    owner_id: str
    kind: str
    message: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=63)
    region: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        if any(ord(c) < 32 for c in v):
            raise ValueError("name must not contain control characters")
        return v


class DeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend_image: str = Field(max_length=512)
    stack_version: Optional[str] = None
    config: dict[str, str] = Field(default_factory=dict)

    @field_validator("backend_image")
    @classmethod
    def _image(cls, v: str) -> str:
        v = v.strip()
        if not _IMAGE.match(v):
            raise ValueError("backend_image must look like registry/name:tag or registry/name@sha256:<digest>")
        if ":" not in v.rsplit("/", 1)[-1] and "@sha256:" not in v:
            raise ValueError("backend_image needs a tag or a digest (bare names would float to :latest)")
        return v

    @field_validator("stack_version")
    @classmethod
    def _stack(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _STACK_VERSION.match(v):
            raise ValueError("stack_version must be 'main' or a version like 1.4.2")
        return v

    @field_validator("config")
    @classmethod
    def _config(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > MAX_CONFIG_ENTRIES:
            raise ValueError(f"config allows at most {MAX_CONFIG_ENTRIES} entries")
        for key, value in v.items():
            if not _CONFIG_KEY.match(key):
                raise ValueError(f"config key {key!r} must be UPPER_SNAKE_CASE")
            if key.startswith(_RESERVED_PREFIXES):
                raise ValueError(f"config key {key!r} is reserved for the platform")
            if len(value) > MAX_CONFIG_VALUE:
                raise ValueError(f"config value for {key!r} is longer than {MAX_CONFIG_VALUE} characters")
        return v


class SetPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1, max_length=32)


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class Region(BaseModel):
    id: str
    name: str
    is_default: bool = False


class AccountView(BaseModel):
    user_id: str
    plan: Plan
    projects_used: int
    projects_allowed: int
    is_admin: bool = False


class ProjectView(BaseModel):
    project: Project
    server: Optional[Server] = None
    current_deployment: Optional[Deployment] = None
    url: str


class DesiredState(BaseModel):
    """What the project's VPS should be running; the future agent fetches this."""

    project_id: str
    version: int
    stack_version: Optional[str]
    backend_image: Optional[str]
    config: dict[str, str]
    domains: list[str]
    server: Optional[dict[str, Optional[str]]]
    generated_at: datetime

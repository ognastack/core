"""Repository backed by Hasura GraphQL (the OGNA way: services don't open Postgres directly).

Uses the admin secret over the internal `gql` network. Users never reach these
operations: they only get the read-only, owner-filtered permissions defined in
platform/hasura/tables.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional, Sequence

from .errors import Conflict, NotFound, QuotaExceeded, RepositoryError
from .http import HttpClient, TransportError
from .models import Account, Deployment, Event, Plan, Project, Server

PLAN_FIELDS = "id name server_type max_projects monthly_price_cents is_default active sort_order"
ACCOUNT_FIELDS = "user_id plan_id"
PROJECT_FIELDS = (
    "id owner_id name slug plan_id server_type region status status_detail "
    "current_version created_at updated_at deleted_at"
)
SERVER_FIELDS = (
    "id project_id owner_id provider provider_server_id name server_type location "
    "ipv4 ipv6 status enrollment_token_hash created_at updated_at"
)
DEPLOYMENT_FIELDS = (
    "id project_id owner_id version stack_version backend_image config reason "
    "rolled_back_from created_by created_at"
)
EVENT_FIELDS = "id project_id owner_id kind message created_at"


def _jsonable(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in fields.items()}


def _server_row(server: Server) -> dict[str, Any]:
    row = server.model_dump(mode="json", exclude_none=True, exclude={"id", "created_at", "updated_at"})
    if server.enrollment_token_hash is not None:
        row["enrollment_token_hash"] = server.enrollment_token_hash
    return row


def _server(row: dict) -> Server:
    return Server.model_validate(row)


class HasuraRepository:
    def __init__(self, http: HttpClient, url: str, admin_secret: str):
        self._http = http
        self._url = url
        self._headers = {"x-hasura-admin-secret": admin_secret, "content-type": "application/json"}

    async def _gql(self, query: str, variables: Optional[dict] = None) -> dict:
        try:
            response = await self._http.request(
                "POST", self._url, headers=self._headers, json={"query": query, "variables": variables or {}}
            )
        except TransportError as exc:
            raise RepositoryError(f"Hasura unreachable: {exc}") from exc
        body = response.body or {}
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors:
            self._raise_for(errors)
        if response.status != 200 or not isinstance(body, dict) or "data" not in body:
            raise RepositoryError(f"Hasura returned HTTP {response.status}")
        return body["data"]

    @staticmethod
    def _raise_for(errors: list) -> None:
        text = json.dumps(errors)
        match = re.search(r"quota_exceeded: plan allows (\d+)", text)
        if match:
            raise QuotaExceeded(f"Your plan allows {match.group(1)} project(s)")
        if "projects_slug_key" in text:
            raise Conflict("slug already taken")
        if "servers_project_id_key" in text:
            raise Conflict("server already exists for project")
        if "account_not_found" in text or "project_not_found" in text:
            raise NotFound("referenced row not found")
        first = errors[0] if errors and isinstance(errors[0], dict) else {}
        raise RepositoryError(f"Hasura error: {first.get('message', 'unknown')}")

    # plans & accounts --------------------------------------------------------
    async def list_plans(self, *, active_only: bool = True) -> list[Plan]:
        where = {"active": {"_eq": True}} if active_only else {}
        data = await self._gql(
            f"""query ($where: platform_plans_bool_exp!) {{
                  platform_plans(where: $where, order_by: [{{sort_order: asc}}, {{id: asc}}]) {{ {PLAN_FIELDS} }}
                }}""",
            {"where": where},
        )
        return [Plan.model_validate(r) for r in data["platform_plans"]]

    async def get_plan(self, plan_id: str) -> Optional[Plan]:
        data = await self._gql(
            f"query ($id: String!) {{ platform_plans_by_pk(id: $id) {{ {PLAN_FIELDS} }} }}", {"id": plan_id}
        )
        row = data["platform_plans_by_pk"]
        return Plan.model_validate(row) if row else None

    async def get_account(self, user_id: str) -> Optional[Account]:
        data = await self._gql(
            f"query ($id: String!) {{ platform_accounts_by_pk(user_id: $id) {{ {ACCOUNT_FIELDS} }} }}",
            {"id": user_id},
        )
        row = data["platform_accounts_by_pk"]
        return Account.model_validate(row) if row else None

    async def create_account(self, user_id: str, plan_id: str) -> Account:
        # ON CONFLICT DO NOTHING; returns null if the account already existed
        await self._gql(
            f"""mutation ($o: platform_accounts_insert_input!) {{
                  insert_platform_accounts_one(object: $o,
                    on_conflict: {{constraint: accounts_pkey, update_columns: []}}) {{ {ACCOUNT_FIELDS} }}
                }}""",
            {"o": {"user_id": user_id, "plan_id": plan_id}},
        )
        account = await self.get_account(user_id)
        if account is None:
            raise RepositoryError("account could not be created")
        return account

    async def set_account_plan(self, user_id: str, plan_id: str) -> Account:
        data = await self._gql(
            f"""mutation ($id: String!, $plan: String!) {{
                  update_platform_accounts_by_pk(pk_columns: {{user_id: $id}}, _set: {{plan_id: $plan}}) {{ {ACCOUNT_FIELDS} }}
                }}""",
            {"id": user_id, "plan": plan_id},
        )
        row = data["update_platform_accounts_by_pk"]
        if row is None:
            raise NotFound("account not found")
        return Account.model_validate(row)

    # projects ----------------------------------------------------------------
    async def count_active_projects(self, owner_id: str) -> int:
        data = await self._gql(
            """query ($owner: String!) {
                 platform_projects_aggregate(where: {owner_id: {_eq: $owner}, status: {_neq: "deleted"}}) {
                   aggregate { count }
                 }
               }""",
            {"owner": owner_id},
        )
        return int(data["platform_projects_aggregate"]["aggregate"]["count"])

    async def create_project(self, project: Project) -> Project:
        row = project.model_dump(
            mode="json", exclude_none=True,
            exclude={"id", "current_version", "created_at", "updated_at", "deleted_at"},
        )
        data = await self._gql(
            f"""mutation ($o: platform_projects_insert_input!) {{
                  insert_platform_projects_one(object: $o) {{ {PROJECT_FIELDS} }}
                }}""",
            {"o": row},
        )
        return Project.model_validate(data["insert_platform_projects_one"])

    async def get_project(self, project_id: str) -> Optional[Project]:
        data = await self._gql(
            f"query ($id: uuid!) {{ platform_projects_by_pk(id: $id) {{ {PROJECT_FIELDS} }} }}",
            {"id": project_id},
        )
        row = data["platform_projects_by_pk"]
        return Project.model_validate(row) if row else None

    async def list_projects(self, owner_id: str) -> list[Project]:
        data = await self._gql(
            f"""query ($owner: String!) {{
                  platform_projects(where: {{owner_id: {{_eq: $owner}}, status: {{_neq: "deleted"}}}},
                                    order_by: {{created_at: asc}}) {{ {PROJECT_FIELDS} }}
                }}""",
            {"owner": owner_id},
        )
        return [Project.model_validate(r) for r in data["platform_projects"]]

    async def list_projects_by_status(self, statuses: Sequence[str]) -> list[Project]:
        data = await self._gql(
            f"""query ($s: [String!]!) {{
                  platform_projects(where: {{status: {{_in: $s}}}}, order_by: {{created_at: asc}}) {{ {PROJECT_FIELDS} }}
                }}""",
            {"s": list(statuses)},
        )
        return [Project.model_validate(r) for r in data["platform_projects"]]

    async def update_project(self, project_id: str, **fields) -> Project:
        data = await self._gql(
            f"""mutation ($id: uuid!, $set: platform_projects_set_input!) {{
                  update_platform_projects_by_pk(pk_columns: {{id: $id}}, _set: $set) {{ {PROJECT_FIELDS} }}
                }}""",
            {"id": project_id, "set": _jsonable(fields)},
        )
        row = data["update_platform_projects_by_pk"]
        if row is None:
            raise NotFound("project not found")
        return Project.model_validate(row)

    # servers -----------------------------------------------------------------
    async def create_server(self, server: Server) -> Server:
        data = await self._gql(
            f"""mutation ($o: platform_servers_insert_input!) {{
                  insert_platform_servers_one(object: $o) {{ {SERVER_FIELDS} }}
                }}""",
            {"o": _server_row(server)},
        )
        return _server(data["insert_platform_servers_one"])

    async def get_server(self, project_id: str) -> Optional[Server]:
        data = await self._gql(
            f"""query ($p: uuid!) {{
                  platform_servers(where: {{project_id: {{_eq: $p}}}}, limit: 1) {{ {SERVER_FIELDS} }}
                }}""",
            {"p": project_id},
        )
        rows = data["platform_servers"]
        return _server(rows[0]) if rows else None

    async def update_server(self, project_id: str, **fields) -> Server:
        data = await self._gql(
            f"""mutation ($p: uuid!, $set: platform_servers_set_input!) {{
                  update_platform_servers(where: {{project_id: {{_eq: $p}}}}, _set: $set) {{
                    returning {{ {SERVER_FIELDS} }}
                  }}
                }}""",
            {"p": project_id, "set": _jsonable(fields)},
        )
        rows = data["update_platform_servers"]["returning"]
        if not rows:
            raise NotFound("server not found")
        return _server(rows[0])

    # deployments -------------------------------------------------------------
    async def create_deployment(self, deployment: Deployment) -> Deployment:
        # `version` is assigned by the deployments_version trigger
        row = deployment.model_dump(mode="json", exclude_none=True, exclude={"id", "created_at"})
        row["version"] = 0
        data = await self._gql(
            f"""mutation ($o: platform_deployments_insert_input!) {{
                  insert_platform_deployments_one(object: $o) {{ {DEPLOYMENT_FIELDS} }}
                }}""",
            {"o": row},
        )
        return Deployment.model_validate(data["insert_platform_deployments_one"])

    async def get_deployment(self, project_id: str, version: int) -> Optional[Deployment]:
        data = await self._gql(
            f"""query ($p: uuid!, $v: Int!) {{
                  platform_deployments(where: {{project_id: {{_eq: $p}}, version: {{_eq: $v}}}}, limit: 1) {{
                    {DEPLOYMENT_FIELDS}
                  }}
                }}""",
            {"p": project_id, "v": version},
        )
        rows = data["platform_deployments"]
        return Deployment.model_validate(rows[0]) if rows else None

    async def list_deployments(self, project_id: str, limit: int = 50) -> list[Deployment]:
        data = await self._gql(
            f"""query ($p: uuid!, $limit: Int!) {{
                  platform_deployments(where: {{project_id: {{_eq: $p}}}}, order_by: {{version: desc}}, limit: $limit) {{
                    {DEPLOYMENT_FIELDS}
                  }}
                }}""",
            {"p": project_id, "limit": limit},
        )
        return [Deployment.model_validate(r) for r in data["platform_deployments"]]

    # events ------------------------------------------------------------------
    async def add_event(self, event: Event) -> None:
        row = event.model_dump(mode="json", exclude_none=True, exclude={"id", "created_at"})
        await self._gql(
            """mutation ($o: platform_events_insert_input!) {
                 insert_platform_events_one(object: $o) { id }
               }""",
            {"o": row},
        )

    async def list_events(self, project_id: str, limit: int = 50) -> list[Event]:
        data = await self._gql(
            f"""query ($p: uuid!, $limit: Int!) {{
                  platform_events(where: {{project_id: {{_eq: $p}}}}, order_by: {{created_at: desc}}, limit: $limit) {{
                    {EVENT_FIELDS}
                  }}
                }}""",
            {"p": project_id, "limit": limit},
        )
        return [Event.model_validate(r) for r in data["platform_events"]]

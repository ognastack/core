"""Helpers for integration tests: obtain Zitadel tokens without a browser.

Uses the IAM_OWNER service-account PAT that Zitadel writes to the bootstrap
volume to create a throwaway machine user, then gets access tokens for it with
the OAuth client-credentials grant. Tokens are scoped to the OGNA project so
the gateway's introspection client accepts them.

Environment:
  OGNA_GATEWAY_URL     default http://localhost:8000
  OGNA_AUTH_DOMAIN     default auth.localhost
  OGNA_TEST_ADMIN_PAT  optional; otherwise read from the zitadel-setup volume
"""

import os
import subprocess
import uuid
from urllib.parse import urlparse

import requests

GATEWAY_URL = os.environ.get("OGNA_GATEWAY_URL", "http://localhost:8000").rstrip("/")
AUTH_DOMAIN = os.environ.get("OGNA_AUTH_DOMAIN", "auth.localhost")
_port = urlparse(GATEWAY_URL).port
AUTH_HOST = f"{AUTH_DOMAIN}:{_port}" if _port else AUTH_DOMAIN
PROJECT_NAME = os.environ.get("OGNA_AUTH_PROJECT_NAME", "OGNA")

# Seconds the gateway may cache an "active" introspection result
ACTIVE_CACHE_TTL = int(os.environ.get("OGNA_AUTH_ACTIVE_CACHE_TTL", "5"))


def admin_pat():
    pat = os.environ.get("OGNA_TEST_ADMIN_PAT")
    if pat:
        return pat.strip()
    out = subprocess.run(
        ["docker", "run", "--rm", "--volumes-from", "zitadel-setup", "alpine",
         "cat", "/zitadel/bootstrap/admin.pat"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def auth_request(method, path, **kwargs):
    """Request to Zitadel through the gateway's auth-domain routes."""
    headers = kwargs.pop("headers", {})
    headers["Host"] = AUTH_HOST
    return requests.request(method, f"{GATEWAY_URL}{path}", headers=headers, timeout=15, **kwargs)


class ZitadelTestUser:
    """A machine user that can mint access tokens for the OGNA project."""

    def __init__(self):
        self.pat = admin_pat()
        self.project_id = self._project_id()
        res = self._mgmt("POST", "/users/machine", json={
            "userName": f"ogna-test-{uuid.uuid4().hex[:12]}",
            "name": "OGNA integration test",
            "description": "Created by the OGNA test suite; safe to delete",
            "accessTokenType": "ACCESS_TOKEN_TYPE_BEARER",
        })
        self.user_id = res["userId"]
        secret = self._mgmt("PUT", f"/users/{self.user_id}/secret", json={})
        self.client_id = secret["clientId"]
        self.client_secret = secret["clientSecret"]

    def _mgmt(self, method, path, **kwargs):
        r = auth_request(method, f"/management/v1{path}",
                         headers={"Authorization": f"Bearer {self.pat}"}, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}

    def _project_id(self):
        res = self._mgmt("POST", "/projects/_search", json={
            "queries": [{"nameQuery": {"name": PROJECT_NAME, "method": "TEXT_QUERY_METHOD_EQUALS"}}]
        })
        return res["result"][0]["id"]

    def access_token(self):
        r = auth_request("POST", "/oauth/v2/token",
                         auth=(self.client_id, self.client_secret),
                         data={
                             "grant_type": "client_credentials",
                             "scope": f"openid profile urn:zitadel:iam:org:project:id:{self.project_id}:aud",
                         })
        r.raise_for_status()
        return r.json()["access_token"]

    def revoke(self, token):
        r = auth_request("POST", "/oauth/v2/revoke",
                         auth=(self.client_id, self.client_secret),
                         data={"token": token})
        r.raise_for_status()

    def delete(self):
        try:
            self._mgmt("DELETE", f"/users/{self.user_id}")
        except requests.RequestException:
            pass

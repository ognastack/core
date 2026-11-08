"""Idempotent bootstrap for OGNA's Zitadel instance.

Runs after Zitadel is healthy and before the gateway starts. Using the
IAM_OWNER service-account PAT that Zitadel writes on first start, it ensures:

* a project (OGNA_AUTH_PROJECT_NAME, default "OGNA"),
* an API app "ogna-gateway" (client id + secret) that the gateway uses for
  token introspection, written to $BOOTSTRAP_DIR/gateway-client.env,
* an OIDC app "ogna-web" (PKCE, no secret, opaque access tokens) for user-facing
  apps, whose redirect URIs are kept in sync with OGNA_OIDC_REDIRECT_URIS,
  written to $BOOTSTRAP_DIR/web-client.json.

Only the Python standard library is used.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BOOTSTRAP_DIR = os.environ.get("BOOTSTRAP_DIR", "/zitadel/bootstrap")
ADMIN_PAT_PATH = os.path.join(BOOTSTRAP_DIR, "admin.pat")
GATEWAY_ENV_PATH = os.path.join(BOOTSTRAP_DIR, "gateway-client.env")
WEB_CLIENT_PATH = os.path.join(BOOTSTRAP_DIR, "web-client.json")

ZITADEL_URL = os.environ.get("ZITADEL_INTERNAL_URL", "http://zitadel:8080").rstrip("/")
AUTH_DOMAIN = os.environ["OGNA_AUTH_DOMAIN"]
EXTERNAL_PORT = os.environ.get("OGNA_AUTH_EXTERNAL_PORT", "8000")
EXTERNAL_SECURE = os.environ.get("OGNA_AUTH_EXTERNAL_SECURE", "false").lower() == "true"
PROJECT_NAME = os.environ.get("OGNA_AUTH_PROJECT_NAME", "OGNA")
GATEWAY_APP = "ogna-gateway"
WEB_APP = "ogna-web"
KONG_GID = int(os.environ.get("KONG_GID", "1000"))

SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.@-]+$")


def log(msg):
    print(f"[ogna-zitadel-setup] {msg}", flush=True)


def csv_env(name, default):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


def issuer():
    scheme = "https" if EXTERNAL_SECURE else "http"
    default_port = "443" if EXTERNAL_SECURE else "80"
    port = "" if EXTERNAL_PORT == default_port else f":{EXTERNAL_PORT}"
    return f"{scheme}://{AUTH_DOMAIN}{port}"


def read_admin_pat(timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(ADMIN_PAT_PATH, encoding="utf-8") as f:
                pat = f.read().strip()
            if pat:
                return pat
        except FileNotFoundError:
            pass
        log(f"waiting for {ADMIN_PAT_PATH} ...")
        time.sleep(3)
    sys.exit(f"admin PAT not found at {ADMIN_PAT_PATH}")


class Zitadel:
    def __init__(self, pat):
        self.pat = pat

    def call(self, method, path, body=None, retries=20):
        url = f"{ZITADEL_URL}/management/v1{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.pat}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Zitadel resolves the instance from the Host header
            "Host": AUTH_DOMAIN,
            "X-Forwarded-Proto": "https" if EXTERNAL_SECURE else "http",
        }
        for attempt in range(retries):
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")
                if e.code in (502, 503, 504) and attempt < retries - 1:
                    time.sleep(3)
                    continue
                sys.exit(f"{method} {path} failed: HTTP {e.code} {detail}")
            except urllib.error.URLError as e:
                if attempt < retries - 1:
                    log(f"Zitadel not reachable yet ({e.reason}), retrying ...")
                    time.sleep(3)
                    continue
                sys.exit(f"{method} {path} failed: {e.reason}")
        sys.exit(f"{method} {path} failed after {retries} attempts")

    def find_project(self, name):
        res = self.call("POST", "/projects/_search", {
            "queries": [{"nameQuery": {"name": name, "method": "TEXT_QUERY_METHOD_EQUALS"}}]
        })
        for project in res.get("result", []):
            if project.get("name") == name:
                return project["id"]
        return None

    def ensure_project(self, name):
        project_id = self.find_project(name)
        if project_id:
            log(f"project '{name}' exists ({project_id})")
            return project_id
        project_id = self.call("POST", "/projects", {"name": name})["id"]
        log(f"created project '{name}' ({project_id})")
        return project_id

    def find_app(self, project_id, name):
        res = self.call("POST", f"/projects/{project_id}/apps/_search", {
            "queries": [{"nameQuery": {"name": name, "method": "TEXT_QUERY_METHOD_EQUALS"}}]
        })
        for app in res.get("result", []):
            if app.get("name") == name:
                return app
        return None


def write_file(path, content, mode):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        os.chown(tmp, 0, KONG_GID)
    except (PermissionError, OSError):
        pass
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_env_file(path):
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    values[k] = v
    except FileNotFoundError:
        pass
    return values


def ensure_gateway_app(z, project_id):
    app = z.find_app(project_id, GATEWAY_APP)
    existing = read_env_file(GATEWAY_ENV_PATH)

    if app is None:
        res = z.call("POST", f"/projects/{project_id}/apps/api", {
            "name": GATEWAY_APP,
            "authMethodType": "API_AUTH_METHOD_TYPE_BASIC",
        })
        client_id, client_secret = res["clientId"], res["clientSecret"]
        log(f"created API app '{GATEWAY_APP}'")
    else:
        client_id = app["apiConfig"]["clientId"]
        if existing.get("OGNA_INTROSPECTION_CLIENT_ID") == client_id and existing.get("OGNA_INTROSPECTION_CLIENT_SECRET"):
            log(f"API app '{GATEWAY_APP}' exists, credentials file is current")
            return
        res = z.call("POST", f"/projects/{project_id}/apps/{app['id']}/api_config/_generate_client_secret", {})
        client_secret = res["clientSecret"]
        log(f"API app '{GATEWAY_APP}' exists, regenerated its client secret")

    for value in (client_id, client_secret):
        if not SAFE_VALUE.match(value):
            sys.exit("unexpected characters in gateway client credentials")
    write_file(
        GATEWAY_ENV_PATH,
        f"OGNA_INTROSPECTION_CLIENT_ID={client_id}\nOGNA_INTROSPECTION_CLIENT_SECRET={client_secret}\n",
        0o640,
    )


def ensure_web_app(z, project_id):
    redirect_uris = csv_env("OGNA_OIDC_REDIRECT_URIS", "http://localhost:8000/auth/callback,http://localhost:3000/auth/callback,http://localhost:5173/auth/callback")
    logout_uris = csv_env("OGNA_OIDC_POST_LOGOUT_URIS", "http://localhost:8000/,http://localhost:3000/,http://localhost:5173/")
    dev_mode = any(u.startswith("http://") for u in redirect_uris + logout_uris)
    config = {
        "redirectUris": redirect_uris,
        "postLogoutRedirectUris": logout_uris,
        "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
        "grantTypes": ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"],
        "appType": "OIDC_APP_TYPE_USER_AGENT",
        "authMethodType": "OIDC_AUTH_METHOD_TYPE_NONE",
        # Opaque tokens: every API call is checked against Zitadel by the gateway
        "accessTokenType": "OIDC_TOKEN_TYPE_BEARER",
        "devMode": dev_mode,
    }

    app = z.find_app(project_id, WEB_APP)
    if app is None:
        res = z.call("POST", f"/projects/{project_id}/apps/oidc", {"name": WEB_APP, "version": "OIDC_VERSION_1_0", **config})
        client_id = res["clientId"]
        log(f"created OIDC app '{WEB_APP}'")
    else:
        client_id = app["oidcConfig"]["clientId"]
        try:
            z.call("PUT", f"/projects/{project_id}/apps/{app['id']}/oidc_config", config, retries=1)
            log(f"updated OIDC app '{WEB_APP}' config")
        except SystemExit as e:
            # Zitadel answers 400 "No changes" when the config is identical
            if "No changes" not in str(e) and "COMMAND-1m88i" not in str(e):
                raise
            log(f"OIDC app '{WEB_APP}' config is current")

    info = {
        "issuer": issuer(),
        "client_id": client_id,
        "redirect_uris": redirect_uris,
        "post_logout_redirect_uris": logout_uris,
        "scopes": "openid profile email offline_access",
    }
    write_file(WEB_CLIENT_PATH, json.dumps(info, indent=2) + "\n", 0o644)
    log(f"OIDC issuer:    {info['issuer']}")
    log(f"OIDC client_id: {client_id}")


def main():
    z = Zitadel(read_admin_pat())
    project_id = z.ensure_project(PROJECT_NAME)
    ensure_gateway_app(z, project_id)
    ensure_web_app(z, project_id)
    log("done")


if __name__ == "__main__":
    main()

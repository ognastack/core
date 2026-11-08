"""Command-line interface for initializing and managing OGNA projects."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import string
import subprocess
import sys

from ogna_cli import __version__
from ogna_cli.templates import (
    CORE_COMPOSE_YAML,
    ENV_TEMPLATE,
    GITIGNORE_TEMPLATE,
    STARTER_API_DOCKERFILE,
    STARTER_API_MAIN,
    STARTER_API_REQUIREMENTS,
    STARTER_MIGRATION_SQL,
    STARTER_README,
    STORAGE_COMPOSE_YAML,
    USER_COMPOSE_BUILD_YAML,
    USER_COMPOSE_IMAGE_YAML,
)


def _generate_secret(length: int = 48) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ensure_ogna_runtime_files(project_dir: Path, force: bool = False) -> Path:
    """Ensure `.ogna/docker-compose.core.yaml` and `.ogna/docker-compose.storage.yaml` exist."""
    ogna_dir = project_dir / ".ogna"
    ogna_dir.mkdir(parents=True, exist_ok=True)

    core_compose = ogna_dir / "docker-compose.core.yaml"
    if force or not core_compose.exists():
        core_compose.write_text(CORE_COMPOSE_YAML, encoding="utf-8")

    storage_compose = ogna_dir / "docker-compose.storage.yaml"
    if force or not storage_compose.exists():
        storage_compose.write_text(STORAGE_COMPOSE_YAML, encoding="utf-8")

    return ogna_dir


def _write_if_missing(path: Path, content: str, force: bool = False) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _update_env_var(env_path: Path, key: str, value: str) -> None:
    """Update or append a KEY="value" entry in a .env file."""
    if not env_path.exists():
        env_path.write_text(f'{key}="{value}"\n', encoding="utf-8")
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replaced = False
    new_lines: list[str] = []
    for line in lines:
        if pattern.match(line):
            new_lines.append(f'{key}="{value}"')
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f'{key}="{value}"')
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _compose_base_cmd(
    project_dir: Path,
    external_s3: bool = False,
    no_api: bool = False,
) -> list[str]:
    _ensure_ogna_runtime_files(project_dir)

    cmd = [
        "docker",
        "compose",
        "--project-directory",
        str(project_dir),
    ]
    env_file = project_dir / ".env"
    if env_file.exists():
        cmd.extend(["--env-file", str(env_file)])

    cmd.extend(["-f", str(project_dir / ".ogna" / "docker-compose.core.yaml")])

    if not external_s3:
        cmd.extend(["-f", str(project_dir / ".ogna" / "docker-compose.storage.yaml")])

    user_compose = project_dir / "docker-compose.yaml"
    if not no_api and user_compose.exists():
        cmd.extend(["-f", str(user_compose)])

    return cmd


def cmd_init(args: argparse.Namespace) -> int:
    target_dir = Path(args.directory).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    project_name = args.name or target_dir.name or "ogna-app"
    sanitized_db = re.sub(r"[^a-zA-Z0-9_]", "_", project_name.lower()).strip("_") or "ogna_db"
    api_image = args.api_image or ("ogna-local-api:dev" if args.scaffold_api else "ogna-py-appi:prod")

    _ensure_ogna_runtime_files(target_dir, force=args.force)

    # Generate secure secrets for .env
    env_content = ENV_TEMPLATE.format(
        postgres_password=_generate_secret(32),
        project_db=sanitized_db,
        encryption_key=_generate_secret(50),
        jwt_secret=_generate_secret(50),
        api_image=api_image,
        s3_secret=_generate_secret(32),
        hasura_secret=_generate_secret(40),
        gateway_db_password=_generate_secret(40),
    )
    env_example_content = ENV_TEMPLATE.format(
        postgres_password="change_me_postgres_password",
        project_db=sanitized_db,
        encryption_key="change_me_50_char_encryption_key_000000000000000000",
        jwt_secret="change_me_50_char_gotrue_jwt_secret_000000000000000",
        api_image=api_image,
        s3_secret="rustfsadmin",
        hasura_secret="change_me_hasura_admin_secret",
        gateway_db_password="change_me_gateway_db_password",
    )

    created_files: list[str] = [".ogna/docker-compose.core.yaml", ".ogna/docker-compose.storage.yaml"]

    if _write_if_missing(target_dir / ".env", env_content, force=args.force):
        created_files.append(".env")
    if _write_if_missing(target_dir / ".env.example", env_example_content, force=args.force):
        created_files.append(".env.example")
    if _write_if_missing(target_dir / ".gitignore", GITIGNORE_TEMPLATE, force=args.force):
        created_files.append(".gitignore")

    compose_template = USER_COMPOSE_BUILD_YAML if args.scaffold_api else USER_COMPOSE_IMAGE_YAML
    if _write_if_missing(target_dir / "docker-compose.yaml", compose_template, force=args.force):
        created_files.append("docker-compose.yaml")
    if _write_if_missing(
        target_dir / "README.md",
        STARTER_README.format(project_name=project_name),
        force=args.force,
    ):
        created_files.append("README.md")

    # Migrations folder
    migrations_dir = target_dir / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    if not list(migrations_dir.glob("*.sql")) or args.force:
        init_mig = migrations_dir / "20260101000000_init.sql"
        if _write_if_missing(init_mig, STARTER_MIGRATION_SQL, force=args.force):
            created_files.append(f"migrations/{init_mig.name}")

    # User Hasura tables metadata folder (auto-merged with OGNA core metadata)
    hasura_tables_dir = target_dir / "hasura" / "tables"
    hasura_tables_dir.mkdir(parents=True, exist_ok=True)
    gitkeep = hasura_tables_dir / ".gitkeep"
    if _write_if_missing(gitkeep, "", force=args.force):
        created_files.append("hasura/tables/.gitkeep")

    # Optional starter API service scaffold
    if args.scaffold_api:
        api_dir = target_dir / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        if _write_if_missing(api_dir / "Dockerfile", STARTER_API_DOCKERFILE, force=args.force):
            created_files.append("api/Dockerfile")
        if _write_if_missing(api_dir / "requirements.txt", STARTER_API_REQUIREMENTS, force=args.force):
            created_files.append("api/requirements.txt")
        if _write_if_missing(api_dir / "main.py", STARTER_API_MAIN, force=args.force):
            created_files.append("api/main.py")

    print(f"Initialized OGNA project '{project_name}' in {target_dir}")
    print(f"  API Image: {api_image}")
    for rel in created_files:
        print(f"  + {rel}")

    print("\nNext steps:")
    if target_dir != Path.cwd().resolve():
        print(f"  cd {target_dir.name}")
    print("  ogna set-api <your-backend-image:tag>   # Swap your backend container image")
    print("  ogna up -d                              # Start the stack")
    return 0


def _read_env_var(env_path: Path, key: str) -> str:
    if not env_path.exists():
        return ""
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line)
        if m:
            val = m.group(1).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            return val
    return ""


def cmd_set_api(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    env_path = project_dir / ".env"
    _update_env_var(env_path, "API_IMAGE", args.image)
    print(f"Updated API_IMAGE={args.image} in {env_path}")

    if args.restart:
        cmd = _compose_base_cmd(project_dir)
        cmd.extend(["up", "-d", "--no-deps", "api"])
        return subprocess.call(cmd, cwd=project_dir)
    return 0


def cmd_add_service(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    compose_path = project_dir / "docker-compose.yaml"
    if not compose_path.exists():
        print(
            "Error: No docker-compose.yaml found in project directory. Run `ogna init` first.",
            file=sys.stderr,
        )
        return 1

    svc_name = re.sub(r"[^a-zA-Z0-9_-]", "-", args.name.strip().lower()).strip("-")
    if not svc_name:
        print("Error: Invalid service name.", file=sys.stderr)
        return 1

    existing = compose_path.read_text(encoding="utf-8")
    if re.search(rf"^\s{{2}}{re.escape(svc_name)}\s*:", existing, flags=re.MULTILINE):
        print(f"Error: Service '{svc_name}' already exists in {compose_path.name}.", file=sys.stderr)
        return 1

    port = args.port or 8000
    service_block = f"""
  {svc_name}:
    image: {args.image}
    container_name: {svc_name}
    restart: unless-stopped
    depends_on:
      - postgres
      - kong-cp
    expose:
      - "{port}"
    networks:
      - gql
      - api
    env_file:
      - .env
"""
    compose_path.write_text(existing.rstrip() + "\n" + service_block, encoding="utf-8")
    print(f"Added service '{svc_name}' ({args.image}) to {compose_path.name}")

    if args.route:
        route_path = args.route if args.route.startswith("/") else f"/{args.route}"
        auth_mode = "public" if args.public else "jwt"
        route_entry = f"{svc_name}=http://{svc_name}:{port}:{route_path}:{auth_mode}"

        env_path = project_dir / ".env"
        current_routes = _read_env_var(env_path, "OGNA_EXTRA_ROUTES")
        entries = [e.strip() for e in current_routes.split(",") if e.strip()]
        entries = [e for e in entries if not e.startswith(f"{svc_name}=")]
        entries.append(route_entry)
        _update_env_var(env_path, "OGNA_EXTRA_ROUTES", ",".join(entries))
        print(
            f"Registered Kong gateway route '{route_path}' -> http://{svc_name}:{port} (auth: {auth_mode}) in .env"
        )

    return 0


def cmd_up(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    env_path = project_dir / ".env"
    if not env_path.exists():
        print(
            "Error: No .env file found in current directory. Run `ogna init` first.",
            file=sys.stderr,
        )
        return 1

    env = os.environ.copy()
    if args.api_image:
        _update_env_var(env_path, "API_IMAGE", args.api_image)
        env["API_IMAGE"] = args.api_image

    cmd = _compose_base_cmd(
        project_dir,
        external_s3=args.external_s3,
        no_api=args.no_api,
    )
    cmd.append("up")
    if args.detach:
        cmd.append("-d")
    if args.build:
        cmd.append("--build")
    if args.services:
        cmd.extend(args.services)

    return subprocess.call(cmd, cwd=project_dir, env=env)


def cmd_down(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    cmd = _compose_base_cmd(project_dir, external_s3=False, no_api=False)
    cmd.extend(["down", "--remove-orphans"])
    if args.volumes:
        cmd.append("-v")
    return subprocess.call(cmd, cwd=project_dir)


def cmd_logs(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    cmd = _compose_base_cmd(project_dir)
    cmd.append("logs")
    if args.follow:
        cmd.append("-f")
    if args.tail:
        cmd.extend(["--tail", str(args.tail)])
    if args.services:
        cmd.extend(args.services)
    return subprocess.call(cmd, cwd=project_dir)


def cmd_status(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    cmd = _compose_base_cmd(project_dir)
    cmd.append("ps")
    rc = subprocess.call(cmd, cwd=project_dir)
    print("\nOGNA Endpoints (via Kong Gateway on http://localhost:8000):")
    print("  - Dashboard:  http://localhost:8000/")
    print("  - Auth API:   http://localhost:8000/auth")
    print("  - App API:    http://localhost:8000/api")
    print("  - Storage:    http://localhost:8000/storage")
    print("  - GraphQL:    http://localhost:8000/graphql")
    return rc


def cmd_migration_new(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    migrations_dir = project_dir / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", args.name.strip().lower()).strip("_")
    if not slug:
        print("Error: Invalid migration name.", file=sys.stderr)
        return 1

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    filename = f"{timestamp}_{slug}.sql"
    filepath = migrations_dir / filename
    filepath.write_text(
        "-- migrate:up\n\n\n-- migrate:down\n",
        encoding="utf-8",
    )
    print(f"Created migration: migrations/{filename}")
    return 0


def cmd_track_table(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    tables_dir = project_dir / "hasura" / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    raw_table = args.table.strip()
    if "." in raw_table:
        schema_name, table_name = raw_table.split(".", 1)
    else:
        schema_name, table_name = "public", raw_table

    schema_name = re.sub(r"[^a-zA-Z0-9_]", "", schema_name) or "public"
    table_name = re.sub(r"[^a-zA-Z0-9_]", "", table_name)
    if not table_name:
        print("Error: Invalid table name.", file=sys.stderr)
        return 1

    cols = [c.strip() for c in (args.columns or "*").split(",") if c.strip()]
    if cols == ["*"]:
        cols_yaml = '"*"'
    else:
        cols_yaml = "\n" + "\n".join(f"        - {c}" for c in cols)

    owner_col = args.owner_column
    if owner_col:
        filter_block = f"""      filter:
        {owner_col}:
          _eq: X-Hasura-User-Id"""
        set_block = f"""      set:
        {owner_col}: X-Hasura-User-Id"""
        check_block = f"""      check:
        {owner_col}:
          _eq: X-Hasura-User-Id"""
    else:
        filter_block = "      filter: {}"
        set_block = ""
        check_block = "      check: {}"

    insert_set_section = f"\n{set_block}" if set_block else ""

    yaml_content = f"""table:
  schema: {schema_name}
  name: {table_name}

select_permissions:
  - role: authenticated
    permission:
      columns: {cols_yaml}
{filter_block}

insert_permissions:
  - role: authenticated
    permission:
      columns: {cols_yaml}{insert_set_section}
{check_block}

update_permissions:
  - role: authenticated
    permission:
      columns: {cols_yaml}
{filter_block}
{check_block}

delete_permissions:
  - role: authenticated
    permission:
{filter_block}
"""

    out_file = tables_dir / f"{schema_name}_{table_name}.yaml"
    out_file.write_text(yaml_content, encoding="utf-8")
    print(f"Created Hasura table metadata: hasura/tables/{out_file.name}")
    print("Run `ogna up -d` (or `docker compose restart hasura`) to merge and apply metadata.")
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    project_dir = Path(args.project_dir).resolve()
    env_path = project_dir / ".env"
    if not env_path.exists():
        print("Error: No .env file found. Run `ogna init` first.", file=sys.stderr)
        return 1

    enable_val = "false" if args.disable else "true"
    _update_env_var(env_path, "HASURA_GRAPHQL_ENABLE_CONSOLE", enable_val)
    _update_env_var(env_path, "HASURA_GRAPHQL_DEV_MODE", enable_val)

    if args.disable:
        print("Disabled Hasura Console and Dev Mode in .env.")
    else:
        secret = _read_env_var(env_path, "HASURA_GRAPHQL_ADMIN_SECRET")
        port = _read_env_var(env_path, "HASURA_CONSOLE_PORT") or "8080"
        print("Enabled Hasura Console in .env:")
        print(f"  - Console URL:  http://127.0.0.1:{port}/console")
        print(f"  - Admin Secret: {secret}")

    if args.restart:
        cmd = _compose_base_cmd(project_dir)
        cmd.extend(["up", "-d", "--no-deps", "hasura"])
        return subprocess.call(cmd, cwd=project_dir)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ogna",
        description="OGNA Backend Stack CLI — scaffold and manage OGNA projects with a swappable API container.",
    )
    parser.add_argument("--version", action="version", version=f"ogna {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ogna init
    p_init = subparsers.add_parser("init", help="Scaffold a new OGNA project in a clean directory")
    p_init.add_argument("directory", nargs="?", default=".", help="Target directory (default: current directory)")
    p_init.add_argument("--name", help="Project name (defaults to directory name)")
    p_init.add_argument(
        "--api-image",
        help="Docker image for your backend API container (default: ogna-py-appi:prod)",
    )
    p_init.add_argument(
        "--scaffold-api",
        action="store_true",
        help="Also generate a local starter ./api folder with a Dockerfile",
    )
    p_init.add_argument("--force", action="store_true", help="Overwrite existing template files")
    p_init.set_defaults(func=cmd_init)

    # ogna set-api
    p_set_api = subparsers.add_parser("set-api", help="Swap the backend API Docker image in .env")
    p_set_api.add_argument("image", help="Docker image name:tag (e.g. my-org/my-api:latest)")
    p_set_api.add_argument(
        "-r",
        "--restart",
        action="store_true",
        help="Immediately recreate and restart the running `api` container with the new image",
    )
    p_set_api.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_set_api.set_defaults(func=cmd_set_api)

    # ogna add-service
    p_add_svc = subparsers.add_parser(
        "add-service",
        help="Add an extra container service to docker-compose.yaml (with optional Kong route)",
    )
    p_add_svc.add_argument("name", help="Service name (e.g. payments, worker, ml-engine)")
    p_add_svc.add_argument("--image", required=True, help="Docker image for the service")
    p_add_svc.add_argument("--port", type=int, default=8000, help="Internal container port (default: 8000)")
    p_add_svc.add_argument(
        "--route",
        help="Optional Kong gateway route path (e.g. /payments) to expose this service through Kong",
    )
    p_add_svc.add_argument(
        "--public",
        action="store_true",
        help="If --route is specified, make the route public (skip JWT requirement)",
    )
    p_add_svc.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_add_svc.set_defaults(func=cmd_add_service)

    # ogna up
    p_up = subparsers.add_parser("up", help="Start the OGNA stack")
    p_up.add_argument("-d", "--detach", action="store_true", help="Run containers in the background")
    p_up.add_argument("--api-image", help="Swap API_IMAGE in .env and start with this backend image")
    p_up.add_argument("--build", action="store_true", help="Build images before starting containers")
    p_up.add_argument("--external-s3", action="store_true", help="Do not start local RustFS S3 container")
    p_up.add_argument("--no-api", action="store_true", help="Start only OGNA core services without user API")
    p_up.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_up.add_argument("services", nargs="*", help="Optional specific services to start")
    p_up.set_defaults(func=cmd_up)

    # ogna down
    p_down = subparsers.add_parser("down", help="Stop the OGNA stack")
    p_down.add_argument("-v", "--volumes", action="store_true", help="Remove named volumes (wipes local DB data)")
    p_down.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_down.set_defaults(func=cmd_down)

    # ogna logs
    p_logs = subparsers.add_parser("logs", help="View container logs")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p_logs.add_argument("-n", "--tail", type=int, help="Number of lines to show from the end of logs")
    p_logs.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_logs.add_argument("services", nargs="*", help="Optional specific services")
    p_logs.set_defaults(func=cmd_logs)

    # ogna status / ps
    for alias in ("status", "ps"):
        p_status = subparsers.add_parser(alias, help="Show status of OGNA services and endpoints")
        p_status.add_argument("-C", "--project-dir", default=".", help="Project directory")
        p_status.set_defaults(func=cmd_status)

    # ogna migration new <name>
    p_mig = subparsers.add_parser("migration", help="Manage application SQL migrations")
    mig_sub = p_mig.add_subparsers(dest="migration_command", required=True)
    p_mig_new = mig_sub.add_parser("new", help="Create a new timestamped SQL migration in ./migrations")
    p_mig_new.add_argument("name", help="Migration name (e.g. create_profiles_table)")
    p_mig_new.set_defaults(func=cmd_migration_new)
    p_mig_new.add_argument("-C", "--project-dir", default=".", help="Project directory")

    # ogna track-table <[schema.]table>
    p_track = subparsers.add_parser(
        "track-table",
        help="Generate Hasura table & permission metadata in ./hasura/tables/ (auto-merged on startup)",
    )
    p_track.add_argument("table", help="Table name, optionally prefixed with schema (e.g. public.profiles)")
    p_track.add_argument(
        "--owner-column",
        help="Optional UUID column referencing auth.users(id) (e.g. user_id or owner) to scope row-level permissions to X-Hasura-User-Id",
    )
    p_track.add_argument(
        "--columns",
        default="*",
        help="Comma-separated list of allowed columns (default: '*')",
    )
    p_track.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_track.set_defaults(func=cmd_track_table)

    # ogna console
    p_console = subparsers.add_parser(
        "console",
        help="Enable/disable the local Hasura Admin Console (http://127.0.0.1:8080/console) and print admin secret",
    )
    p_console.add_argument("--disable", action="store_true", help="Disable Hasura Console & Dev Mode in .env")
    p_console.add_argument(
        "-r",
        "--restart",
        action="store_true",
        help="Immediately recreate/restart the `hasura` container to apply the console setting",
    )
    p_console.add_argument("-C", "--project-dir", default=".", help="Project directory")
    p_console.set_defaults(func=cmd_console)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

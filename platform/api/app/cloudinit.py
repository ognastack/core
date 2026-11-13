"""cloud-init user data for a new project VPS.

Prepares the machine (Docker, firewall, no password logins, automatic security
updates) and leaves the one-time enrollment token where the OGNA agent will
read it. The agent itself is installed only when OGNA_AGENT_INSTALL_URL is set.
"""

from __future__ import annotations

import json

from .config import Settings
from .models import Project


def _q(value: str) -> str:
    """Quote a scalar for YAML (JSON strings are valid YAML)."""
    return json.dumps(value)


def render_user_data(project: Project, enrollment_token: str, settings: Settings) -> str:
    agent_env = "\n".join([
        f"OGNA_CONTROL_PLANE_URL={settings.control_plane_url}",
        f"OGNA_PROJECT_ID={project.id}",
        f"OGNA_ENROLLMENT_TOKEN={enrollment_token}",
    ]) + "\n"

    runcmd = [
        # Docker Engine from Docker's official install script
        "curl -fsSL https://get.docker.com -o /tmp/get-docker.sh && sh /tmp/get-docker.sh",
        "systemctl enable --now docker",
        # Host firewall: only SSH and the gateway's HTTP(S). Note: ports published by
        # Docker bypass ufw, so the stack must only publish 80/443 (or use a provider firewall).
        "ufw default deny incoming",
        "ufw default allow outgoing",
        "ufw allow OpenSSH",
        "ufw allow 80/tcp",
        "ufw allow 443/tcp",
        "ufw --force enable",
        "systemctl restart ssh || systemctl restart sshd",
    ]
    if settings.agent_install_url:
        runcmd.append(f"curl -fsSL {settings.agent_install_url} -o /tmp/install-agent.sh && sh /tmp/install-agent.sh")

    lines = [
        "#cloud-config",
        f"hostname: {_q('ogna-' + project.slug)}",
        "package_update: true",
        "package_upgrade: true",
        "packages:",
        "  - ca-certificates",
        "  - curl",
        "  - ufw",
        "  - unattended-upgrades",
        "  - fail2ban",
        "write_files:",
        "  - path: /etc/ogna/agent.env",
        "    permissions: '0600'",
        "    owner: root:root",
        f"    content: {_q(agent_env)}",
        "  - path: /etc/ssh/sshd_config.d/99-ogna.conf",
        "    permissions: '0644'",
        f"    content: {_q('PasswordAuthentication no' + chr(10) + 'PermitRootLogin prohibit-password' + chr(10))}",
        "  - path: /etc/apt/apt.conf.d/20auto-upgrades",
        "    permissions: '0644'",
        f"    content: {_q('APT::Periodic::Update-Package-Lists \"1\";' + chr(10) + 'APT::Periodic::Unattended-Upgrade \"1\";' + chr(10))}",
        "runcmd:",
        *[f"  - {_q(cmd)}" for cmd in runcmd],
    ]
    return "\n".join(lines) + "\n"

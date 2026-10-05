from __future__ import annotations

import os
import secrets
import subprocess
import sys
from urllib.parse import quote, urlsplit, urlunsplit

from provision_database_roles import ROLE_NAMES, provision_database_roles

LOCAL_ADMIN_DATABASE_URL = (
    "postgresql://agentledger:agentledger@127.0.0.1:55439/agentledger_dev"
)


def role_url(admin_database_url: str, role_name: str, password: str) -> str:
    parsed = urlsplit(admin_database_url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit(
        (
            parsed.scheme,
            f"{quote(role_name)}:{quote(password, safe='')}@{host}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def main() -> int:
    admin_database_url = os.environ.get(
        "DATABASE_ADMIN_URL",
        os.environ.get("DATABASE_URL", LOCAL_ADMIN_DATABASE_URL),
    )
    passwords = {name: secrets.token_urlsafe(36) for name in ROLE_NAMES}
    provision_database_roles(admin_database_url, passwords)

    environment = os.environ.copy()
    environment["DATABASE_URL"] = admin_database_url
    environment["OWNER_DATABASE_URL"] = role_url(
        admin_database_url,
        "agentledger_owner",
        passwords["agentledger_owner"],
    )
    environment["APP_DATABASE_URL"] = role_url(
        admin_database_url,
        "agentledger_app",
        passwords["agentledger_app"],
    )
    environment["WORKER_DATABASE_URL"] = role_url(
        admin_database_url,
        "agentledger_worker",
        passwords["agentledger_worker"],
    )
    environment["AGENTLEDGER_RLS_TESTS"] = "1"

    subprocess.run(  # noqa: S603
        [sys.executable, "manage.py", "migrate", "--noinput"],
        check=True,
        env=environment,
    )
    arguments = sys.argv[1:] or ["-m", "rls"]
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", *arguments],
        check=False,
        env=environment,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())

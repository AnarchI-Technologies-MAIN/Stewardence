from __future__ import annotations

import os
from collections.abc import Mapping

import psycopg
from psycopg import sql

ROLE_NAMES = (
    "agentledger_owner",
    "agentledger_app",
    "agentledger_worker",
)


def provision_database_roles(
    admin_database_url: str,
    passwords: Mapping[str, str],
) -> None:
    if set(passwords) != set(ROLE_NAMES):
        raise ValueError(
            "Passwords must be supplied for every AgentLedger database role"
        )
    if any(len(passwords[name]) < 32 for name in ROLE_NAMES):
        raise ValueError("Database role passwords must contain at least 32 characters")

    with psycopg.connect(admin_database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            administrator = cursor.fetchone()[0]

            for role_name in ROLE_NAMES:
                cursor.execute(
                    sql.SQL(
                        "DO $$ BEGIN "
                        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {}) "
                        "THEN CREATE ROLE {} LOGIN; END IF; END $$"
                    ).format(sql.Literal(role_name), sql.Identifier(role_name))
                )
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}"
                    ).format(
                        sql.Identifier(role_name),
                        sql.Literal(passwords[role_name]),
                    )
                )

            cursor.execute(
                sql.SQL("GRANT {} TO {} WITH ADMIN OPTION").format(
                    sql.Identifier("agentledger_owner"),
                    sql.Identifier(administrator),
                )
            )
            cursor.execute("SELECT current_database()")
            database_name = cursor.fetchone()[0]
            cursor.execute(
                sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier("agentledger_owner"),
                )
            )


def main() -> int:
    admin_database_url = os.environ.get("DATABASE_ADMIN_URL", "")
    passwords = {
        "agentledger_owner": os.environ.get("AGENTLEDGER_OWNER_DB_PASSWORD", ""),
        "agentledger_app": os.environ.get("AGENTLEDGER_APP_DB_PASSWORD", ""),
        "agentledger_worker": os.environ.get("AGENTLEDGER_WORKER_DB_PASSWORD", ""),
    }
    if not admin_database_url:
        raise SystemExit("DATABASE_ADMIN_URL is required")
    provision_database_roles(admin_database_url, passwords)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

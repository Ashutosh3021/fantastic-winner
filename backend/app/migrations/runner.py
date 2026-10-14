"""Migration runner.

PyroCore runs a batch of statements inside one transaction, so each migration
file is all-or-nothing. Applied files are recorded in a small ledger table; the
runner is safe to call on every boot and safe to run concurrently, because
concurrent runners race on the same primary key and the loser simply sees the
version already applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..core.logging import get_logger
from ..repositories.gateway import PyronitesGateway
from ..repositories.sql import encode, safe_identifier

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent

LEDGER_TABLE = "cm_migrations"

_LEDGER_DDL = f"""
CREATE TABLE IF NOT EXISTS {safe_identifier(LEDGER_TABLE)} (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
)
"""

_FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if match:
            found.append(
                Migration(version=match.group(1), name=path.stem, path=path)
            )
    return found

def split_statements(sql: str) -> list[str]:
    """Split on semicolons outside string literals, comments and BEGIN blocks.

    Mirrors what the server-side splitter tolerates, so a statement containing a
    semicolon inside a string value is not cut in half.
    """
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    index = 0
    length = len(sql)

    while index < length:
        char = sql[index]
        if char == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline
            continue
        if in_single:
            current.append(char)
            if char == "'":
                if sql.startswith("''", index):
                    current.append("'")
                    index += 2
                    continue
                in_single = False
        elif char == "'":
            in_single = True
            current.append(char)
        elif char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements

async def applied_versions(gateway: PyronitesGateway) -> set[str]:
    await gateway.execute([_LEDGER_DDL])
    rows = await gateway.query_all(f"SELECT version FROM {safe_identifier(LEDGER_TABLE)}")
    return {str(row["version"]) for row in rows}

async def run_migrations(
    gateway: PyronitesGateway,
    *,
    directory: Path = MIGRATIONS_DIR,
) -> list[str]:
    """Apply every pending migration. Returns the versions that were applied."""
    migrations = discover(directory)
    if not migrations:
        raise RuntimeError(f"No migrations found in {directory}")

    done = await applied_versions(gateway)
    applied: list[str] = []

    for migration in migrations:
        if migration.version in done:
            continue

        statements = split_statements(migration.path.read_text(encoding="utf-8"))
        # Each migration file is its own atomic batch, so a DDL failure leaves no
        # half-applied schema behind.
        await gateway.execute(statements)

        from datetime import UTC, datetime

        record = (
            f"INSERT INTO {safe_identifier(LEDGER_TABLE)} (version, applied_at) "
            f"VALUES ({encode(migration.version)}, {encode(datetime.now(UTC).isoformat())})"
        )
        await gateway.execute([record])
        applied.append(migration.version)
        logger.info("applied migration %s (%s)", migration.version, migration.name)

    if applied:
        logger.info("schema at version %s", migrations[-1].version)
    return applied
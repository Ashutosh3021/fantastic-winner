"""Apply pending schema migrations to PyroCore.

Run it before starting the API:

    python scripts/migrate.py

Loads ``backend/.env`` when present so local runs need no shell exports; in a
deployed container the environment is already set and the file is absent.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

def load_env_file(path: Path) -> None:
    """Minimal ``.env`` loader.

    Deliberately not python-dotenv: the backend's only dependency on env
    handling is reading ``KEY=value`` lines, and existing process variables win
    so a real environment always overrides the file.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

async def _main() -> int:
    load_env_file(BACKEND_ROOT / ".env")

    from app.core.config import get_settings
    from app.core.logging import get_logger
    from app.migrations.runner import run_migrations
    from app.repositories.gateway import PyronitesGateway

    log = get_logger("migrate")
    settings = get_settings()

    if not settings.pyronites.configured:
        log.error("PYRONITES_URL and PYRONITES_KEY must be set")
        return 2

    log.info(
        "target %s project=%s", settings.pyronites.url, settings.pyronites.project_slug
    )
    gateway = PyronitesGateway(settings)
    try:
        applied = await run_migrations(gateway)
    finally:
        await gateway.aclose()

    if applied:
        log.info("applied %s", ", ".join(applied))
    else:
        log.info("schema already up to date")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))

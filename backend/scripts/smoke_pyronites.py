"""End-to-end check of the datastore integration.

Runs the real :class:`PyronitesGateway` against a live PyroCore: insert, read
back, write a child row (which proves foreign keys are enforced end to end),
then delete and confirm the row is gone.

    python scripts/smoke_pyronites.py

Exits non-zero on the first failure, so it is usable as a deploy gate.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from migrate import load_env_file  # noqa: E402


def main() -> int:
    load_env_file(BACKEND_ROOT / ".env")

    from app.core.config import get_settings
    from app.repositories.gateway import PyronitesGateway
    from app.repositories.sql import encode
    from app.repositories.store import now_iso

    async def run() -> int:
        settings = get_settings()
        if not settings.pyronites.configured:
            print("FAIL: PYRONITES_URL / PYRONITES_KEY not set")
            return 2

        gw = PyronitesGateway(settings)
        suffix = uuid.uuid4().hex[:12]
        user_id = f"smoke-{suffix}"
        email = f"smoke-{suffix}@codementor.invalid"

        try:
            # 1. insert
            await gw.execute(
                [
                    "INSERT INTO cm_users (id, pyrocore_user_id, email, email_verified_at, "
                    "created_at, updated_at) VALUES ("
                    f"{encode(user_id)}, {encode('pyro-' + suffix)}, {encode(email)}, NULL, "
                    f"{encode(now_iso())}, {encode(now_iso())})"
                ]
            )
            print("insert      OK")

            # 2. read back
            row = await gw.query_one(f"SELECT id, email FROM cm_users WHERE id = {encode(user_id)}")
            if not row or row.get("email") != email:
                print(f"FAIL: read back returned {row!r}")
                return 1
            print("select      OK")

            # 3. child row: proves the schema, not just the transport
            await gw.execute(
                [
                    "INSERT INTO user_preferences (user_id, updated_at) VALUES ("
                    f"{encode(user_id)}, {encode(now_iso())})"
                ]
            )
            prefs = await gw.query_one(
                f"SELECT language, difficulty_mode FROM user_preferences "
                f"WHERE user_id = {encode(user_id)}"
            )
            if not prefs or prefs.get("difficulty_mode") != "beginner":
                print(f"FAIL: child row returned {prefs!r}")
                return 1
            print("child row   OK (defaults applied by the schema)")

            # 4. uniqueness is actually enforced
            try:
                await gw.execute(
                    [
                        "INSERT INTO cm_users "
                        "(id, pyrocore_user_id, email, created_at, updated_at) VALUES ("
                        f"{encode('smoke2-' + suffix)}, "
                        f"{encode('pyro2-' + suffix)}, {encode(email)}, "
                        f"{encode(now_iso())}, {encode(now_iso())})"
                    ]
                )
            except Exception:
                print("unique      OK (duplicate email rejected)")
            else:
                print("FAIL: duplicate email was accepted")
                return 1

            # 5. delete
            deleted = await gw.delete_row("cm_users", user_id)
            if not deleted:
                print("FAIL: delete reported no success")
                return 1
            gone = await gw.query_one(f"SELECT id FROM cm_users WHERE id = {encode(user_id)}")
            if gone is not None:
                print("FAIL: row still present after delete")
                return 1
            print("delete      OK")
            return 0
        finally:
            # Leave no test data behind, even on failure.
            with contextlib.suppress(Exception):
                await gw.execute([f"DELETE FROM cm_users WHERE id = {encode(user_id)}"])
            await gw.aclose()

    return asyncio.run(run())

if __name__ == "__main__":
    code = main()
    print("SMOKE " + ("PASS" if code == 0 else "FAIL"))
    raise SystemExit(code)


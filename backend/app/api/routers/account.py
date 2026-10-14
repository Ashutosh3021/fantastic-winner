"""Account and preferences.

``/me`` carries the usage snapshot because the extension's popup needs credits,
identity and preferences together on its first paint. Three round trips for one
render is a bad trade on a page the learner opens while reading a problem.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from ...schemas.models import (
    MeResponse,
    Preferences,
    PreferencesPatch,
    Usage,
)
from ..dependencies import CallerDep, ContainerDep, enforce_rate_limit

router = APIRouter(tags=["account"])


async def _usage(container: ContainerDep, caller: CallerDep) -> Usage:
    snapshot = await container.credits.usage(user_id=caller.identity.user_id)
    active = await container.sessions.count_in_progress(caller.identity.user_id)
    return await container.progress.usage(
        snapshot=snapshot,
        active_sessions=active,
        max_active_sessions=container.settings.credits.max_active_sessions,
    )


@router.get("/me", response_model=MeResponse)
async def read_me(container: ContainerDep, caller: CallerDep) -> dict[str, Any]:
    enforce_rate_limit(container, caller, route_class="light")
    usage = await _usage(container, caller)
    return await container.progress.me(
        caller.identity.user_id, usage=usage.model_dump(by_alias=True)
    )


@router.delete("/me", status_code=204)
async def delete_me(container: ContainerDep, caller: CallerDep) -> Response:
    """Delete the learner's data.

    Identity stays with PyroCore, which is the system of record for accounts; this
    removes everything CodeMentor holds about the learner. A 204 rather than a
    JSON null, so a retry after a network blip is naturally idempotent.
    """
    await container.progress.delete_account(caller.identity.user_id)
    return Response(status_code=204)


@router.put("/preferences", response_model=Preferences)
async def put_preferences(
    container: ContainerDep, caller: CallerDep, patch: PreferencesPatch
) -> Preferences:
    enforce_rate_limit(container, caller, route_class="light")
    data = patch.model_dump(exclude_none=True, by_alias=True)
    return await container.progress.save_preferences(caller.identity.user_id, data)


@router.get("/usage", response_model=Usage)
async def read_usage(container: ContainerDep, caller: CallerDep) -> Usage:
    enforce_rate_limit(container, caller, route_class="light")
    return await _usage(container, caller)

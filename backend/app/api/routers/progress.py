"""Read-only history plus the funnel event sink.

Events are accepted and never validated for truth. The extension sends what the
learner's UI actually did; the only rule is that a write must be idempotent, so
a retried beacon does not double-count a funnel step.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query

from ...repositories.store import new_id
from ...schemas.models import (
    EventsRequest,
    MistakeList,
    ProgressResponse,
    ReviewQueueResponse,
    SavedCardsResponse,
)
from ..dependencies import CallerDep, ContainerDep, enforce_rate_limit

router = APIRouter(tags=["progress"])


@router.get("/progress", response_model=ProgressResponse)
async def read_progress(container: ContainerDep, caller: CallerDep) -> ProgressResponse:
    enforce_rate_limit(container, caller, route_class="light")
    return await container.progress.progress(caller.identity.user_id)


@router.get("/mistakes", response_model=MistakeList)
async def read_mistakes(
    container: ContainerDep,
    caller: CallerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MistakeList:
    enforce_rate_limit(container, caller, route_class="light")
    return await container.progress.mistake_list(caller.identity.user_id, limit=limit)


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def read_review_queue(
    container: ContainerDep, caller: CallerDep
) -> ReviewQueueResponse:
    enforce_rate_limit(container, caller, route_class="light")
    return await container.progress.review_queue(caller.identity.user_id)


@router.get("/saved-cards", response_model=SavedCardsResponse)
async def read_saved_cards(
    container: ContainerDep, caller: CallerDep
) -> SavedCardsResponse:
    enforce_rate_limit(container, caller, route_class="light")
    return await container.progress.saved_cards_for(caller.identity.user_id)


@router.post("/events")
async def record_events(
    container: ContainerDep,
    caller: CallerDep,
    body: EventsRequest,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", max_length=200)
    ] = None,
) -> dict[str, int]:
    """Store funnel events.

    De-duplication is the caller's key plus the event name, so a retried beacon
    cannot double-count a funnel step.
    """
    enforce_rate_limit(container, caller, route_class="light")
    key = idempotency_key or new_id()
    accepted = await container.events.record_batch(
        user_id=caller.identity.user_id,
        events=[{"name": e.name, "props": e.props} for e in body.events],
        idempotency_key=key,
    )
    return {"accepted": accepted}


__all__ = ["router"]

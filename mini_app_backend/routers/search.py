"""Search endpoints used by Telegram Mini App."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from mini_app_backend.dependencies import require_auth_context
from mini_app_backend.schemas import AuthContext, SearchResponse
from mini_app_backend.services.music_service import music_service


router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search_tracks(
    query: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    auth: AuthContext = Depends(require_auth_context),
) -> SearchResponse:
    _ = auth
    q = query.strip()
    results = await music_service.search(query=q, limit=limit)
    return SearchResponse(query=q, limit=limit, count=len(results), items=results)


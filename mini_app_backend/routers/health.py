"""Health endpoints."""

from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "soul-king-mini-app", "timestamp": int(time.time())}


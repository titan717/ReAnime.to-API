#!/usr/bin/env python3

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://reanime.to"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, */*",
}

_client: Optional[httpx.AsyncClient] = None


# ============================================================
# FASTAPI LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client

    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=30.0,
            pool=10.0,
        ),
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
        ),
        headers=HEADERS,
        follow_redirects=True,
    )

    yield

    await _client.aclose()
    _client = None


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="ReAnime API",
    description="Custom API wrapper for the current Re:Anime API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# HTTP HELPER
# ============================================================

async def reanime_get(
    path: str,
    params: Optional[dict[str, Any]] = None,
) -> Any:

    if _client is None:
        raise HTTPException(
            status_code=503,
            detail="HTTP client is not ready",
        )

    url = f"{BASE_URL}{path}"

    try:
        response = await _client.get(
            url,
            params=params,
        )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Re:Anime request timed out",
        )

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Re:Anime request failed: {str(exc)}",
        )

    if response.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"Re:Anime endpoint not found: {path}",
        )

    if not response.is_success:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text[:500],
        )

    try:
        return response.json()

    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="Re:Anime returned invalid JSON",
        )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "ReAnime API",
        "version": "2.0.0",

        "endpoints": {
            "health":
                "GET /health",

            "search":
                "GET /search?q=naruto&limit=20&offset=0",

            "info":
                "GET /info/{anime_id}",

            "episodes":
                "GET /episodes/{anime_id}?limit=2000",

            "recommendations":
                "GET /recommendations/{anime_id}",

            "schedule":
                "GET /schedule?tz=Asia/Calcutta&week=0",

            "servers":
                "GET /servers/{anime_id}/{episode}?anilist_id=20",

            "stream":
                "GET /stream/{anime_id}/{episode}?server=HD-2&type=sub&anilist_id=20",
        },
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "ReAnime API",
        "upstream": BASE_URL,
    }


# ============================================================
# SEARCH
#
# Verified:
# GET /api/v1/search?limit=5&q=naruto
# ============================================================

@app.get("/search")
async def search(
    q: str = Query(
        ...,
        min_length=1,
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        0,
        ge=0,
    ),
):
    return await reanime_get(
        "/api/v1/search",
        {
            "limit": limit,
            "offset": offset,
            "q": q,
        },
    )


# ============================================================
# ANIME INFO
#
# Verified:
# GET /api/v1/anime/{anime_id}/meta
# ============================================================

@app.get("/info/{anime_id}")
async def anime_info(
    anime_id: str,
):
    return await reanime_get(
        f"/api/v1/anime/{anime_id}/meta"
    )


# ============================================================
# EPISODES
#
# Verified:
# GET /api/v1/anime/{anime_id}/episodes?limit=2000
# ============================================================

@app.get("/episodes/{anime_id}")
async def episodes(
    anime_id: str,
    limit: int = Query(
        2000,
        ge=1,
        le=5000,
    ),
):
    return await reanime_get(
        f"/api/v1/anime/{anime_id}/episodes",
        {
            "limit": limit,
        },
    )


# ============================================================
# RECOMMENDATIONS
#
# Verified:
# GET /api/v1/anime/{anime_id}/recommendations
# ============================================================

@app.get("/recommendations/{anime_id}")
async def recommendations(
    anime_id: str,
):
    return await reanime_get(
        f"/api/v1/anime/{anime_id}/recommendations"
    )


# ============================================================
# SCHEDULE
#
# Verified:
# GET /api/v1/schedule?tz=Asia/Calcutta&week=0
# ============================================================

@app.get("/schedule")
async def schedule(
    tz: str = Query(
        "Asia/Calcutta",
    ),
    week: int = Query(
        0,
        ge=-10,
        le=10,
    ),
):
    return await reanime_get(
        "/api/v1/schedule",
        {
            "tz": tz,
            "week": week,
        },
    )


# ============================================================
# GET SERVER INFORMATION
#
# Verified:
# GET /api/flix/{anilist_id}/{episode}
#
# Example:
# /api/flix/20/2
# ============================================================

@app.get("/servers/{anime_id}/{episode}")
async def servers(
    anime_id: str,
    episode: int,
    anilist_id: Optional[int] = Query(
        None,
        description="AniList ID",
    ),
):
    if episode < 1:
        raise HTTPException(
            status_code=400,
            detail="Episode must be >= 1",
        )

    # If the frontend already knows the AniList ID,
    # use it directly.
    if anilist_id is None:

        # Get anime metadata.
        meta = await reanime_get(
            f"/api/v1/anime/{anime_id}/meta"
        )

        # ReAnime normally exposes the AniList ID
        # in its metadata.
        anilist_id = meta.get("anilist_id")

        # Some responses may use "id".
        if not anilist_id:
            anilist_id = meta.get("id")

        if not anilist_id:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Could not determine AniList ID. "
                    "Pass ?anilist_id=..."
                ),
            )

    data = await reanime_get(
        f"/api/flix/{anilist_id}/{episode}"
    )

    return {
        "success": data.get(
            "success",
            False,
        ),

        "anime_id": anime_id,

        "anilist_id": anilist_id,

        "episode": episode,

        "servers": data.get(
            "servers",
            [],
        ),
    }


# ============================================================
# PLAYBACK HANDOFF
#
# This selects one of the server links returned by Re:Anime.
#
# Example:
# /stream/naruto-bjfend/2
#     ?server=HD-2
#     &type=sub
#     &anilist_id=20
#
# Returns the authorized embed/dataLink.
# ============================================================

@app.get("/stream/{anime_id}/{episode}")
async def stream(
    anime_id: str,
    episode: int,

    server: str = Query(
        "HD-2",
        description="HD-1 or HD-2",
    ),

    type: str = Query(
        "sub",
        pattern="^(sub|dub)$",
        description="sub or dub",
    ),

    anilist_id: Optional[int] = Query(
        None,
        description="AniList ID",
    ),
):
    if episode < 1:
        raise HTTPException(
            status_code=400,
            detail="Episode must be >= 1",
        )

    if server not in {
        "HD-1",
        "HD-2",
    }:
        raise HTTPException(
            status_code=400,
            detail="server must be HD-1 or HD-2",
        )

    # Determine AniList ID when it wasn't supplied.
    if anilist_id is None:

        meta = await reanime_get(
            f"/api/v1/anime/{anime_id}/meta"
        )

        anilist_id = meta.get(
            "anilist_id"
        )

        if not anilist_id:
            anilist_id = meta.get(
                "id"
            )

        if not anilist_id:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Could not determine AniList ID. "
                    "Pass ?anilist_id=..."
                ),
            )

    # Get the available servers.
    data = await reanime_get(
        f"/api/flix/{anilist_id}/{episode}"
    )

    available_servers = data.get(
        "servers",
        [],
    )

    # Find requested server + language.
    selected = None

    for item in available_servers:

        if (
            item.get("serverName") == server
            and item.get("dataType") == type
        ):
            selected = item
            break

    if selected is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Requested server unavailable",
                "server": server,
                "type": type,
                "available": available_servers,
            },
        )

    data_link = selected.get(
        "dataLink"
    )

    if not data_link:
        raise HTTPException(
            status_code=502,
            detail="Server did not provide a playback link",
        )

    return {
        "success": True,

        "anime_id": anime_id,

        "anilist_id": anilist_id,

        "episode": episode,

        "server": server,

        "type": type,

        "dataType": selected.get(
            "dataType"
        ),

        "softsub": selected.get(
            "softsub",
            False,
        ),

        "continue": selected.get(
            "continue",
            False,
        ),

        # Authorized embed/data link returned by Re:Anime.
        "url": data_link,
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000",
        )
    )

    uvicorn.run(
        "rean​ime:app",
        host="0.0.0.0",
        port=port,
        workers=1,
        reload=False,
    )

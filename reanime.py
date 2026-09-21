import json
import subprocess
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx

app = FastAPI(title="ReAnime API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPSTREAM_BASE = "https://reanime.to"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, */*",
}

async def fetch_reanime(endpoint: str, params: dict = None):
    url = f"{UPSTREAM_BASE}{endpoint}"
    async with httpx.AsyncClient(http2=False, timeout=15.0) as client:
        try:
            res = await client.get(url, params=params, headers=HEADERS)
            if res.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Upstream error {res.status_code}: {res.text[:300]}")
            return res.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Upstream connection error: {str(e)}")

import time

# Lightweight in-memory cache
_ANILIST_CACHE = {}
_SEASONS_CACHE = {}

async def anilist_graphql(query: str, variables: dict):
    cache_key = f"{query}:{str(variables)}"
    now = time.time()
    if cache_key in _ANILIST_CACHE:
        val, expiry = _ANILIST_CACHE[cache_key]
        if now < expiry:
            return val

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(
                "https://graphql.anilist.co",
                json={"query": query, "variables": variables},
                headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            if res.status_code == 200:
                data = res.json()
                _ANILIST_CACHE[cache_key] = (data, now + 3600)  # 1 hour cache
                return data
        except Exception:
            pass
        return None

async def search_reanime_by_title(title: str, anilist_id: int = None):
    try:
        data = await fetch_reanime("/api/v1/search", {"q": title, "limit": 10})
        results = data.get("results", [])
        if anilist_id:
            for r in results:
                if r.get("anilist_id") == anilist_id:
                    return r.get("anime_id")
        if results:
            return results[0].get("anime_id")
    except Exception:
        pass
    return None

@app.get("/health")
def health():
    return {"status": "ok", "service": "ReAnime API (Python)", "upstream": UPSTREAM_BASE}

@app.get("/search")
async def search(q: str, limit: int = 20, offset: int = 0):
    return await fetch_reanime("/api/v1/search", {"q": q, "limit": limit, "offset": offset})

@app.get("/info/{anime_id}")
async def info(anime_id: str):
    return await fetch_reanime(f"/api/v1/anime/{anime_id}/meta")

@app.get("/episodes/{anime_id}")
async def episodes(anime_id: str, limit: int = 2000):
    return await fetch_reanime(f"/api/v1/anime/{anime_id}/episodes", {"limit": limit})

@app.get("/recommendations/{anime_id}")
async def recommendations(anime_id: str):
    return await fetch_reanime(f"/api/v1/anime/{anime_id}/recommendations")

@app.get("/schedule")
async def schedule(tz: str = "Asia/Calcutta", week: int = 0):
    return await fetch_reanime("/api/v1/schedule", {"tz": tz, "week": week})

async def resolve_anilist_id(anime_id: str, anilist_id: int = None) -> int:
    if anilist_id:
        return anilist_id
    meta = await fetch_reanime(f"/api/v1/anime/{anime_id}/meta")
    aid = meta.get("anilist_id") or meta.get("id")
    if not aid:
        # Try searching anilist via title
        title_obj = meta.get("title", {})
        search_title = title_obj.get("english") or title_obj.get("romaji")
        if search_title:
            q = "query ($search: String) { Media (search: $search, type: ANIME) { id } }"
            resp = await anilist_graphql(q, {"search": search_title})
            if resp and resp.get("data", {}).get("Media"):
                aid = resp["data"]["Media"]["id"]
    if not aid:
        raise HTTPException(status_code=404, detail="Could not determine AniList ID. Pass ?anilist_id=...")
    return int(aid)

@app.get("/servers/{anime_id}/{episode}")
async def servers(anime_id: str, episode: int, anilist_id: int = None):
    if episode < 1:
        raise HTTPException(status_code=400, detail="Episode must be >= 1")
    aid = await resolve_anilist_id(anime_id, anilist_id)
    flix_data = await fetch_reanime(f"/api/flix/{aid}/{episode}")
    return {
        "success": flix_data.get("success", False),
        "anime_id": anime_id,
        "anilist_id": aid,
        "episode": episode,
        "servers": flix_data.get("servers", []),
        "intro_start": flix_data.get("intro_start"),
        "intro_end": flix_data.get("intro_end"),
        "outro_start": flix_data.get("outro_start"),
        "outro_end": flix_data.get("outro_end"),
    }

@app.get("/stream/{anime_id}/{episode}")
async def stream_episode(anime_id: str, episode: int, server: str = "HD-2", type: str = "sub", anilist_id: int = None):
    if episode < 1:
        raise HTTPException(status_code=400, detail="Episode must be >= 1")
    aid = await resolve_anilist_id(anime_id, anilist_id)
    flix_data = await fetch_reanime(f"/api/flix/{aid}/{episode}")
    servers_list = flix_data.get("servers", [])
    
    selected = None
    for s in servers_list:
        if s.get("serverName") == server and s.get("dataType") == type:
            selected = s
            break
    if not selected or not selected.get("dataLink"):
        raise HTTPException(status_code=404, detail={"error": "Requested server unavailable", "server": server, "type": type, "available": servers_list})
    
    link = selected["dataLink"]
    try:
        proc = subprocess.run(["node", "decrypt.mjs", link], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise HTTPException(status_code=502, detail=f"Decryption error: {proc.stderr.strip()}")
        decrypted = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Decryption timed out")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from decryptor: {proc.stdout}")

    return {
        "success": True,
        "anime_id": anime_id,
        "anilist_id": aid,
        "episode": episode,
        "server": server,
        "type": type,
        "dataType": selected.get("dataType"),
        "softsub": selected.get("softsub", False),
        "continue": selected.get("continue", False),
        **decrypted
    }

@app.get("/stream/from-link")
async def stream_from_link(link: str):
    if not link:
        raise HTTPException(status_code=400, detail="Query parameter 'link' is required")
    try:
        proc = subprocess.run(["node", "decrypt.mjs", link], capture_output=True, text=True, timeout=15)
        if proc.returncode != 0:
            raise HTTPException(status_code=502, detail=f"Decryption error: {proc.stderr.strip()}")
        decrypted = json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Decryption timed out")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail=f"Invalid JSON from decryptor: {proc.stdout}")
    return {"success": True, **decrypted}

async def fetch_media_node(media_id: int):
    q = '''
    query ($id: Int) {
      Media (id: $id, type: ANIME) {
        id
        title { romaji english }
        format
        episodes
        seasonYear
        relations {
          edges {
            relationType
            node {
              id
              title { romaji english }
              format
              episodes
              seasonYear
            }
          }
        }
      }
    }
    '''
    resp = await anilist_graphql(q, {"id": media_id})
    if resp and resp.get("data", {}).get("Media"):
        return resp["data"]["Media"]
    return None

async def get_tv_chain_for_anilist_id(media_id: int):
    visited = set()
    curr_id = media_id
    
    # Traverse UP PREQUELs
    for _ in range(10):
        if curr_id in visited:
            break
        visited.add(curr_id)
        media = await fetch_media_node(curr_id)
        if not media or not media.get("relations"):
            break
        prequel_id = None
        for edge in media["relations"]["edges"]:
            if edge["relationType"] == "PREQUEL" and edge["node"]["format"] in ("TV", "TV_SHORT"):
                prequel_id = edge["node"]["id"]
                break
        if prequel_id and prequel_id not in visited:
            curr_id = prequel_id
        else:
            break

    root_id = curr_id
    visited.clear()
    chain = []
    curr_id = root_id

    # Traverse DOWN SEQUELs
    for _ in range(20):
        if curr_id in visited:
            break
        visited.add(curr_id)
        media = await fetch_media_node(curr_id)
        if not media:
            break
        chain.append(media)
        
        sequel_id = None
        if media.get("relations"):
            for edge in media["relations"]["edges"]:
                if edge["relationType"] == "SEQUEL" and edge["node"]["format"] in ("TV", "TV_SHORT"):
                    sequel_id = edge["node"]["id"]
                    break
        if sequel_id and sequel_id not in visited:
            curr_id = sequel_id
        else:
            break

    return chain

@app.get("/seasons/{anime_id}")
async def get_seasons(anime_id: str):
    now = time.time()
    if anime_id in _SEASONS_CACHE:
        cached_val, expiry = _SEASONS_CACHE[anime_id]
        if now < expiry:
            return cached_val

    try:
        meta = await fetch_reanime(f"/api/v1/anime/{anime_id}/meta")
        title_obj = meta.get("title", {})
        search_title = title_obj.get("english") or title_obj.get("romaji") or anime_id
        
        anilist_id = None
        try:
            anilist_id = await resolve_anilist_id(anime_id)
        except Exception:
            # Fallback search via AniList GraphQL
            if search_title:
                q = "query ($search: String) { Media (search: $search, type: ANIME) { id } }"
                resp = await anilist_graphql(q, {"search": search_title})
                if resp and resp.get("data", {}).get("Media"):
                    anilist_id = resp["data"]["Media"]["id"]

        chain = []
        if anilist_id:
            chain = await get_tv_chain_for_anilist_id(int(anilist_id))

        seasons = []
        if chain:
            for idx, node in enumerate(chain):
                node_id = node["id"]
                node_title_obj = node.get("title", {})
                node_title = node_title_obj.get("english") or node_title_obj.get("romaji") or f"Season {idx+1}"
                ep_count = node.get("episodes") or 0
                
                # Resolve reanime anime_id
                season_anime_id = anime_id if (anilist_id and int(node_id) == int(anilist_id)) else None
                if not season_anime_id:
                    season_anime_id = await search_reanime_by_title(node_title, int(node_id))
                if not season_anime_id:
                    season_anime_id = anime_id

                seasons.append({
                    "season_number": idx + 1,
                    "anime_id": season_anime_id,
                    "anilist_id": int(node_id),
                    "title": node_title,
                    "episode_count": ep_count
                })
        else:
            eps_data = await fetch_reanime(f"/api/v1/anime/{anime_id}/episodes", {"limit": 2000})
            total_eps = eps_data.get("total") or len(eps_data.get("data", []))
            seasons = [
                {
                    "season_number": 1,
                    "anime_id": anime_id,
                    "anilist_id": int(anilist_id) if anilist_id else 0,
                    "title": search_title,
                    "episode_count": total_eps
                }
            ]

        result = {
            "anime_id": anime_id,
            "seasons": seasons
        }
        _SEASONS_CACHE[anime_id] = (result, time.time() + 1800)  # 30 min cache
        return result
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/seasons/{anime_id}/{season_number}/episodes")
async def get_season_episodes(anime_id: str, season_number: int):
    try:
        # Get seasons list for this anime
        seasons_res = await get_seasons(anime_id)
        seasons_list = seasons_res.get("seasons", [])
        
        target_season = None
        for s in seasons_list:
            if s.get("season_number") == season_number:
                target_season = s
                break
        
        if not target_season:
            raise HTTPException(status_code=404, detail="Season not found")
        
        season_anime_id = target_season.get("anime_id", anime_id)
        eps_data = await fetch_reanime(f"/api/v1/anime/{season_anime_id}/episodes", {"limit": 2000})
        return {
            "anime_id": anime_id,
            "season_number": season_number,
            "season_anime_id": season_anime_id,
            "episodes": eps_data.get("data", [])
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/")
def home():
    return {
        "name": "ReAnime API",
        "description": "Self-hosted anime streaming API with FlixCloud WASM & AES decryption and advanced AniList Seasons support",
        "docs": "/docs",
        "health": "/health"
    }


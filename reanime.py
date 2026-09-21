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

import os
import time

DATABASE_URL = os.getenv("DATABASE_URL")

CANONICAL_CATALOG_SEED = {
    "attack-on-titan": {
        "franchise": {
            "id": 1,
            "slug": "attack-on-titan",
            "title": "Attack on Titan",
            "description": "Humanity fights for survival against giant humanoid Titans."
        },
        "seasons": [
            {
                "id": 1,
                "season_number": 1,
                "title": "Season 1",
                "display_title": "Season 1",
                "parts": [
                    {
                        "id": 1,
                        "part_number": 1,
                        "title": "Season 1",
                        "display_title": "Season 1",
                        "reanime_id": "attack-on-titan-p9y2p9",
                        "anilist_id": 16498,
                        "format": "TV"
                    }
                ]
            },
            {
                "id": 2,
                "season_number": 2,
                "title": "Season 2",
                "display_title": "Season 2",
                "parts": [
                    {
                        "id": 2,
                        "part_number": 1,
                        "title": "Season 2",
                        "display_title": "Season 2",
                        "reanime_id": "attack-on-titan-season-2-nn7gs9",
                        "anilist_id": 20958,
                        "format": "TV"
                    }
                ]
            },
            {
                "id": 3,
                "season_number": 3,
                "title": "Season 3",
                "display_title": "Season 3",
                "parts": [
                    {
                        "id": 3,
                        "part_number": 1,
                        "title": "Season 3",
                        "display_title": "Season 3",
                        "reanime_id": "attack-on-titan-season-3-d5sm7p",
                        "anilist_id": 99147,
                        "format": "TV"
                    }
                ]
            },
            {
                "id": 4,
                "season_number": 4,
                "title": "Season 4",
                "display_title": "Season 4",
                "parts": [
                    {
                        "id": 4,
                        "part_number": 1,
                        "title": "Part 1",
                        "display_title": "Part 1",
                        "reanime_id": "attack-on-titan-final-season-z8gsmy",
                        "anilist_id": 110277,
                        "format": "TV"
                    },
                    {
                        "id": 5,
                        "part_number": 2,
                        "title": "Part 2",
                        "display_title": "Part 2",
                        "reanime_id": "attack-on-titan-final-season-part-2-s66894",
                        "anilist_id": 131681,
                        "format": "TV"
                    },
                    {
                        "id": 6,
                        "part_number": 3,
                        "title": "Final Chapters",
                        "display_title": "Final Chapters",
                        "reanime_id": "attack-on-titan-final-chapters-part-1-or1249",
                        "anilist_id": 146690,
                        "format": "SPECIAL"
                    }
                ]
            }
        ]
    }
}

REANIME_SLUG_MAP = {
    "attack-on-titan-p9y2p9": "attack-on-titan",
    "attack-on-titan-season-2-nn7gs9": "attack-on-titan",
    "attack-on-titan-season-3-d5sm7p": "attack-on-titan",
    "attack-on-titan-season-3-part-2-u8gdy6": "attack-on-titan",
    "attack-on-titan-final-season-z8gsmy": "attack-on-titan",
    "attack-on-titan-final-season-part-2-s66894": "attack-on-titan",
    "attack-on-titan-final-chapters-part-1-or1249": "attack-on-titan",
    "attack-on-titan": "attack-on-titan",
}

async def get_catalog_record(identifier: str):
    # Attempt DB lookup if DATABASE_URL is configured
    if DATABASE_URL:
        try:
            import asyncpg
            conn = await asyncpg.connect(DATABASE_URL, timeout=5.0)
            try:
                # Query franchise by slug, or by anime entry reanime_id, or season_part reanime_id
                row = await conn.fetchrow("""
                    SELECT f.id, f.slug, f.canonical_title, f.description
                    FROM franchises f
                    LEFT JOIN anime_entries ae ON ae.franchise_id = f.id
                    LEFT JOIN seasons s ON s.franchise_id = f.id
                    LEFT JOIN season_parts sp ON sp.season_id = s.id
                    WHERE f.slug = $1 OR ae.reanime_id = $1 OR sp.reanime_id = $1
                       OR CAST(ae.anilist_id AS text) = $1 OR CAST(sp.anilist_id AS text) = $1
                    LIMIT 1
                """, str(identifier))
                
                if row:
                    f_id = row['id']
                    f_slug = row['slug']
                    f_title = row['canonical_title']
                    f_desc = row['description']
                    
                    s_rows = await conn.fetch("""
                        SELECT id, season_number, canonical_title, display_title
                        FROM seasons
                        WHERE franchise_id = $1
                        ORDER BY season_number ASC
                    """, f_id)
                    
                    seasons = []
                    for sr in s_rows:
                        p_rows = await conn.fetch("""
                            SELECT id, part_number, canonical_title, display_title, reanime_id, anilist_id, format
                            FROM season_parts
                            WHERE season_id = $1
                            ORDER BY part_number ASC
                        """, sr['id'])
                        
                        parts = []
                        for pr in p_rows:
                            parts.append({
                                "id": pr['id'],
                                "part_number": pr['part_number'],
                                "title": pr['display_title'] or pr['canonical_title'],
                                "display_title": pr['display_title'],
                                "reanime_id": pr['reanime_id'],
                                "anilist_id": pr['anilist_id'],
                                "format": pr['format'] or "TV"
                            })
                            
                        seasons.append({
                            "id": sr['id'],
                            "season_number": sr['season_number'],
                            "title": sr['display_title'] or sr['canonical_title'],
                            "display_title": sr['display_title'],
                            "parts": parts
                        })
                        
                    return {
                        "franchise": {
                            "id": f_id,
                            "slug": f_slug,
                            "title": f_title,
                            "description": f_desc
                        },
                        "seasons": seasons
                    }
            finally:
                await conn.close()
        except Exception:
            pass  # Fallback to seed catalog or dynamic resolution
            
    # Check seed catalog fallback
    slug = REANIME_SLUG_MAP.get(str(identifier).lower())
    if not slug:
        for s_key in CANONICAL_CATALOG_SEED:
            if s_key in str(identifier).lower():
                slug = s_key
                break
                
    if slug and slug in CANONICAL_CATALOG_SEED:
        return CANONICAL_CATALOG_SEED[slug]
        
    return None

# Catalog Endpoints
@app.get("/catalog/resolve/{anime_id}")
@app.get("/catalog/anime/{anime_id}")
async def get_catalog_anime(anime_id: str):
    cat = await get_catalog_record(anime_id)
    if cat:
        return cat
    # Fallback to dynamic resolution formatted into catalog structure
    try:
        seasons_data = await get_seasons(anime_id)
        seasons_list = seasons_data.get("seasons", [])
        return {
            "franchise": {
                "id": anime_id,
                "slug": anime_id,
                "title": anime_id.replace("-", " ").title()
            },
            "seasons": [
                {
                    "id": s["season_number"],
                    "season_number": s["season_number"],
                    "title": s["title"],
                    "parts": [
                        {
                            "id": s["season_number"],
                            "part_number": 1,
                            "title": s["title"],
                            "reanime_id": s["anime_id"],
                            "anilist_id": s.get("anilist_id", 0),
                            "format": "TV"
                        }
                    ]
                }
                for s in seasons_list
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Catalog entry not found: {str(e)}")

@app.get("/catalog/franchise/{franchise_id}")
async def get_catalog_franchise(franchise_id: str):
    return await get_catalog_anime(franchise_id)

@app.get("/catalog/franchise/{franchise_id}/seasons")
async def get_catalog_franchise_seasons(franchise_id: str):
    cat = await get_catalog_anime(franchise_id)
    return {"franchise": cat.get("franchise"), "seasons": cat.get("seasons", [])}

@app.get("/catalog/season/{season_id}")
async def get_catalog_season_by_id(season_id: int):
    # Lookup in seed or DB
    for key, data in CANONICAL_CATALOG_SEED.items():
        for s in data["seasons"]:
            if s["id"] == season_id:
                return {"season": s}
    raise HTTPException(status_code=404, detail="Season not found")

@app.get("/catalog/season/{season_id}/parts")
async def get_catalog_season_parts(season_id: int):
    s_data = await get_catalog_season_by_id(season_id)
    season = s_data.get("season", {})
    return {"season_id": season_id, "parts": season.get("parts", [])}

@app.get("/seasons/{anime_id}")
async def get_seasons(anime_id: str):
    now = time.time()
    if anime_id in _SEASONS_CACHE:
        cached_val, expiry = _SEASONS_CACHE[anime_id]
        if now < expiry:
            return cached_val

    # Check canonical catalog first
    cat = await get_catalog_record(anime_id)
    if cat:
        seasons_arr = []
        for s in cat["seasons"]:
            main_part = s["parts"][0] if s.get("parts") else {}
            seasons_arr.append({
                "season_number": s["season_number"],
                "anime_id": main_part.get("reanime_id", anime_id),
                "anilist_id": main_part.get("anilist_id", 0),
                "title": s["title"],
                "episode_count": 0,
                "parts": s.get("parts", [])
            })
        result = {
            "anime_id": anime_id,
            "franchise": cat["franchise"]["title"],
            "seasons": seasons_arr
        }
        _SEASONS_CACHE[anime_id] = (result, time.time() + 1800)
        return result

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
async def get_season_episodes(anime_id: str, season_number: int, part: int = 1, part_number: int = 1):
    selected_part = part if part != 1 else part_number
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
        parts = target_season.get("parts", [])
        if parts:
            for p in parts:
                if p.get("part_number") == selected_part:
                    season_anime_id = p.get("reanime_id", season_anime_id)
                    break

        eps_data = await fetch_reanime(f"/api/v1/anime/{season_anime_id}/episodes", {"limit": 2000})
        return {
            "anime_id": anime_id,
            "season_number": season_number,
            "part_number": selected_part,
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


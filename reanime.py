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

@app.get("/seasons/{anime_id}")
async def get_seasons(anime_id: str):
    try:
        meta = await fetch_reanime(f"/api/v1/anime/{anime_id}/meta")
        eps_data = await fetch_reanime(f"/api/v1/anime/{anime_id}/episodes", {"limit": 2000})
        total_eps = eps_data.get("total") or len(eps_data.get("data", []))
        
        # Check recommendations for potential season relations
        recs = []
        try:
            rec_data = await fetch_reanime(f"/api/v1/anime/{anime_id}/recommendations")
            recs = rec_data.get("recommendations", [])
        except Exception:
            pass

        seasons = [
            {
                "season_number": 1,
                "title": meta.get("title", {}).get("english") or "Season 1",
                "episode_count": total_eps
            }
        ]
        
        return {
            "anime_id": anime_id,
            "seasons": seasons
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/seasons/{anime_id}/{season_number}/episodes")
async def get_season_episodes(anime_id: str, season_number: int):
    if season_number != 1:
        raise HTTPException(status_code=404, detail="Season not found")
    try:
        eps_data = await fetch_reanime(f"/api/v1/anime/{anime_id}/episodes", {"limit": 2000})
        return {
            "anime_id": anime_id,
            "season_number": season_number,
            "episodes": eps_data.get("data", [])
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/")
def home():
    return {
        "name": "ReAnime API",
        "description": "Self-hosted anime streaming API with FlixCloud WASM & AES decryption and Seasons support",
        "docs": "/docs",
        "health": "/health"
    }

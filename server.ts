import express from "express";
import cors from "cors";
import path from "path";
import { decryptStream } from "./decrypt.mjs";

const app = express();
const PORT = 3000;
const BASE_URL = "https://reanime.to";

const HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept": "application/json, */*",
};

app.use(cors());
app.use(express.json());

async function fetchReanime(endpoint: string, params: Record<string, any> = {}) {
  const url = new URL(`${BASE_URL}${endpoint}`);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      url.searchParams.append(key, String(value));
    }
  }

  const res = await fetch(url.toString(), { headers: HEADERS });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`ReAnime API error ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.json();
}

// Routes
app.get("/health", (req, res) => {
  res.json({
    status: "ok",
    service: "ReAnime API (Node.js)",
    upstream: BASE_URL,
  });
});

app.get("/search", async (req, res) => {
  try {
    const q = req.query.q as string;
    const limit = req.query.limit ? Number(req.query.limit) : 20;
    const offset = req.query.offset ? Number(req.query.offset) : 0;

    if (!q) {
      return res.status(400).json({ error: "Query parameter 'q' is required" });
    }

    const data = await fetchReanime("/api/v1/search", { q, limit, offset });
    res.json(data);
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/info/:anime_id", async (req, res) => {
  try {
    const { anime_id } = req.params;
    const data = await fetchReanime(`/api/v1/anime/${anime_id}/meta`);
    res.json(data);
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/episodes/:anime_id", async (req, res) => {
  try {
    const { anime_id } = req.params;
    const limit = req.query.limit ? Number(req.query.limit) : 2000;
    const data = await fetchReanime(`/api/v1/anime/${anime_id}/episodes`, { limit });
    res.json(data);
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/recommendations/:anime_id", async (req, res) => {
  try {
    const { anime_id } = req.params;
    const data = await fetchReanime(`/api/v1/anime/${anime_id}/recommendations`);
    res.json(data);
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/schedule", async (req, res) => {
  try {
    const tz = (req.query.tz as string) || "Asia/Calcutta";
    const week = req.query.week ? Number(req.query.week) : 0;
    const data = await fetchReanime("/api/v1/schedule", { tz, week });
    res.json(data);
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/servers/:anime_id/:episode", async (req, res) => {
  try {
    const { anime_id, episode } = req.params;
    let anilist_id = req.query.anilist_id ? Number(req.query.anilist_id) : null;
    const epNum = Number(episode);

    if (epNum < 1) {
      return res.status(400).json({ error: "Episode must be >= 1" });
    }

    if (!anilist_id) {
      const meta = await fetchReanime(`/api/v1/anime/${anime_id}/meta`);
      anilist_id = meta.anilist_id || meta.id;
      if (!anilist_id) {
        return res.status(404).json({ error: "Could not determine AniList ID. Pass ?anilist_id=..." });
      }
    }

    const flixData = await fetchReanime(`/api/flix/${anilist_id}/${epNum}`);
    res.json({
      success: flixData.success || false,
      anime_id,
      anilist_id,
      episode: epNum,
      servers: flixData.servers || [],
    });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/stream/:anime_id/:episode", async (req, res) => {
  try {
    const { anime_id, episode } = req.params;
    const server = (req.query.server as string) || "HD-2";
    const type = (req.query.type as string) || "sub";
    let anilist_id = req.query.anilist_id ? Number(req.query.anilist_id) : null;
    const epNum = Number(episode);

    if (epNum < 1) {
      return res.status(400).json({ error: "Episode must be >= 1" });
    }

    if (!anilist_id) {
      const meta = await fetchReanime(`/api/v1/anime/${anime_id}/meta`);
      anilist_id = meta.anilist_id || meta.id;
      if (!anilist_id) {
        return res.status(404).json({ error: "Could not determine AniList ID. Pass ?anilist_id=..." });
      }
    }

    const flixData = await fetchReanime(`/api/flix/${anilist_id}/${epNum}`);
    const servers = flixData.servers || [];

    const selected = servers.find((s: any) => s.serverName === server && s.dataType === type);
    if (!selected || !selected.dataLink) {
      return res.status(404).json({
        error: "Requested server unavailable",
        server,
        type,
        available: servers,
      });
    }

    const decrypted = await decryptStream(selected.dataLink);
    res.json({
      success: true,
      anime_id,
      anilist_id,
      episode: epNum,
      server,
      type,
      dataType: selected.dataType,
      softsub: selected.softsub || false,
      continue: selected.continue || false,
      ...decrypted,
    });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

app.get("/stream/from-link", async (req, res) => {
  try {
    const link = req.query.link as string;
    if (!link) {
      return res.status(400).json({ error: "Query parameter 'link' is required" });
    }
    const decrypted = await decryptStream(link);
    res.json({ success: true, ...decrypted });
  } catch (err: any) {
    res.status(502).json({ error: err.message });
  }
});

// HTML Documentation Dashboard
app.get("/", (req, res) => {
  res.send(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ReAnime API (Node.js)</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen p-6 font-sans">
  <div class="max-w-4xl mx-auto space-y-8">
    <header class="border-b border-slate-800 pb-6 flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
          <span class="bg-indigo-600 px-3 py-1 rounded-lg text-lg">API</span> ReAnime.to API
        </h1>
        <p class="text-slate-400 mt-1">High-performance anime streaming API with FlixCloud WASM & AES-256 decryption</p>
      </div>
      <span class="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-3 py-1 rounded-full text-sm font-medium">
        ● Online
      </span>
    </header>

    <div class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-4">
      <h2 class="text-xl font-semibold text-white">Available Endpoints</h2>
      <div class="space-y-3 font-mono text-sm">
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/health</span></div>
          <span class="text-slate-400 text-xs font-sans">Service health check</span>
        </div>
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/search?q=naruto</span></div>
          <span class="text-slate-400 text-xs font-sans">Search anime by title</span>
        </div>
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/info/{anime_id}</span></div>
          <span class="text-slate-400 text-xs font-sans">Get anime metadata</span>
        </div>
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/episodes/{anime_id}</span></div>
          <span class="text-slate-400 text-xs font-sans">Get full episode list</span>
        </div>
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/servers/{anime_id}/{episode}</span></div>
          <span class="text-slate-400 text-xs font-sans">Get streaming servers & dataLinks</span>
        </div>
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/stream/{anime_id}/{episode}</span></div>
          <span class="text-slate-400 text-xs font-sans">Fully decrypt HLS (.m3u8) & subtitles</span>
        </div>
        <div class="bg-slate-950 p-3 rounded-lg border border-slate-800 flex items-center justify-between">
          <div><span class="text-emerald-400 font-bold">GET</span> <span class="text-slate-200">/stream/from-link?link=...</span></div>
          <span class="text-slate-400 text-xs font-sans">Decrypt directly from FlixCloud link</span>
        </div>
      </div>
    </div>
  </div>
</body>
</html>`);
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`ReAnime Node.js API server running on http://0.0.0.0:${PORT}`);
});

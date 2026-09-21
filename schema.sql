-- Kinoma Canonical Catalog Database Schema for PostgreSQL / Supabase

-- 1. FRANCHISES TABLE
CREATE TABLE IF NOT EXISTS franchises (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(255) UNIQUE NOT NULL,
    canonical_title VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. SEASONS TABLE
CREATE TABLE IF NOT EXISTS seasons (
    id SERIAL PRIMARY KEY,
    franchise_id INT NOT NULL REFERENCES franchises(id) ON DELETE CASCADE,
    season_number INT NOT NULL,
    canonical_title VARCHAR(255) NOT NULL,
    display_title VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(franchise_id, season_number)
);

-- 3. SEASON PARTS TABLE
CREATE TABLE IF NOT EXISTS season_parts (
    id SERIAL PRIMARY KEY,
    season_id INT NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    part_number INT NOT NULL,
    canonical_title VARCHAR(255) NOT NULL,
    display_title VARCHAR(255) NOT NULL,
    anilist_id INT,
    reanime_id VARCHAR(255) NOT NULL,
    format VARCHAR(50) DEFAULT 'TV',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(season_id, part_number)
);

-- 4. ANIME ENTRIES TABLE
CREATE TABLE IF NOT EXISTS anime_entries (
    id SERIAL PRIMARY KEY,
    franchise_id INT REFERENCES franchises(id) ON DELETE CASCADE,
    season_id INT REFERENCES seasons(id) ON DELETE SET NULL,
    season_part_id INT REFERENCES season_parts(id) ON DELETE SET NULL,
    anilist_id INT,
    reanime_id VARCHAR(255) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    format VARCHAR(50) DEFAULT 'TV',
    is_main_content BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. CATALOG ALIASES TABLE
CREATE TABLE IF NOT EXISTS catalog_aliases (
    id SERIAL PRIMARY KEY,
    anime_entry_id INT REFERENCES anime_entries(id) ON DELETE CASCADE,
    alias VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- SEED DATA: ATTACK ON TITAN
INSERT INTO franchises (slug, canonical_title, description)
VALUES ('attack-on-titan', 'Attack on Titan', 'Humanity fights for survival against giant humanoid Titans.')
ON CONFLICT (slug) DO NOTHING;

-- AOT Seasons
INSERT INTO seasons (franchise_id, season_number, canonical_title, display_title)
SELECT id, 1, 'Season 1', 'Season 1' FROM franchises WHERE slug = 'attack-on-titan'
ON CONFLICT (franchise_id, season_number) DO NOTHING;

INSERT INTO seasons (franchise_id, season_number, canonical_title, display_title)
SELECT id, 2, 'Season 2', 'Season 2' FROM franchises WHERE slug = 'attack-on-titan'
ON CONFLICT (franchise_id, season_number) DO NOTHING;

INSERT INTO seasons (franchise_id, season_number, canonical_title, display_title)
SELECT id, 3, 'Season 3', 'Season 3' FROM franchises WHERE slug = 'attack-on-titan'
ON CONFLICT (franchise_id, season_number) DO NOTHING;

INSERT INTO seasons (franchise_id, season_number, canonical_title, display_title)
SELECT id, 4, 'Season 4', 'Season 4' FROM franchises WHERE slug = 'attack-on-titan'
ON CONFLICT (franchise_id, season_number) DO NOTHING;

-- AOT Season Parts
-- Season 1 Part 1
INSERT INTO season_parts (season_id, part_number, canonical_title, display_title, anilist_id, reanime_id, format)
SELECT s.id, 1, 'Season 1', 'Season 1', 16498, 'attack-on-titan-p9y2p9', 'TV'
FROM seasons s JOIN franchises f ON s.franchise_id = f.id
WHERE f.slug = 'attack-on-titan' AND s.season_number = 1
ON CONFLICT (season_id, part_number) DO NOTHING;

-- Season 2 Part 1
INSERT INTO season_parts (season_id, part_number, canonical_title, display_title, anilist_id, reanime_id, format)
SELECT s.id, 1, 'Season 2', 'Season 2', 20958, 'attack-on-titan-season-2-nn7gs9', 'TV'
FROM seasons s JOIN franchises f ON s.franchise_id = f.id
WHERE f.slug = 'attack-on-titan' AND s.season_number = 2
ON CONFLICT (season_id, part_number) DO NOTHING;

-- Season 3 Part 1
INSERT INTO season_parts (season_id, part_number, canonical_title, display_title, anilist_id, reanime_id, format)
SELECT s.id, 1, 'Season 3', 'Season 3', 99147, 'attack-on-titan-season-3-d5sm7p', 'TV'
FROM seasons s JOIN franchises f ON s.franchise_id = f.id
WHERE f.slug = 'attack-on-titan' AND s.season_number = 3
ON CONFLICT (season_id, part_number) DO NOTHING;

-- Season 4 Part 1
INSERT INTO season_parts (season_id, part_number, canonical_title, display_title, anilist_id, reanime_id, format)
SELECT s.id, 1, 'Part 1', 'Part 1', 110277, 'attack-on-titan-final-season-z8gsmy', 'TV'
FROM seasons s JOIN franchises f ON s.franchise_id = f.id
WHERE f.slug = 'attack-on-titan' AND s.season_number = 4
ON CONFLICT (season_id, part_number) DO NOTHING;

-- Season 4 Part 2
INSERT INTO season_parts (season_id, part_number, canonical_title, display_title, anilist_id, reanime_id, format)
SELECT s.id, 2, 'Part 2', 'Part 2', 131681, 'attack-on-titan-final-season-part-2-s66894', 'TV'
FROM seasons s JOIN franchises f ON s.franchise_id = f.id
WHERE f.slug = 'attack-on-titan' AND s.season_number = 4
ON CONFLICT (season_id, part_number) DO NOTHING;

-- Season 4 Final Chapters (Part 3)
INSERT INTO season_parts (season_id, part_number, canonical_title, display_title, anilist_id, reanime_id, format)
SELECT s.id, 3, 'Final Chapters', 'Final Chapters', 146690, 'attack-on-titan-final-chapters-part-1-or1249', 'SPECIAL'
FROM seasons s JOIN franchises f ON s.franchise_id = f.id
WHERE f.slug = 'attack-on-titan' AND s.season_number = 4
ON CONFLICT (season_id, part_number) DO NOTHING;

-- Anime Entries
INSERT INTO anime_entries (franchise_id, anilist_id, reanime_id, title, format, is_main_content)
SELECT f.id, 16498, 'attack-on-titan-p9y2p9', 'Attack on Titan', 'TV', true
FROM franchises f WHERE f.slug = 'attack-on-titan'
ON CONFLICT (reanime_id) DO NOTHING;

INSERT INTO anime_entries (franchise_id, anilist_id, reanime_id, title, format, is_main_content)
SELECT f.id, 20958, 'attack-on-titan-season-2-nn7gs9', 'Attack on Titan Season 2', 'TV', true
FROM franchises f WHERE f.slug = 'attack-on-titan'
ON CONFLICT (reanime_id) DO NOTHING;

INSERT INTO anime_entries (franchise_id, anilist_id, reanime_id, title, format, is_main_content)
SELECT f.id, 99147, 'attack-on-titan-season-3-d5sm7p', 'Attack on Titan Season 3', 'TV', true
FROM franchises f WHERE f.slug = 'attack-on-titan'
ON CONFLICT (reanime_id) DO NOTHING;

INSERT INTO anime_entries (franchise_id, anilist_id, reanime_id, title, format, is_main_content)
SELECT f.id, 110277, 'attack-on-titan-final-season-z8gsmy', 'Attack on Titan Final Season', 'TV', true
FROM franchises f WHERE f.slug = 'attack-on-titan'
ON CONFLICT (reanime_id) DO NOTHING;

INSERT INTO anime_entries (franchise_id, anilist_id, reanime_id, title, format, is_main_content)
SELECT f.id, 131681, 'attack-on-titan-final-season-part-2-s66894', 'Attack on Titan Final Season Part 2', 'TV', true
FROM franchises f WHERE f.slug = 'attack-on-titan'
ON CONFLICT (reanime_id) DO NOTHING;

INSERT INTO anime_entries (franchise_id, anilist_id, reanime_id, title, format, is_main_content)
SELECT f.id, 146690, 'attack-on-titan-final-chapters-part-1-or1249', 'Attack on Titan Final Chapters', 'SPECIAL', true
FROM franchises f WHERE f.slug = 'attack-on-titan'
ON CONFLICT (reanime_id) DO NOTHING;

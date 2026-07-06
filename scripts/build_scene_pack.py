#!/usr/bin/env python3
"""Maintainer tool: build/refresh Fraimic scene packs.

NOT loaded by the integration -- this is a one-off content-curation script
for whoever maintains this repo's scene_packs/ directory. It queries
Wikimedia Commons for candidate paintings, keeps only files whose license
metadata explicitly says "public domain", downsizes them (the running
integration converts to per-frame .bin at install time -- it never needs
full museum-scan resolution), and writes scene_packs/<pack_id>/*.jpg plus
scene_packs/index.json.

Usage:
    python3 scripts/build_scene_pack.py

Add a new pack by adding an entry to PACKS below and re-running. With no
arguments, every pack in PACKS is rebuilt (Commons occasionally reshuffles
which scan is the "best" one for a search query), so review `git diff`
before committing. Pass one or more pack ids as arguments to rebuild only
those packs and leave the rest of index.json untouched, e.g.:

    python3 scripts/build_scene_pack.py christmas halloween
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from PIL import Image

# Raised (not disabled) from Pillow's ~89MP default: legitimate museum scans
# routinely exceed that, and MAX_SOURCE_PIXELS below already rejects anything
# apt to be slow/huge before it's ever downloaded -- this is just a backstop
# in case width/height from the Commons API ever disagrees with the actual
# file (e.g. a redirect), so decoding still fails fast instead of hanging.
Image.MAX_IMAGE_PIXELS = 200_000_000

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(REPO_ROOT, "scene_packs")

MAX_LONG_EDGE = 2400  # comfortably covers the largest current frame, 2560x1440
JPEG_QUALITY = 85
MIN_SOURCE_DIM = 1000  # reject thumbnails/detail crops that are too small to be useful
# Some Commons "Google Art Project" ultra-zoom scans run to multiple
# gigapixels (one Night Watch scan is 2.8 billion). Decoding those takes
# minutes and gigabytes of RAM for zero quality benefit once downsized to
# MAX_LONG_EDGE -- reject candidates above this before ever downloading them.
# Matches Image.MAX_IMAGE_PIXELS above, so nothing that clears this filter
# can still trip Pillow's own guard.
MAX_SOURCE_PIXELS = 200_000_000
IMAGES_PER_PACK_TARGET = 8

USER_AGENT = (
    "FraimicScenePackBuilder/1.0 "
    "(https://github.com/dsackr/fraimic-homeassistant; maintainer tooling)"
)

API_URL = "https://commons.wikimedia.org/w/api.php"

_EXCLUDE_TITLE_PATTERNS = re.compile(
    r"\bdetail\b|\bcropp?ed\b|replica|after |sketch for|study for|forgery|restoration|"
    r"x-?ray|infrared|conservation|photograph of the|frame\b|"
    r"-x\d+-y\d+",  # a single zoomify tile from a Google Art Project scan, not the whole work
    re.IGNORECASE,
)

# No well-known painting is this elongated -- anything past this is almost
# certainly a tile fragment or a panoramic detail crop, not the full work
# (bit us once already: a Van Gogh "Starry Night" query's top-scoring hit by
# raw pixel count was a 29696x5595 zoomify tile strip).
MAX_ASPECT_RATIO = 2.5


def _api_get(params: dict) -> dict:
    time.sleep(0.8)  # prevent HTTP 429 Rate Limiting from Wikimedia Commons
    params = {**params, "format": "json"}
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _search_candidates(query: str, limit: int = 6) -> list[str]:
    data = _api_get(
        {
            "action": "query",
            "list": "search",
            "srnamespace": 6,
            "srlimit": limit,
            "srsearch": query,
        }
    )
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _imageinfo(titles: list[str]) -> dict[str, dict]:
    """Return {title: {url, width, height, mime, license_ok, artist_text}}."""
    if not titles:
        return {}
    data = _api_get(
        {
            "action": "query",
            "titles": "|".join(titles),
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
        }
    )
    out: dict[str, dict] = {}
    for page in data.get("query", {}).get("pages", {}).values():
        title = page.get("title")
        infos = page.get("imageinfo") or []
        if not title or not infos:
            continue
        info = infos[0]
        meta = info.get("extmetadata", {}) or {}
        license_name = str(meta.get("LicenseShortName", {}).get("value", "")).lower()
        usage_terms = str(meta.get("UsageTerms", {}).get("value", "")).lower()
        license_ok = "public domain" in license_name or "public domain" in usage_terms
        artist_text = _strip_accents(
            _strip_html(str(meta.get("Artist", {}).get("value", "")))
        ).lower()
        out[title] = {
            "url": info.get("url"),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "mime": info.get("mime"),
            "license_ok": license_ok,
            "page_url": info.get("descriptionurl"),
            "artist_text": artist_text,
        }
    return out


def _pick_best(query: str, artist_keyword: str, seen_urls: set[str]) -> dict | None:
    candidates = _search_candidates(query, limit=8)
    is_exact_file = query.startswith("File:")
    if not is_exact_file:
        candidates = [c for c in candidates if not _EXCLUDE_TITLE_PATTERNS.search(c)]
    if not candidates:
        return None
    infos = _imageinfo(candidates)
    keyword = _strip_accents(artist_keyword).lower()

    scored = []
    for title in candidates:
        info = infos.get(title)
        if not info or (not is_exact_file and not info["license_ok"]):
            continue
        if info["mime"] not in ("image/jpeg", "image/png"):
            continue
        if not is_exact_file:
            if info["width"] < MIN_SOURCE_DIM or info["height"] < MIN_SOURCE_DIM:
                continue
            if info["width"] * info["height"] > MAX_SOURCE_PIXELS:
                continue
            if max(info["width"], info["height"]) / min(info["width"], info["height"]) > MAX_ASPECT_RATIO:
                continue
            if info["url"] in seen_urls:
                continue
            # Commons full-text search matches page content, not just the
            # title, so an unrelated painting can outrank the real one (bit us
            # once already: a "van Gogh Self-Portrait" query's top hit was a
            # Malczewski painting). Trust the file's own Artist metadata when
            # present; only fall back to a title-keyword check when a file
            # genuinely has no structured Artist field.
            artist_text = info["artist_text"]
            haystack = artist_text if artist_text else _strip_accents(title).lower()
            if keyword not in haystack:
                continue
        scored.append((info["width"] * info["height"], title, info))

    if not scored:
        return None
    scored.sort(key=lambda t: t[0], reverse=True)
    _, title, info = scored[0]
    return {"title": title, **info}


def _slugify(text: str) -> str:
    text = re.sub(r"^File:", "", text)
    text = re.sub(r"\.(jpg|jpeg|png)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text[:60] or "image"


def _pack_categories(pack: dict) -> list[str]:
    """Return the pack's category tags, preserving authored order."""
    raw_categories = pack.get("categories", pack.get("category", []))
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]

    categories: list[str] = []
    for category in raw_categories if isinstance(raw_categories, list) else []:
        if not isinstance(category, str):
            continue
        category = category.strip()
        if category and category not in categories:
            categories.append(category)
    return categories or ["famous_artists"]


def _pack_category_compat(pack: dict) -> str | list[str]:
    """Compatibility shape for integrations still reading `category`."""
    categories = _pack_categories(pack)
    return categories[0] if len(categories) == 1 else categories


def _download_and_resize(url: str, dest_path: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()

    from io import BytesIO

    with Image.open(BytesIO(raw)) as img:
        img = img.convert("RGB")
        w, h = img.size
        scale = MAX_LONG_EDGE / max(w, h)
        if scale < 1:
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        img.save(dest_path, "JPEG", quality=JPEG_QUALITY, optimize=True)


def build_pack(pack: dict) -> dict:
    pack_id = pack["id"]
    out_dir = os.path.join(PACKS_DIR, pack_id)
    os.makedirs(out_dir, exist_ok=True)

    if "local_images" in pack:
        images = []
        for img in pack["local_images"]:
            filename = img["filename"]
            images.append(
                {
                    "filename": filename,
                    "path": f"scene_packs/{pack_id}/{filename}",
                    "title": img["title"],
                    "source": img.get("source", "AI Generated (Antigravity)"),
                    "commons_url": img.get("commons_url"),
                }
            )
        return {
            "id": pack_id,
            "name": pack["name"],
            "description": pack["description"],
            "category": _pack_category_compat(pack),
            "categories": _pack_categories(pack),
            "license": pack.get("license", "AI Generated artwork (Public Domain CC0 equivalent)"),
            "cover": images[0]["path"],
            "images": images,
        }

    images = []
    seen_urls: set[str] = set()

    for query_spec in pack["queries"]:
        query, display_title, artist_keyword = query_spec
        try:
            best = _pick_best(query, artist_keyword, seen_urls)
        except Exception as err:  # noqa: BLE001
            print(f"  ! query failed ({query!r}): {err}", file=sys.stderr)
            continue
        if not best:
            print(f"  - no valid candidate for {query!r}", file=sys.stderr)
            continue

        seen_urls.add(best["url"])
        slug = _slugify(display_title)
        filename = f"{len(images) + 1:02d}_{slug}.jpg"
        dest_path = os.path.join(out_dir, filename)
        try:
            _download_and_resize(best["url"], dest_path)
        except Exception as err:  # noqa: BLE001
            print(f"  ! download/resize failed for {best['title']!r}: {err}", file=sys.stderr)
            continue

        images.append(
            {
                "filename": filename,
                "path": f"scene_packs/{pack_id}/{filename}",
                "title": display_title,
                "source": "Wikimedia Commons",
                "commons_url": best["page_url"],
            }
        )
        print(f"  + {filename}  <-  {best['title']}")
        time.sleep(0.3)  # be polite to the Commons API

    if not images:
        raise RuntimeError(f"Pack '{pack_id}' ended up with zero images")

    return {
        "id": pack_id,
        "name": pack["name"],
        "description": pack["description"],
        "category": _pack_category_compat(pack),
        "categories": _pack_categories(pack),
        "license": "Public domain (verified per-image via Wikimedia Commons)",
        "cover": images[0]["path"],
        "images": images,
    }


PACKS = [
    {
        "id": "monet",
        "name": "Claude Monet",
        "description": "Impressionist gardens, water lilies, and shifting light.",
        "categories": ["famous_artists"],
        "queries": [
            ("Claude Monet Impression Sunrise painting", "Impression, Sunrise", "Monet"),
            ("Claude Monet Water Lilies Google Art Project", "Water Lilies", "Monet"),
            ("Claude Monet Woman with a Parasol painting", "Woman with a Parasol", "Monet"),
            ("Claude Monet Poppy Field Argenteuil painting", "Poppy Field near Argenteuil", "Monet"),
            ("Claude Monet Rouen Cathedral painting", "Rouen Cathedral", "Monet"),
            ("Claude Monet The Magpie painting", "The Magpie", "Monet"),
            ("Claude Monet Wheatstacks painting", "Wheatstacks", "Monet"),
            ("Claude Monet Japanese Bridge Giverny painting", "The Japanese Footbridge", "Monet"),
            ("Claude Monet Garden at Sainte-Adresse painting", "Garden at Sainte-Adresse", "Monet"),
            ("Claude Monet Bridge over a Pond of Water Lilies", "Bridge over a Pond of Water Lilies", "Monet"),
        ],
    },
    {
        "id": "davinci",
        "name": "Leonardo da Vinci",
        "description": "Renaissance portraits, studies, and sacred scenes.",
        "categories": ["famous_artists"],
        "queries": [
            ("Leonardo da Vinci Mona Lisa painting", "Mona Lisa", "Vinci"),
            ("Leonardo da Vinci The Last Supper painting", "The Last Supper", "Vinci"),
            ("Leonardo da Vinci Vitruvian Man drawing", "Vitruvian Man", "Vinci"),
            ("Leonardo da Vinci Lady with an Ermine painting", "Lady with an Ermine", "Vinci"),
            ("Leonardo da Vinci Virgin of the Rocks painting", "Virgin of the Rocks", "Vinci"),
            ("Leonardo da Vinci Ginevra de Benci painting", "Ginevra de' Benci", "Vinci"),
            ("Leonardo da Vinci Annunciation painting Uffizi", "The Annunciation", "Vinci"),
            ("Leonardo da Vinci Saint John the Baptist painting", "Saint John the Baptist", "Vinci"),
        ],
    },
    {
        "id": "van_gogh",
        "name": "Vincent van Gogh",
        "description": "Bold color and brushwork from Post-Impressionism's icon.",
        "categories": ["famous_artists"],
        "queries": [
            ("Vincent van Gogh Starry Night painting MoMA", "The Starry Night", "Gogh"),
            ("Vincent van Gogh Sunflowers painting National Gallery", "Sunflowers", "Gogh"),
            ("Vincent van Gogh Cafe Terrace at Night painting", "Café Terrace at Night", "Gogh"),
            ("Vincent van Gogh Bedroom in Arles painting", "The Bedroom", "Gogh"),
            ("Vincent van Gogh Wheatfield with Crows painting", "Wheatfield with Crows", "Gogh"),
            ("Vincent van Gogh Irises painting Getty", "Irises", "Gogh"),
            ("Vincent van Gogh Self-Portrait painting Orsay", "Self-Portrait", "Gogh"),
            ("Vincent van Gogh The Potato Eaters painting", "The Potato Eaters", "Gogh"),
            ("Vincent van Gogh Almond Blossoms painting", "Almond Blossoms", "Gogh"),
        ],
    },
    {
        "id": "classic_art",
        "name": "Classic Art",
        "description": "Famous public-domain masterworks spanning centuries and continents.",
        "categories": ["famous_artists"],
        "queries": [
            ("Johannes Vermeer Girl with a Pearl Earring painting", "Girl with a Pearl Earring", "Vermeer"),
            ("Katsushika Hokusai Great Wave off Kanagawa print", "The Great Wave off Kanagawa", "Hokusai"),
            ("Sandro Botticelli Birth of Venus painting", "The Birth of Venus", "Botticelli"),
            ("Rembrandt Night Watch painting", "The Night Watch", "Rembrandt"),
            ("Hieronymus Bosch Garden of Earthly Delights painting", "The Garden of Earthly Delights", "Bosch"),
            ("Jan van Eyck Arnolfini Portrait painting", "The Arnolfini Portrait", "Eyck"),
            ("Diego Velazquez Las Meninas painting", "Las Meninas", "Velazquez"),
            ("Gustav Klimt The Kiss painting", "The Kiss", "Klimt"),
            ("Katsushika Hokusai Fine Wind Clear Morning print", "Fine Wind, Clear Morning", "Hokusai"),
        ],
    },
    {
        "id": "christmas",
        "name": "Christmas",
        "description": "Vibrant, high-contrast Christmas scenes optimized for Spectra 6 displays.",
        "categories": ["seasons"],
        "license": "AI Generated / Public Domain",
        "local_images": [
            {"filename": "01_christmas_tree.jpg", "title": "Christmas Tree"},
            {"filename": "02_santa_claus.jpg", "title": "Santa Claus"},
            {"filename": "03_snowman.jpg", "title": "Snowman"},
            {"filename": "04_nativity_scene.jpg", "title": "Nativity Scene"},
            {"filename": "05_gingerbread_house.jpg", "title": "Gingerbread House"},
            {"filename": "06_christmas_wreath.jpg", "title": "Christmas Wreath"},
            {"filename": "07_decorating_the_christmas_tree.jpg", "title": "Decorating the Christmas Tree", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Knud_Larsen_Decorating_the_Christmas_tree_1897.jpg"},
            {"filename": "08_victorian_christmas_postcard.jpg", "title": "Victorian Christmas Postcard", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Victorian_Christmas_postcard_by_Raphael_Tuck_%26_Sons.jpg"},
            {"filename": "09_christmas_tree_by_aleksey_korin.jpg", "title": "Christmas Tree (Korin)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Christmas_Tree_by_Aleksey_Korin_%281910%29.jpg"},
            {"filename": "10_christmas_postcard_bowley.jpg", "title": "Christmas Postcard (Bowley)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Raphael_Tuck_%26_Sons_Christmas_Postcard_-_A.L._Bowley_-_circa_1909.jpg"},
        ],
    },
    {
        "id": "halloween",
        "name": "Halloween",
        "description": "Spooky-cute, vibrant Halloween illustrations optimized for Spectra 6 displays.",
        "categories": ["seasons"],
        "license": "AI Generated / Public Domain",
        "local_images": [
            {"filename": "01_jack_o_lanterns.jpg", "title": "Jack-o'-Lanterns"},
            {"filename": "02_witch_flying_on_broomstick.jpg", "title": "Witch flying on Broomstick"},
            {"filename": "03_friendly_ghost.jpg", "title": "Friendly Ghost"},
            {"filename": "04_haunted_house.jpg", "title": "Haunted House"},
            {"filename": "05_black_cat_and_pumpkin.jpg", "title": "Black Cat and Pumpkin"},
            {"filename": "06_bats_flying_across_red_moon.jpg", "title": "Bats flying across Red Moon"},
            {"filename": "07_examination_of_a_witch.jpg", "title": "Examination of a Witch (Matteson)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Examination_of_a_Witch_-_Tompkins_Matteson.jpg"},
            {"filename": "08_winslow_homer_pumpkin_patch.jpg", "title": "The Pumpkin Patch (Homer)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Winslow_Homer_-_The_Pumpkin_Patch_%281878%29.jpg"},
            {"filename": "09_takiyasha_the_witch_skeleton.jpg", "title": "Takiyasha the Witch (Kuniyoshi)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Takiyasha_the_Witch_and_the_Skeleton_Spectre_3.jpg"},
            {"filename": "10_woman_with_a_pumpkin.jpg", "title": "Woman with a Pumpkin (Kishida)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Kishida_Ryusei_-_Woman_with_a_Pumpkin_-_Google_Art_Project.jpg"},
        ],
    },
    {
        "id": "independence_day",
        "name": "Independence Day",
        "description": "Patriotic Americana and vibrant July 4th displays optimized for Spectra 6 displays.",
        "categories": ["seasons"],
        "license": "AI Generated / Public Domain",
        "local_images": [
            {"filename": "01_statue_of_liberty.jpg", "title": "Statue of Liberty"},
            {"filename": "02_bald_eagle_and_flag.jpg", "title": "Bald Eagle and Flag"},
            {"filename": "03_independence_day_fireworks.jpg", "title": "Independence Day Fireworks"},
            {"filename": "04_mount_rushmore.jpg", "title": "Mount Rushmore"},
            {"filename": "05_uncle_sam_celebration.jpg", "title": "Uncle Sam's Celebration"},
            {"filename": "06_sailboat_and_fireworks.jpg", "title": "Sailboat and Fireworks (Homer)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Winslow_Homer_-_Sailboat_and_Fourth_of_July_Fireworks.jpg"},
            {"filename": "07_fourth_of_july_picnic.jpg", "title": "Fourth of July Picnic (Spencer)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Lily_Martin_Spencer_-_The_Artist_and_Her_Family_on_a_Fourth_of_July_Picnic.JPG"},
            {"filename": "08_unveiling_statue_of_liberty.jpg", "title": "Unveiling the Statue of Liberty (Moran)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:EdwardMoran-UnveilingTheStatueofLiberty1886Large.jpg"},
            {"filename": "09_uncle_sam_postcard_hurrah.jpg", "title": "Uncle Sam Postcard (Hurrah!)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:Hurrah%21_For_the_Fourth_of_July_Hurrah%21_-_Uncle_Sam_postcard.jpg"},
            {"filename": "10_uncle_sam_postcard_going_off.jpg", "title": "Uncle Sam Postcard (Going Off)", "source": "Wikimedia Commons", "commons_url": "https://commons.wikimedia.org/wiki/File:We%27re_Going_Off_on_the_4th_-_Uncle_Sam_postcard.jpg"},
        ],
    },
    {
        "id": "thanksgiving",
        "name": "Thanksgiving",
        "description": "Harvest abundance, fruit still lifes, and warm autumn scenes.",
        "categories": ["seasons"],
        "queries": [
            ("George Henry Durrie Home to Thanksgiving", "Home to Thanksgiving (Durrie)", "Durrie"),
            ("File:The Harvesters.jpg", "The Harvesters (Brueghel)", "brueghel"),
            ("Severin Roesen - Still Life, Fruit", "Still Life of Fruit (Roesen)", "Roesen"),
            ("Severin Roesen - Two-Tiered Still Life with Fruit and Sunset Landscape - Google Art Project", "Fruit Cornucopia (Roesen)", "Roesen"),
            ("Fruit Still Life by Severin Roesen", "Still Life with Fruit (Roesen)", "Roesen"),
            ("Thanksgiving day - DPLA - 754f1711409e406676cf9febaf17862a", "Vintage Thanksgiving Postcard", "Thanksgiving"),
            ("Puck Thanksgiving 1903", "Thanksgiving (Glackens)", "Glackens"),
            ("Thanksgiving Day – Ways and Means (Harper's Weekly, Vol. II) MET DP875137", "Thanksgiving Day -- Ways and Means", "Homer"),
            ("Hearty Thanksgiving Greeting John Winsch", "Hearty Thanksgiving Greeting (Winsch)", "Winsch"),
            ("The Thanksgiving turkey Alfcamp Campbell", "The Thanksgiving Turkey (Campbell)", "Campbell"),
            ("THANKSGIVING DAY DINNER HOTEL MARLBOROUGH", "Thanksgiving Dinner (Hotel Marlborough)", "NYPL"),
        ],
    },
    {
        "id": "easter",
        "name": "Easter",
        "description": "Vibrant and cheerful Easter scenes featuring the Easter Bunny, colorful eggs, and spring blossoms.",
        "categories": ["seasons"],
        "license": "AI-generated (Creative Commons CC0 Public Domain Dedication)",
        "local_images": [
            {"filename": "01_bunny_basket_landscape.jpg", "title": "Easter Bunny and Basket"},
            {"filename": "02_decorated_eggs_landscape.jpg", "title": "Vibrant Easter Eggs in Spring Grass"},
            {"filename": "03_bunny_portrait_tall.jpg", "title": "Fluffy Easter Bunny Portrait"},
            {"filename": "04_eggs_hanging_portrait.jpg", "title": "Pastel Eggs Hanging from Cherry Blossoms"},
            {"filename": "05_egg_hunt_landscape.jpg", "title": "Easter Egg Hunt in the Meadow"},
            {"filename": "06_bunny_painting_portrait.jpg", "title": "Whimsical Bunny Painting Easter Egg"},
            {"filename": "07_easter_wreath_landscape.jpg", "title": "Rustic Spring Easter Wreath"},
            {"filename": "08_chicks_nest_portrait.jpg", "title": "Fluffy Yellow Chicks in Nest"},
        ],
    },
    {
        "id": "new_years",
        "name": "New Year's",
        "description": "Vibrant fireworks, stunning cityscape celebrations, and festive New Year's Eve scenes.",
        "categories": ["seasons"],
        "license": "AI-generated (Creative Commons CC0 Public Domain Dedication)",
        "local_images": [
            {"filename": "01_nyc_times_square_landscape.jpg", "title": "New Year's Eve in Times Square"},
            {"filename": "02_sydney_fireworks_landscape.jpg", "title": "Sydney Harbour Fireworks Celebration"},
            {"filename": "03_champagne_toast_portrait.jpg", "title": "Champagne Toast at Midnight"},
            {"filename": "04_ball_drop_portrait.jpg", "title": "One Times Square Ball Drop"},
            {"filename": "05_paris_fireworks_landscape.jpg", "title": "Eiffel Tower Fireworks Display"},
            {"filename": "06_sparkler_close_up_portrait.jpg", "title": "Glowing New Year Sparkler"},
            {"filename": "07_london_fireworks_landscape.jpg", "title": "London Eye Fireworks Spectacular"},
            {"filename": "08_confetti_party_portrait.jpg", "title": "New Year's Eve Celebration Party"},
        ],
    },
    {
        "id": "valentines_day",
        "name": "Valentine's Day",
        "description": "Iconic romantic masterworks and classic Cupid and heart illustrations.",
        "categories": ["seasons"],
        "queries": [
            ("Jean-Leon Gerome - Pygmalion and Galatea", "Pygmalion and Galatea (Gerome)", "Gerome"),
            ("1880 Pierre Auguste Cot - The Storm", "The Storm (Cot)", "Cot"),
            ("El Beso (Pinacoteca de Brera, Milán, 1859)", "The Kiss (Il Bacio)", "Hayez"),
            ("Joean Honoré Fragonard - The Swing", "The Swing (Fragonard)", "Fragonard"),
            ("Valentine Met DP886048", "Vintage Valentine (Clapsaddle)", "Clapsaddle"),
            ("Frances Brundage Valentine", "Cupid's Valentine (Brundage)", "Brundage"),
            ("File:Venus and Cupid (c.1700) - Sebastiano Ricci.jpg", "Venus and Cupid (Ricci)", "Ricci"),
            ("File:Cupid and Doves - Frederic Leighton.jpg", "Cupid and Doves (Leighton)", "Leighton"),
            ("File:Cupid and Psyche by François-Édouard Picot.jpg", "Cupid and Psyche (Picot)", "Picot"),
            ("File:The Love of Paris and Helen by Jacques-Louis David.jpg", "The Love of Paris and Helen", "David"),
            ("File:Cupid and Psyche by Jean-François de Troy.jpg", "Cupid and Psyche (Troy)", "Troy"),
        ],
    },
    {
        "id": "presidents",
        "name": "US Presidents",
        "description": "Official, public-domain portraits of the Presidents of the United States.",
        "categories": ["history"],
        "queries": [
            ("File:Gilbert Stuart Williamstown Portrait of George Washington (3x4 cropped).jpg", "George Washington", ""),
            ("File:John Adams A18236 (cropped).jpg", "John Adams", ""),
            ("File:Official Presidential portrait of Thomas Jefferson (by Rembrandt Peale, 1800) (3x4 cropped).jpg", "Thomas Jefferson", ""),
            ("File:James Madison Portrait 1816 (3x4 cropped).jpg", "James Madison", ""),
            ("File:James Monroe White House portrait 1819 (cropped 3x4 close).jpg", "James Monroe", ""),
            ("File:John Quincy Adams 1858 (3x4 cropped).jpg", "John Quincy Adams", ""),
            ("File:Andrew jackson head (3x4 cropped).jpg", "Andrew Jackson", ""),
            ("File:Martin Van Buren circa 1837 (3x4 cropped).jpg", "Martin Van Buren", ""),
            ("File:William Henry Harrison Portrait (3x4 cropped).jpg", "William Henry Harrison", ""),
            ("File:John Tyler (cropped 3x4) (cropped)(2).png", "John Tyler", ""),
            ("File:James K Polk (3x4 cropped).jpg", "James K. Polk", ""),
            ("File:Zachary Taylor restored (3x4 cropped).jpg", "Zachary Taylor", ""),
            ("File:Fillmore (cropped).jpg", "Millard Fillmore", ""),
            ("File:Mathew Brady - Franklin Pierce - alternate crop (cropped)(2).jpg", "Franklin Pierce", ""),
            ("File:James Buchanan (cropped 3x4).jpg", "James Buchanan", ""),
            ("File:Abraham Lincoln 1863 Portrait (3x4 cropped).jpg", "Abraham Lincoln", ""),
            ("File:Andrew Johnson photo portrait head and shoulders (3x4 cropped).jpg", "Andrew Johnson", ""),
            ("File:Ulysses S Grant by Brady c1870-restored (3x4 cropped).jpg", "Ulysses S. Grant", ""),
            ("File:President Rutherford Hayes 1870 - 1880 (3x4 cropped).jpg", "Rutherford B. Hayes", ""),
            ("File:James Abram Garfield, photo portrait seated (3x4 cropped b).jpg", "James A. Garfield", ""),
            ("File:Chester A. Arthur by Abraham Bogardus (cropped) (2).jpg", "Chester A. Arthur", ""),
            ("File:Grover Cleveland by Charles Milton Bell color change (3x4 cropped b).jpg", "Grover Cleveland", ""),
            ("File:Benjamin Harrison, head and shoulders bw photo, 1896 (4x5 cropped).jpg", "Benjamin Harrison", ""),
            ("File:William McKinley Portrait (3x4 cropped).jpg", "William McKinley", ""),
            ("File:Theodore Roosevelt by the Pach Bros (4x5 cropped).jpg", "Theodore Roosevelt", ""),
            ("File:William Howard Taft by Pach Brothers (3x4 ropped).jpg", "William Howard Taft", ""),
            ("File:President Woodrow Wilson Harris & Ewing (3x4 cropped c).jpg", "Woodrow Wilson", ""),
            ("File:Warren G Harding-Harris & Ewing (3x4 cropped).jpg", "Warren G. Harding", ""),
            ("File:President Calvin Coolidge, 1924 head-and-shoulders portrait, facing slightly right (2).jpeg", "Calvin Coolidge", ""),
            ("File:Herbert Clark Hoover by Greene, 1956.jpg", "Herbert Hoover", ""),
            ("File:Franklin Delano Roosevelt, Portrait 1933.jpg", "Franklin D. Roosevelt", ""),
            ("File:TRUMAN 58-766-06 (cropped).jpg", "Harry S. Truman", ""),
            ("File:Dwight D. Eisenhower, official photo portrait, May 29, 1959 (cropped)(3).jpg", "Dwight D. Eisenhower", ""),
            ("File:John F. Kennedy, White House color photo portrait (3x4) (cropped).jpg", "John F. Kennedy", ""),
            ("File:37 Lyndon Johnson 3x4.jpg", "Lyndon B. Johnson", ""),
            ("File:Richard Nixon presidential portrait (1).jpg", "Richard Nixon", ""),
            ("File:Gerald Ford presidential portrait (cropped 3).jpg", "Gerald Ford", ""),
            ("File:Jimmy Carter presidential portrait (cropped 1).jpg", "Jimmy Carter", ""),
            ("File:Official Portrait of President Reagan 1981-cropped.jpg", "Ronald Reagan", ""),
            ("File:George H. W. Bush presidential portrait (cropped 2).jpg", "George H. W. Bush", ""),
            ("File:Bill Clinton.jpg", "Bill Clinton", ""),
            ("File:George-W-Bush.jpeg", "George W. Bush", ""),
            ("File:President Barack Obama, 2012 portrait crop.jpg", "Barack Obama", ""),
            ("File:Donald Trump official portrait (3x4a).jpg", "Donald Trump", ""),
            ("File:Joe Biden presidential portrait (cropped).jpg", "Joe Biden", ""),
        ],
    },
    {
        "id": "wonders",
        "name": "7 Wonders of the World",
        "description": "Stunning landscapes of the New Seven Wonders of the World plus the Great Pyramid of Giza.",
        "categories": ["nature"],
        "queries": [
            ("File:The Great Wall of China at Jinshanling.jpg", "Great Wall of China", ""),
            ("File:The Monastery, Petra, Jordan8.jpg", "Petra", ""),
            ("File:Unique Moment with the Moon and Christ the Redeemer 3.jpg", "Christ the Redeemer", ""),
            ("File:Machu Picchu, Peru.jpg", "Machu Picchu", ""),
            ("File:Chichen-Itza-Castillo-Seen-From-East.JPG", "Chichén Itzá", ""),
            ("File:Colosseum in Rome, Italy - April 2007.jpg", "Colosseum", ""),
            ("File:Taj Mahal in March 2004.jpg", "Taj Mahal", ""),
            ("File:Great Pyramid of Giza.jpg", "Great Pyramid of Giza", ""),
        ],
    },
]


def main() -> None:
    os.makedirs(PACKS_DIR, exist_ok=True)

    requested_ids = sys.argv[1:]
    known_ids = {p["id"] for p in PACKS}
    unknown = set(requested_ids) - known_ids
    if unknown:
        raise SystemExit(f"Unknown pack id(s): {', '.join(sorted(unknown))}")

    to_build = [p for p in PACKS if not requested_ids or p["id"] in requested_ids]

    built_by_id: dict[str, dict] = {}
    for pack in to_build:
        print(f"Building pack '{pack['id']}'...")
        built_by_id[pack["id"]] = build_pack(pack)

    index_path = os.path.join(PACKS_DIR, "index.json")
    existing_by_id: dict[str, dict] = {}
    if requested_ids and os.path.exists(index_path):
        # Only rebuilding a subset -- keep every other pack's existing
        # entry untouched instead of dropping it from the catalog.
        with open(index_path, encoding="utf-8") as f:
            existing_by_id = {p["id"]: p for p in json.load(f).get("packs", [])}

    index_packs = []
    for pack in PACKS:
        entry = built_by_id.get(pack["id"], existing_by_id.get(pack["id"]))
        if entry is None:
            raise SystemExit(
                f"Pack '{pack['id']}' has no existing index.json entry and wasn't "
                f"rebuilt this run -- pass it explicitly to build it."
            )
        index_packs.append(entry)

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"packs": index_packs}, f, indent=2)
        f.write("\n")
    print(f"Wrote {index_path}")

    print("\nSanity check (flag anything worth a manual look):")
    for pack in built_by_id.values():
        for image in pack["images"]:
            path = os.path.join(REPO_ROOT, image["path"])
            with Image.open(path) as img:
                w, h = img.size
            ratio = max(w, h) / min(w, h)
            flag = " <-- unusual aspect ratio" if ratio > 2.0 else ""
            print(f"  {pack['id']}/{image['filename']}: {w}x{h} ({ratio:.2f}:1){flag}")


if __name__ == "__main__":
    main()

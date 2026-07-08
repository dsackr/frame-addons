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
RETIRED_PACK_IDS = {"tv_shows"}


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
    """Return image metadata keyed by Commons file title."""
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
        license_name = _strip_html(str(meta.get("LicenseShortName", {}).get("value", ""))).strip()
        usage_terms = _strip_html(str(meta.get("UsageTerms", {}).get("value", ""))).strip()
        license_haystack = f"{license_name} {usage_terms}".lower()
        license_ok = any(
            term in license_haystack
            for term in (
                "public domain",
                "cc0",
                "creative commons zero",
                "cc by",
                "cc-by",
                "creative commons attribution",
            )
        )
        artist_display = _strip_html(str(meta.get("Artist", {}).get("value", ""))).strip()
        artist_text = _strip_accents(
            artist_display
        ).lower()
        out[title] = {
            "url": info.get("url"),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "mime": info.get("mime"),
            "license_ok": license_ok,
            "license_short_name": license_name,
            "page_url": info.get("descriptionurl"),
            "artist_display": artist_display,
            "artist_text": artist_text,
        }
    return out


def _pick_best(query: str, artist_keyword: str, seen_urls: set[str]) -> dict | None:
    is_exact_file = query.startswith("File:")
    candidates = [query] if is_exact_file else _search_candidates(query, limit=8)
    if not is_exact_file:
        candidates = [c for c in candidates if not _EXCLUDE_TITLE_PATTERNS.search(c)]
    if not candidates:
        return None
    infos = _imageinfo(candidates)
    keyword = _strip_accents(artist_keyword).lower()

    scored = []
    for title in candidates:
        info = infos.get(title)
        if not info or not info["license_ok"]:
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
            image_entry = {
                "filename": filename,
                "path": f"scene_packs/{pack_id}/{filename}",
                "title": img["title"],
                "source": img.get("source", "AI Generated (Antigravity)"),
                "commons_url": img.get("commons_url", img.get("source_url")),
            }
            for optional_key in (
                "source_url",
                "license",
                "attribution",
                "rights_notes",
                "image_type",
                "cast",
            ):
                if optional_key in img:
                    image_entry[optional_key] = img[optional_key]
            images.append(image_entry)
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

    for existing_filename in os.listdir(out_dir):
        if existing_filename.lower().endswith((".jpg", ".jpeg")):
            os.remove(os.path.join(out_dir, existing_filename))

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

        image_entry = {
            "filename": filename,
            "path": f"scene_packs/{pack_id}/{filename}",
            "title": display_title,
            "source": "Wikimedia Commons",
            "commons_url": best["page_url"],
        }
        if best.get("license_short_name"):
            image_entry["license"] = best["license_short_name"]
        if best.get("artist_display"):
            image_entry["attribution"] = best["artist_display"]
        images.append(image_entry)
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
        "license": pack.get("license", "Public domain (verified per-image via Wikimedia Commons)"),
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
        "id": "michelangelo",
        "name": "Michelangelo",
        "description": "High-contrast sculpture photography of Michelangelo's marble masterworks.",
        "categories": ["famous_artists"],
        "license": "Public domain artworks with Wikimedia Commons public-domain/Creative Commons photography; see per-image links",
        "queries": [
            ("File:'David' by Michelangelo Fir JBU004.jpg", "David", ""),
            ("File:Michelangelo's David - right view 2.jpg", "David (Right View)", ""),
            ("File:Michelangelo's Pieta 5450 cropncleaned edit.jpg", "Pietà", ""),
            ("File:Michelangelo's Moses (Rome).jpg", "Moses", ""),
            ("File:Michelangelo Bacchus.jpg", "Bacchus", ""),
            ("File:'Dying Slave' Michelangelo JBU001.jpg", "Dying Slave", ""),
            ("File:'Rebellious Slave' Michelangelo JBU81.jpg", "Rebellious Slave", ""),
        ],
    },
    {
        "id": "picasso",
        "name": "Pablo Picasso",
        "description": "Commons-reusable early Picasso works, ceramics, and archival imagery.",
        "categories": ["famous_artists"],
        "license": "Public domain and Creative Commons media from Wikimedia Commons; see per-image links",
        "queries": [
            ("File:The Blue Room, by Pablo Picasso.jpg", "The Blue Room", ""),
            ("File:Boy Holding a Blue Vase, by Pablo Picasso, 1905, oil on canvas - Hyde Collection - Glens Falls, NY - 20180224 123602.jpg", "Boy Holding a Blue Vase", ""),
            ("File:The Soviet Union 1971 CPA 4024 stamp (Child on Ball (Pablo Picasso)).jpg", "Child on a Ball (Stamp)", ""),
            ("File:Pablo Picasso's ceramic3.jpg", "Picasso Ceramic", ""),
            ("File:Pablo Picasso dando instrucciones a una modelo en su taller de pintura.jpg", "Picasso in the Studio", ""),
        ],
    },
    {
        "id": "donatello",
        "name": "Donatello",
        "description": "Open-licensed sculpture photography from the Early Renaissance master.",
        "categories": ["famous_artists"],
        "license": "Public domain artworks with Wikimedia Commons Creative Commons photography; see per-image links",
        "queries": [
            ("File:Marble David by Donatello-Bargello.jpg", "David (Marble)", ""),
            ("File:Bargello Donatello David 03.JPG", "David (Bronze)", ""),
            ("File:Donatello, maria maddalena 02.JPG", "Penitent Magdalene", ""),
            ("File:St. Georg, Donatello, 1416-17, Bargello Florenz-01.jpg", "Saint George", ""),
            ("File:Statue of Gattamelata by Donatello - Padua 2016 (2).jpg", "Equestrian Statue of Gattamelata", ""),
            ("File:Giuditta di donatello 04.JPG", "Judith and Holofernes", ""),
            ("File:Baptismal font of the Siena Baptistry la-test battista presenta.jpg", "The Feast of Herod", ""),
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
        "id": "rembrandt",
        "name": "Rembrandt",
        "description": "Baroque portraits, dramatic histories, and luminous Dutch masterworks.",
        "categories": ["famous_artists"],
        "queries": [
            ("Rembrandt The Night Watch painting", "The Night Watch", "Rembrandt"),
            ("Rembrandt The Anatomy Lesson of Dr Nicolaes Tulp painting", "The Anatomy Lesson of Dr. Nicolaes Tulp", "Rembrandt"),
            ("Rembrandt Self-Portrait with Beret and Turned-Up Collar painting", "Self-Portrait", "Rembrandt"),
            ("Rembrandt The Jewish Bride painting", "The Jewish Bride", "Rembrandt"),
            ("Rembrandt The Return of the Prodigal Son painting", "The Return of the Prodigal Son", "Rembrandt"),
            ("Rembrandt Syndics of the Drapers Guild painting", "The Syndics of the Drapers' Guild", "Rembrandt"),
            ("Rembrandt Bathsheba at Her Bath painting", "Bathsheba at Her Bath", "Rembrandt"),
            ("Rembrandt The Storm on the Sea of Galilee painting", "The Storm on the Sea of Galilee", "Rembrandt"),
        ],
    },
    {
        "id": "hokusai",
        "name": "Katsushika Hokusai",
        "description": "Bold ukiyo-e prints, Mount Fuji views, waterfalls, and crisp linework.",
        "categories": ["famous_artists"],
        "queries": [
            ("Katsushika Hokusai The Great Wave off Kanagawa print", "The Great Wave off Kanagawa", "Hokusai"),
            ("Katsushika Hokusai Fine Wind Clear Morning print", "Fine Wind, Clear Morning", "Hokusai"),
            ("Katsushika Hokusai Ejiri in Suruga Province print", "Ejiri in Suruga Province", "Hokusai"),
            ("Katsushika Hokusai Kajikazawa in Kai Province print", "Kajikazawa in Kai Province", "Hokusai"),
            ("Katsushika Hokusai Amida Falls on the Kiso Road print", "Amida Falls on the Kiso Road", "Hokusai"),
            ("Katsushika Hokusai The Waterfall Where Yoshitsune Washed his Horse at Yoshino print", "Yoshitsune's Horse-Washing Falls", "Hokusai"),
        ],
    },
    {
        "id": "mucha",
        "name": "Alphonse Mucha",
        "description": "Art Nouveau posters and decorative panels with elegant linework and color.",
        "categories": ["famous_artists"],
        "queries": [
            ("Alphonse Mucha Gismonda poster", "Gismonda", "Mucha"),
            ("Alphonse Mucha Zodiac poster", "Zodiac", "Mucha"),
            ("Alphonse Mucha JOB cigarette poster", "JOB Cigarettes", "Mucha"),
            ("Alphonse Mucha Moet Chandon poster", "Moët & Chandon", "Mucha"),
            ("Alphonse Mucha The Seasons Spring", "The Seasons: Spring", "Mucha"),
            ("Alphonse Mucha The Seasons Summer", "The Seasons: Summer", "Mucha"),
            ("Alphonse Mucha Princess Hyacinth poster", "Princess Hyacinth", "Mucha"),
            ("Alphonse Mucha La Dame aux Camelias poster", "La Dame aux Camélias", "Mucha"),
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
        "categories": ["seasons", "AI Art"],
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
        "categories": ["seasons", "AI Art"],
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
        "categories": ["seasons", "AI Art"],
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
        "categories": ["seasons", "AI Art"],
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
        "categories": ["seasons", "AI Art"],
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
            ("File:Bill Clinton (cropped 4).jpg", "Bill Clinton", ""),
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
    {
        "id": "nasa_space",
        "name": "NASA Space",
        "description": "Openly licensed views of Earth, spaceflight, planets, and deep space.",
        "categories": ["nature", "history"],
        "license": "Public domain and Creative Commons media from Wikimedia Commons; see per-image links",
        "queries": [
            ("NASA Earthrise Apollo 8", "Earthrise", ""),
            ("NASA Blue Marble 1972", "The Blue Marble", ""),
            ("NASA Buzz Aldrin Moon Apollo 11", "Buzz Aldrin on the Moon", ""),
            ("NASA Apollo 11 Lunar Module Eagle", "Lunar Module Eagle", ""),
            ("NASA Pillars of Creation Hubble", "Pillars of Creation", ""),
            ("NASA Hubble Ultra Deep Field", "Hubble Ultra Deep Field", ""),
            ("NASA Carina Nebula Webb", "Carina Nebula", ""),
            ("NASA Jupiter Great Red Spot Juno", "Jupiter and the Great Red Spot", ""),
        ],
    },
    {
        "id": "wpa_national_parks",
        "name": "WPA National Parks",
        "description": "Vintage National Park Service poster art from New Deal-era public works.",
        "categories": ["nature", "history"],
        "license": "Public domain and Creative Commons media from Wikimedia Commons; see per-image links",
        "queries": [
            ("File:Grand Canyon National Park, a free government service LCCN2007676131.jpg", "Grand Canyon National Park", ""),
            ("File:Lassen Volcanic National Park, Ranger Naturalist Service LCCN2007676132.jpg", "Lassen Volcanic National Park", ""),
            ("File:Yellowstone National Park, Ranger Naturalist Service LCCN2007676133.jpg", "Yellowstone National Park", ""),
            ("File:Zion National Park, Ranger Naturalist Service LCCN2007676134.jpg", "Zion National Park", ""),
            ("File:The national parks preserve wild life LCCN98518597.jpg", "National Parks Preserve Wildlife", ""),
            ("File:Pueblos of the Southwest poster, ca. 1935.jpg", "Pueblos of the Southwest", ""),
        ],
    },
    {
        "id": "skylines",
        "name": "City Skylines",
        "description": "Famous city skylines from New York, Shanghai, Tokyo, London, Dubai, Sydney, and Frankfurt.",
        "categories": ["architecture"],
        "license": "Public domain and Creative Commons media from Wikimedia Commons; see per-image links",
        "queries": [
            ("File:Lower Manhattan from Jersey City September 2020 panorama.jpg", "New York City", ""),
            ("File:Pudong Shanghai November 2017 panorama.jpg", "Shanghai", ""),
            ("File:Tokyo - Sunset Skyline.jpg", "Tokyo", ""),
            ("File:City of London skyline from London City Hall - Sept 2015 - Crop Aligned.jpg", "London", ""),
            ("File:Dubai Skyline with Ra's Al Khor Wildlife Sanctuary.jpg", "Dubai", ""),
            ("File:Sydney skyline at night 2020.jpg", "Sydney", ""),
            ("File:Skyline Frankfurt am Main 2015.jpg", "Frankfurt", ""),
        ],
    },
    {
        "id": "castles_cathedrals",
        "name": "Castles & Cathedrals",
        "description": "Dramatic castles, cathedrals, abbeys, and historic sacred architecture.",
        "categories": ["architecture", "history"],
        "license": "Public domain and Creative Commons media from Wikimedia Commons; see per-image links",
        "queries": [
            ("File:Neuschwanstein Castle 2024-02.jpg", "Neuschwanstein Castle", ""),
            ("File:Mont-Saint-Michel vu du ciel.jpg", "Mont Saint-Michel", ""),
            ("File:Kölner Dom - Westfassade 2022 ohne Gerüst-0968 b.jpg", "Cologne Cathedral", ""),
            ("File:Paris Notre-Dame Southeast View 01.JPG", "Notre-Dame de Paris", ""),
            ("File:Segovia - Alcázar de Segovia 22 2017-10-24.jpg", "Alcázar of Segovia", ""),
            ("File:Half-Moon battery Edinburgh Castle dec.23.jpg", "Edinburgh Castle", ""),
            ("File:Chartres JBU01.JPG", "Chartres Cathedral", ""),
            ("File:Bran Castle cloudy.jpg", "Bran Castle", ""),
        ],
    },
    {
        "id": "cheers",
        "name": "Cheers",
        "description": "A personal-use Cheers TV show pack with cast metadata, a promotional cast image, and individual cast headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional images and Wikimedia Commons public-domain/CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "Cheers",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:Cheers_original_cast_1982-86_(1983).jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "Ted Danson",
                    "Shelley Long",
                    "Rhea Perlman",
                    "Nicholas Colasanto",
                    "George Wendt",
                    "John Ratzenberger",
                    "Kelsey Grammer",
                    "Woody Harrelson",
                    "Bebe Neuwirth",
                    "Kirstie Alley",
                ],
            },
            {
                "filename": "02_ted_danson.jpg",
                "title": "Ted Danson (Sam Malone)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:%27The_Good_Place%27_cast_and_crew_visit_San_Diego_Comic_Con_for_a_panel_(43100198314)_(cropped_2).jpg",
                "license": "CC BY 2.0",
                "attribution": "aitchisons from United States",
                "image_type": "Actor headshot",
                "cast": ["Ted Danson"],
            },
            {
                "filename": "03_shelley_long.jpg",
                "title": "Shelley Long (Diane Chambers)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Shelley_Long_in_Cheers_(1982_NBC_publicity_photo).jpg",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["Shelley Long"],
            },
            {
                "filename": "04_rhea_perlman.jpg",
                "title": "Rhea Perlman (Carla Tortelli)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Rhea_Perlman_(1988)_-_cropped.jpg",
                "license": "CC BY 2.0",
                "attribution": "Alan Light",
                "image_type": "Actor headshot",
                "cast": ["Rhea Perlman"],
            },
            {
                "filename": "05_nicholas_colasanto.jpg",
                "title": "Nicholas Colasanto (Coach Ernie Pantusso)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Nicholas_Colasanto_(1982_NBC_publicity_photo).jpg",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["Nicholas Colasanto"],
            },
            {
                "filename": "06_george_wendt.jpg",
                "title": "George Wendt (Norm Peterson)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:George_Wendt_1989.jpg",
                "license": "CC BY 2.0",
                "attribution": "Alan Light",
                "image_type": "Actor headshot",
                "cast": ["George Wendt"],
            },
            {
                "filename": "07_john_ratzenberger.jpg",
                "title": "John Ratzenberger (Cliff Clavin)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:John_Ratzenberger_2011_Shankbone.JPG",
                "license": "CC BY 3.0",
                "attribution": "David Shankbone",
                "image_type": "Actor headshot",
                "cast": ["John Ratzenberger"],
            },
            {
                "filename": "08_kelsey_grammer.jpg",
                "title": "Kelsey Grammer (Frasier Crane)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Kelsey_Grammer_2016.jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Greg2600",
                "image_type": "Actor headshot",
                "cast": ["Kelsey Grammer"],
            },
            {
                "filename": "09_woody_harrelson.jpg",
                "title": "Woody Harrelson (Woody Boyd)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Rampart_Premiere_Harrelson_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Ross from hamilton on, Canada",
                "image_type": "Actor headshot",
                "cast": ["Woody Harrelson"],
            },
            {
                "filename": "10_bebe_neuwirth.jpg",
                "title": "Bebe Neuwirth (Lilith Sternin)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Bebe_Neuwirth.jpg",
                "license": "CC BY 2.0",
                "attribution": "Alan Light",
                "image_type": "Actor headshot",
                "cast": ["Bebe Neuwirth"],
            },
            {
                "filename": "11_kirstie_alley.jpg",
                "title": "Kirstie Alley (Rebecca Howe)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:KirstieAlley1994.jpg",
                "license": "CC BY 2.0",
                "attribution": "Alan Light",
                "image_type": "Actor headshot",
                "cast": ["Kirstie Alley"],
            },
        ],
    },
    {
        "id": "friends",
        "name": "Friends",
        "description": "A personal-use Friends TV show pack with cast metadata, a promotional cast image, and individual cast headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and unverified web images; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "Friends",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:Friends_season_one_cast.jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "Jennifer Aniston",
                    "Courteney Cox",
                    "Lisa Kudrow",
                    "Matt LeBlanc",
                    "Matthew Perry",
                    "David Schwimmer",
                ],
            },
            {
                "filename": "rachel.jpg",
                "title": "Jennifer Aniston (Rachel Green)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Jennifer Aniston"],
            },
            {
                "filename": "monica.png",
                "title": "Courteney Cox (Monica Geller)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Courteney Cox"],
            },
            {
                "filename": "phoebe.png",
                "title": "Lisa Kudrow (Phoebe Buffay)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Lisa Kudrow"],
            },
            {
                "filename": "joey.png",
                "title": "Matt LeBlanc (Joey Tribbiani)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Matt LeBlanc"],
            },
            {
                "filename": "chandler.png",
                "title": "Matthew Perry (Chandler Bing)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Matthew Perry"],
            },
            {
                "filename": "ross.jpg",
                "title": "David Schwimmer (Ross Geller)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["David Schwimmer"],
            },
        ],
    },
    {
        "id": "the_big_bang_theory",
        "name": "The Big Bang Theory",
        "description": "A personal-use The Big Bang Theory TV show pack with cast metadata, a promotional image, and individual cast headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and unverified web images; see per-image notes.",
        "local_images": [
            {
                "filename": "01_poster.jpg",
                "title": "The Big Bang Theory",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:The_Big_Bang_Theory_Poster.jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional image kept for personal Home Assistant display use.",
                "image_type": "Promotional poster image",
                "cast": [
                    "Johnny Galecki",
                    "Jim Parsons",
                    "Kaley Cuoco",
                    "Simon Helberg",
                    "Kunal Nayyar",
                    "Mayim Bialik",
                    "Melissa Rauch",
                    "Kevin Sussman",
                ],
            },
            {
                "filename": "leonard.jpg",
                "title": "Johnny Galecki (Leonard Hofstadter)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Johnny Galecki"],
            },
            {
                "filename": "sheldon.jpg",
                "title": "Jim Parsons (Sheldon Cooper)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Jim Parsons"],
            },
            {
                "filename": "penny.webp",
                "title": "Kaley Cuoco (Penny)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Kaley Cuoco"],
            },
            {
                "filename": "howard.jpg",
                "title": "Simon Helberg (Howard Wolowitz)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Simon Helberg"],
            },
            {
                "filename": "raj.jpg",
                "title": "Kunal Nayyar (Raj Koothrappali)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Kunal Nayyar"],
            },
            {
                "filename": "amy.jpg",
                "title": "Mayim Bialik (Amy Farrah Fowler)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Mayim Bialik"],
            },
            {
                "filename": "bernadette.jpg",
                "title": "Melissa Rauch (Bernadette Rostenkowski)",
                "source": "Unverified web image",
                "license": "Unknown / unverified",
                "rights_notes": "Source and license could not be verified; kept for personal-use display only. Replace with a Wikimedia Commons-sourced, license-verified photo before any public/commercial redistribution.",
                "image_type": "Actor headshot (unverified source)",
                "cast": ["Melissa Rauch"],
            },
        ],
    },
    {
        "id": "how_i_met_your_mother",
        "name": "How I Met Your Mother",
        "description": "A personal-use How I Met Your Mother TV show pack with cast metadata, a promotional cast image, and individual cast headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and Wikimedia Commons CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "How I Met Your Mother",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:How_I_Met_Your_Mother_(cast).jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "Josh Radnor",
                    "Jason Segel",
                    "Cobie Smulders",
                    "Neil Patrick Harris",
                    "Alyson Hannigan",
                    "Cristin Milioti",
                ],
            },
            {
                "filename": "02_josh_radnor.jpg",
                "title": "Josh Radnor (Ted Mosby)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Josh_Radnor_(9448570254).jpg",
                "license": "CC BY 2.0",
                "attribution": "vagueonthehow from Tadcaster, York, England",
                "image_type": "Actor headshot",
                "cast": ["Josh Radnor"],
            },
            {
                "filename": "03_jason_segel.jpg",
                "title": "Jason Segel (Marshall Eriksen)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Jason_Segel_2011.jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Eva Rinaldi",
                "image_type": "Actor headshot",
                "cast": ["Jason Segel"],
            },
            {
                "filename": "04_alyson_hannigan.jpg",
                "title": "Alyson Hannigan (Lily Aldrin)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Alyson_Hannigan_(9445491655)_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "vagueonthehow from Tadcaster, York, England",
                "image_type": "Actor headshot",
                "cast": ["Alyson Hannigan"],
            },
            {
                "filename": "05_cobie_smulders.jpg",
                "title": "Cobie Smulders (Robin Scherbatsky)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Cobie_Smulders_(9448214924)_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "vagueonthehow",
                "image_type": "Actor headshot",
                "cast": ["Cobie Smulders"],
            },
            {
                "filename": "06_neil_patrick_harris.jpg",
                "title": "Neil Patrick Harris (Barney Stinson)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Neil_Patrick_Harris_(9448294366)_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "vagueonthehow from Tadcaster, York, England",
                "image_type": "Actor headshot",
                "cast": ["Neil Patrick Harris"],
            },
            {
                "filename": "07_cristin_milioti.jpg",
                "title": "Cristin Milioti (Tracy McConnell / \"The Mother\")",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Cristin_Milioti_July_13,_2014_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Mingle Media TV",
                "image_type": "Actor headshot",
                "cast": ["Cristin Milioti"],
            },
        ],
    },
    {
        "id": "doctor_who",
        "name": "Doctor Who",
        "description": "A personal-use Doctor Who TV show pack with cast metadata, a title-card image, and individual headshots of each actor who has played the Doctor.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free title-card image and Wikimedia Commons public-domain/CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_title_card.jpg",
                "title": "Doctor Who",
                "source": "Wikipedia non-free title-card image",
                "source_url": "https://en.wikipedia.org/wiki/File:Doctor_Who_title_card.png",
                "license": "Fair use / non-free title-card image",
                "rights_notes": "Low-resolution title-card image kept for personal Home Assistant display use.",
                "image_type": "Title-card image",
                "cast": [
                    "William Hartnell",
                    "Patrick Troughton",
                    "Jon Pertwee",
                    "Tom Baker",
                    "Peter Davison",
                    "Colin Baker",
                    "Sylvester McCoy",
                    "Paul McGann",
                    "Christopher Eccleston",
                    "David Tennant",
                    "Matt Smith",
                    "Peter Capaldi",
                    "Jodie Whittaker",
                    "Ncuti Gatwa",
                ],
            },
            {
                "filename": "02_william_hartnell.jpg",
                "title": "William Hartnell (First Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:William_Hartnell,_1946.jpg",
                "license": "Public domain",
                "attribution": "Unknown photographer",
                "image_type": "Actor headshot",
                "cast": ["William Hartnell"],
            },
            {
                "filename": "03_patrick_troughton.jpg",
                "title": "Patrick Troughton (Second Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Patrick_Troughton_in_1984,_2.jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Mark Garland",
                "image_type": "Actor headshot",
                "cast": ["Patrick Troughton"],
            },
            {
                "filename": "04_jon_pertwee.jpg",
                "title": "Jon Pertwee (Third Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Dr_Who,_John_Pertwee_(10842597324)_(cropped3).jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Archives New Zealand from New Zealand",
                "image_type": "Actor headshot",
                "cast": ["Jon Pertwee"],
            },
            {
                "filename": "05_tom_baker.jpg",
                "title": "Tom Baker (Fourth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Tom_Baker.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Legend Photography",
                "image_type": "Actor headshot",
                "cast": ["Tom Baker"],
            },
            {
                "filename": "06_peter_davison.jpg",
                "title": "Peter Davison (Fifth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Peter_Davison_(24257077900)_(cropped).jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "steve cranston",
                "image_type": "Actor headshot",
                "cast": ["Peter Davison"],
            },
            {
                "filename": "07_colin_baker.jpg",
                "title": "Colin Baker (Sixth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Colin_Baker_(cropped).jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Gage Skidmore from Peoria, AZ, United States of America",
                "image_type": "Actor headshot",
                "cast": ["Colin Baker"],
            },
            {
                "filename": "08_sylvester_mccoy.jpg",
                "title": "Sylvester McCoy (Seventh Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Sylvester_McCoy_in_2018.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Simon King",
                "image_type": "Actor headshot",
                "cast": ["Sylvester McCoy"],
            },
            {
                "filename": "09_paul_mcgann.jpg",
                "title": "Paul McGann (Eighth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Paul_McGann.JPG",
                "license": "CC BY-SA 3.0",
                "attribution": "Tim Drury from Cambridge, Cambridgeshire",
                "image_type": "Actor headshot",
                "cast": ["Paul McGann"],
            },
            {
                "filename": "10_christopher_eccleston.jpg",
                "title": "Christopher Eccleston (Ninth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Christopher_Eccleston_by_Gage_Skidmore.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Christopher Eccleston"],
            },
            {
                "filename": "11_david_tennant.jpg",
                "title": "David Tennant (Tenth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:David_Tennant_-_Los_Angeles_Comic_Con_2025.jpg",
                "license": "CC BY 4.0",
                "attribution": "Kevin Paul",
                "image_type": "Actor headshot",
                "cast": ["David Tennant"],
            },
            {
                "filename": "12_matt_smith.jpg",
                "title": "Matt Smith (Eleventh Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Matt_Smith_at_Los_Angeles_Comic_Con_2023-02.jpg",
                "license": "CC BY 4.0",
                "attribution": "Kevin Paul",
                "image_type": "Actor headshot",
                "cast": ["Matt Smith"],
            },
            {
                "filename": "13_peter_capaldi.jpg",
                "title": "Peter Capaldi (Twelfth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Peter_Capaldi_by_Gage_Skidmore.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Peter Capaldi"],
            },
            {
                "filename": "14_jodie_whittaker.jpg",
                "title": "Jodie Whittaker (Thirteenth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Jodie_Whittaker_(52549229052)_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Super Festivals from Ft. Lauderdale, USA",
                "image_type": "Actor headshot",
                "cast": ["Jodie Whittaker"],
            },
            {
                "filename": "15_ncuti_gatwa.jpg",
                "title": "Ncuti Gatwa (Fifteenth Doctor)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Ncuti_Gatwa-65778.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Harald Krichel",
                "image_type": "Actor headshot",
                "cast": ["Ncuti Gatwa"],
            },
        ],
    },
    {
        "id": "star_wars",
        "name": "Star Wars",
        "description": "A personal-use Star Wars pack with cast metadata, a poster image, and individual actor headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free film poster image and Wikimedia Commons public-domain/CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_poster.jpg",
                "title": "Star Wars",
                "source": "Wikipedia non-free film poster image",
                "source_url": "https://en.wikipedia.org/wiki/File:StarWarsMoviePoster1977.jpg",
                "license": "Fair use / non-free film poster image",
                "rights_notes": "Low-resolution poster image kept for personal Home Assistant display use.",
                "image_type": "Poster image",
                "cast": [
                    "Mark Hamill",
                    "Harrison Ford",
                    "Carrie Fisher",
                    "Alec Guinness",
                    "Anthony Daniels",
                    "Kenny Baker",
                    "Peter Mayhew",
                    "David Prowse",
                    "James Earl Jones",
                ],
            },
            {
                "filename": "02_mark_hamill.jpg",
                "title": "Mark Hamill (Luke Skywalker)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Mark_Hamill_by_Gage_Skidmore_4.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Mark Hamill"],
            },
            {
                "filename": "03_harrison_ford.jpg",
                "title": "Harrison Ford (Han Solo)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Harrison_Ford_by_Gage_Skidmore_4.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Harrison Ford"],
            },
            {
                "filename": "04_carrie_fisher.jpg",
                "title": "Carrie Fisher (Princess Leia)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Carrie_Fisher_2013-a_straightened.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Riccardo Ghilardi",
                "image_type": "Actor headshot",
                "cast": ["Carrie Fisher"],
            },
            {
                "filename": "05_alec_guinness.jpg",
                "title": "Alec Guinness (Obi-Wan Kenobi)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Sir_Alec_Guinness_Allan_Warren.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Allan Warren",
                "image_type": "Actor headshot",
                "cast": ["Alec Guinness"],
            },
            {
                "filename": "06_anthony_daniels.jpg",
                "title": "Anthony Daniels (C-3PO)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Anthony_Daniels_2011.jpg",
                "license": "CC BY 2.0",
                "attribution": "Major Nelson",
                "image_type": "Actor headshot",
                "cast": ["Anthony Daniels"],
            },
            {
                "filename": "08_peter_mayhew.jpg",
                "title": "Peter Mayhew (Chewbacca)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Peter_Mayhew_2015.jpg",
                "license": "CC BY 2.0",
                "attribution": "Florida Supercon",
                "image_type": "Actor headshot",
                "cast": ["Peter Mayhew"],
            },
            {
                "filename": "09_david_prowse.jpg",
                "title": "David Prowse (Darth Vader, physical performer)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:David_Prowse,_2006.jpg",
                "license": "CC BY 2.0",
                "attribution": ".Martin.",
                "image_type": "Actor headshot",
                "cast": ["David Prowse"],
            },
            {
                "filename": "10_james_earl_jones.jpg",
                "title": "James Earl Jones (Darth Vader, voice)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Jones,_James_Earl_2.jpg",
                "license": "Public domain",
                "attribution": "Carl Van Vechten",
                "image_type": "Actor headshot",
                "cast": ["James Earl Jones"],
            },
        ],
    },
    {
        "id": "star_trek",
        "name": "Star Trek",
        "description": "A personal-use Star Trek TV show pack with cast metadata, a promotional cast image, and individual actor headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and Wikimedia Commons public-domain/CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "Star Trek",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:ST_TOS_Cast.jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "William Shatner",
                    "Leonard Nimoy",
                    "DeForest Kelley",
                    "James Doohan",
                    "Nichelle Nichols",
                    "George Takei",
                    "Walter Koenig",
                    "Majel Barrett",
                    "Grace Lee Whitney",
                ],
            },
            {
                "filename": "02_william_shatner.jpg",
                "title": "William Shatner (Captain Kirk)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Star_Trek_William_Shatner.JPG",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["William Shatner"],
            },
            {
                "filename": "03_leonard_nimoy.jpg",
                "title": "Leonard Nimoy (Mr. Spock)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Leonard_Nimoy_mid_1960s.JPG",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["Leonard Nimoy"],
            },
            {
                "filename": "04_deforest_kelley.jpg",
                "title": "DeForest Kelley (Dr. McCoy)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:DeForest_Kelley,_Dr._McCoy,_Star_Trek.jpg",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["DeForest Kelley"],
            },
            {
                "filename": "05_james_doohan.jpg",
                "title": "James Doohan (Scotty)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:James_Doohan_Scotty_Star_Trek.JPG",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["James Doohan"],
            },
            {
                "filename": "06_nichelle_nichols.jpg",
                "title": "Nichelle Nichols (Uhura)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Nichelle_Nichols,_NASA_Recruiter_-_GPN-2004-00017.jpg",
                "license": "Public domain",
                "attribution": "NASA",
                "image_type": "Actor headshot",
                "cast": ["Nichelle Nichols"],
            },
            {
                "filename": "07_george_takei.jpg",
                "title": "George Takei (Sulu)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:George_Takei_Sulu_Star_Trek.JPG",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["George Takei"],
            },
            {
                "filename": "08_walter_koenig.jpg",
                "title": "Walter Koenig (Chekov)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Walter_Koenig_Star_Trek.JPG",
                "license": "Public domain",
                "attribution": "NBC Television",
                "image_type": "Actor headshot",
                "cast": ["Walter Koenig"],
            },
            {
                "filename": "09_majel_barrett.jpg",
                "title": "Majel Barrett (Nurse Chapel)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Majel_Roddenberry_Star_Trek_Convention_Las_Vegas_20080814_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Beth Madison",
                "image_type": "Actor headshot",
                "cast": ["Majel Barrett"],
            },
            {
                "filename": "10_grace_lee_whitney.jpg",
                "title": "Grace Lee Whitney (Yeoman Rand)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Grace_Lee_Whitney_1976_(01).jpg",
                "license": "CC BY 2.0",
                "attribution": "Will Hart",
                "image_type": "Actor headshot",
                "cast": ["Grace Lee Whitney"],
            },
        ],
    },
    {
        "id": "star_trek_the_next_generation",
        "name": "Star Trek: The Next Generation",
        "description": "A personal-use Star Trek: The Next Generation TV show pack with cast metadata, a promotional cast image, and individual actor headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and Wikimedia Commons CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "Star Trek: The Next Generation",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:ST_TNG_Season_One_Cast.jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "Patrick Stewart",
                    "Jonathan Frakes",
                    "LeVar Burton",
                    "Denise Crosby",
                    "Michael Dorn",
                    "Gates McFadden",
                    "Marina Sirtis",
                    "Brent Spiner",
                    "Wil Wheaton",
                ],
            },
            {
                "filename": "02_patrick_stewart.jpg",
                "title": "Patrick Stewart (Captain Picard)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Patrick_Stewart_by_Gage_Skidmore_2.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Patrick Stewart"],
            },
            {
                "filename": "03_jonathan_frakes.jpg",
                "title": "Jonathan Frakes (Commander Riker)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Jonathan_Frakes_at_Galaxy_Con_Columbus.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "John Manard",
                "image_type": "Actor headshot",
                "cast": ["Jonathan Frakes"],
            },
            {
                "filename": "04_levar_burton.jpg",
                "title": "LeVar Burton (Geordi La Forge)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:LeVar_Burton_Photo_Op_GalaxyCon_Raleigh_2023.jpg",
                "license": "CC BY 2.0",
                "attribution": "Super Festivals from Ft. Lauderdale, USA",
                "image_type": "Actor headshot",
                "cast": ["LeVar Burton"],
            },
            {
                "filename": "05_denise_crosby.jpg",
                "title": "Denise Crosby (Tasha Yar)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Denise_Crosby_(53373315035).jpg",
                "license": "CC BY 2.0",
                "attribution": "Super Festivals from Ft. Lauderdale, USA",
                "image_type": "Actor headshot",
                "cast": ["Denise Crosby"],
            },
            {
                "filename": "06_michael_dorn.jpg",
                "title": "Michael Dorn (Worf)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Michael_Dorn_Photo_Op_GalaxyCon_San_Jose_2024_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Super Festivals from Ft. Lauderdale, USA",
                "image_type": "Actor headshot",
                "cast": ["Michael Dorn"],
            },
            {
                "filename": "07_gates_mcfadden.jpg",
                "title": "Gates McFadden (Dr. Crusher)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Gates_McFadden_Photo_Op_GalaxyCon_Raleigh_2025.jpg",
                "license": "CC BY 4.0",
                "attribution": "Super Festivals",
                "image_type": "Actor headshot",
                "cast": ["Gates McFadden"],
            },
            {
                "filename": "08_marina_sirtis.jpg",
                "title": "Marina Sirtis (Counselor Troi)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Marina_Sirtis_Photo_Op_GalaxyCon_Raleigh_2023.jpg",
                "license": "CC BY 2.0",
                "attribution": "Super Festivals from Ft. Lauderdale, USA",
                "image_type": "Actor headshot",
                "cast": ["Marina Sirtis"],
            },
            {
                "filename": "09_brent_spiner.jpg",
                "title": "Brent Spiner (Data)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Brent_Spiner_Photo_Op_GalaxyCon_Columbus_2025.jpg",
                "license": "CC BY 4.0",
                "attribution": "Super Festivals from Ft. Lauderdale, USA",
                "image_type": "Actor headshot",
                "cast": ["Brent Spiner"],
            },
            {
                "filename": "10_wil_wheaton.jpg",
                "title": "Wil Wheaton (Wesley Crusher)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Wil_Wheaton_Photo_Op_GalaxyCon_Raleigh_2019.jpg",
                "license": "CC BY 2.0",
                "attribution": "Super Festivals",
                "image_type": "Actor headshot",
                "cast": ["Wil Wheaton"],
            },
        ],
    },
    {
        "id": "stargate_sg1",
        "name": "Stargate SG-1",
        "description": "A personal-use Stargate SG-1 TV show pack with cast metadata, a promotional cast image, and individual actor headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and Wikimedia Commons public-domain/CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "Stargate SG-1",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:Stargate_SG-1_cast_minus_Jonas_Quinn.jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "Richard Dean Anderson",
                    "Michael Shanks",
                    "Amanda Tapping",
                    "Christopher Judge",
                    "Don S. Davis",
                    "Teryl Rothery",
                    "Corin Nemec",
                    "Ben Browder",
                    "Claudia Black",
                    "Beau Bridges",
                ],
            },
            {
                "filename": "02_richard_dean_anderson.jpg",
                "title": "Richard Dean Anderson (Jack O'Neill)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Richard_Dean_Anderson_(2012).jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Bagl8",
                "image_type": "Actor headshot",
                "cast": ["Richard Dean Anderson"],
            },
            {
                "filename": "03_michael_shanks.jpg",
                "title": "Michael Shanks (Daniel Jackson)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Michael_Shanks_Creation_Con_2007.jpg",
                "license": "CC BY 2.0",
                "attribution": "Suzan Marie",
                "image_type": "Actor headshot",
                "cast": ["Michael Shanks"],
            },
            {
                "filename": "04_amanda_tapping.jpg",
                "title": "Amanda Tapping (Samantha Carter)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Amanda_Tapping_by_Gage_Skidmore.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Amanda Tapping"],
            },
            {
                "filename": "05_christopher_judge.jpg",
                "title": "Christopher Judge (Teal'c)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Christopher_Judge_by_Gage_Skidmore.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Christopher Judge"],
            },
            {
                "filename": "06_don_s_davis.jpg",
                "title": "Don S. Davis (General Hammond)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Don_S._Davis_DF-SD-03-14217.jpg",
                "license": "Public domain",
                "attribution": "TSGT Michael R. Nixon, USAF",
                "image_type": "Actor headshot",
                "cast": ["Don S. Davis"],
            },
            {
                "filename": "07_teryl_rothery.jpg",
                "title": "Teryl Rothery (Dr. Fraiser)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Teryl-rothery-2006.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "CelebHeights.com",
                "image_type": "Actor headshot",
                "cast": ["Teryl Rothery"],
            },
            {
                "filename": "08_corin_nemec.jpg",
                "title": "Corin Nemec (Jonas Quinn)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Corin_Nemec_(15045413510).jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Eva Rinaldi",
                "image_type": "Actor headshot",
                "cast": ["Corin Nemec"],
            },
            {
                "filename": "09_ben_browder.jpg",
                "title": "Ben Browder (Cameron Mitchell)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Ben_Browder_Headshot.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Timebandit5565",
                "image_type": "Actor headshot",
                "cast": ["Ben Browder"],
            },
            {
                "filename": "10_claudia_black.jpg",
                "title": "Claudia Black (Vala Mal Doran)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Claudia_Black_San_Diego_ComicCon_2009_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Dave Fayram from Pacifica, United States",
                "image_type": "Actor headshot",
                "cast": ["Claudia Black"],
            },
            {
                "filename": "11_beau_bridges.jpg",
                "title": "Beau Bridges (General Landry)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Beau_Bridges_2011_(cropped).jpg",
                "license": "Public domain",
                "attribution": "U.S. Navy photo by Mass Communication Specialist 3rd Class Mikelle'D. Smith",
                "image_type": "Actor headshot",
                "cast": ["Beau Bridges"],
            },
        ],
    },
    {
        "id": "stargate_atlantis",
        "name": "Stargate Atlantis",
        "description": "A personal-use Stargate Atlantis TV show pack with cast metadata, a promotional cast image, and individual actor headshots.",
        "categories": ["TV Shows"],
        "license": "Mix of Wikipedia fair-use/non-free promotional image and Wikimedia Commons CC-licensed photos; see per-image notes.",
        "local_images": [
            {
                "filename": "01_cast.jpg",
                "title": "Stargate Atlantis",
                "source": "Wikipedia non-free promotional image",
                "source_url": "https://en.wikipedia.org/wiki/File:Stargate_Atlantis_season_4_cast_photo.jpg",
                "license": "Fair use / non-free promotional image",
                "rights_notes": "Low-resolution promotional cast image kept for personal Home Assistant display use.",
                "image_type": "Promotional cast image",
                "cast": [
                    "Joe Flanigan",
                    "Torri Higginson",
                    "Rachel Luttrell",
                    "Rainbow Sun Francks",
                    "David Hewlett",
                    "Jason Momoa",
                    "Paul McGillion",
                    "Jewel Staite",
                    "Robert Picardo",
                    "Amanda Tapping",
                ],
            },
            {
                "filename": "02_joe_flanigan.jpg",
                "title": "Joe Flanigan (John Sheppard)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Joe_Flanigan_Comic_Con_2008.jpg",
                "license": "CC BY 2.0",
                "attribution": "Jean",
                "image_type": "Actor headshot",
                "cast": ["Joe Flanigan"],
            },
            {
                "filename": "03_torri_higginson.jpg",
                "title": "Torri Higginson (Elizabeth Weir)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Torri_Higginson_2014_(cropped).jpg",
                "license": "CC BY 2.0",
                "attribution": "Patrick Subotkiewiez",
                "image_type": "Actor headshot",
                "cast": ["Torri Higginson"],
            },
            {
                "filename": "04_rachel_luttrell.jpg",
                "title": "Rachel Luttrell (Teyla Emmagan)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Rsz_rachel4.jpg",
                "license": "CC BY-SA 4.0",
                "attribution": "Serenafaye",
                "image_type": "Actor headshot",
                "cast": ["Rachel Luttrell"],
            },
            {
                "filename": "05_rainbow_sun_francks.jpg",
                "title": "Rainbow Sun Francks (Aiden Ford)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Rainbow_sun_francks.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Lee Snowden",
                "image_type": "Actor headshot",
                "cast": ["Rainbow Sun Francks"],
            },
            {
                "filename": "06_david_hewlett.jpg",
                "title": "David Hewlett (Rodney McKay)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:David-hewlett-vancouver-300.png",
                "license": "CC BY-SA 3.0",
                "attribution": "Andwhatsnext, aka Nancy J Price",
                "image_type": "Actor headshot",
                "cast": ["David Hewlett"],
            },
            {
                "filename": "07_jason_momoa.jpg",
                "title": "Jason Momoa (Ronon Dex)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Jason_Momoa_(42867509995)_(cropped).jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "Gage Skidmore from Peoria, AZ, United States of America",
                "image_type": "Actor headshot",
                "cast": ["Jason Momoa"],
            },
            {
                "filename": "08_paul_mcgillion.jpg",
                "title": "Paul McGillion (Carson Beckett)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Paul_McGillion_by_Gage_Skidmore_2.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Paul McGillion"],
            },
            {
                "filename": "09_jewel_staite.jpg",
                "title": "Jewel Staite (Jennifer Keller)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Jewel_Staite_2015.jpg",
                "license": "CC BY-SA 2.0",
                "attribution": "5of7",
                "image_type": "Actor headshot",
                "cast": ["Jewel Staite"],
            },
            {
                "filename": "10_robert_picardo.jpg",
                "title": "Robert Picardo (Richard Woolsey)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Robert_Picardo_at_53rd_Saturn_Awards_2026-01.jpg",
                "license": "CC BY 4.0",
                "attribution": "Kevin Paul",
                "image_type": "Actor headshot",
                "cast": ["Robert Picardo"],
            },
            {
                "filename": "11_amanda_tapping.jpg",
                "title": "Amanda Tapping (Samantha Carter, crossover from SG-1)",
                "source": "Wikimedia Commons",
                "source_url": "https://commons.wikimedia.org/wiki/File:Amanda_Tapping_by_Gage_Skidmore.jpg",
                "license": "CC BY-SA 3.0",
                "attribution": "Gage Skidmore",
                "image_type": "Actor headshot",
                "cast": ["Amanda Tapping"],
            },
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
    if os.path.exists(index_path):
        # Keep existing entries for packs not rebuilt in this run. Some legacy
        # packs are shipped in index.json without a PACKS definition here, so
        # preserve those instead of dropping them.
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
    for pack_id, entry in existing_by_id.items():
        if pack_id not in known_ids and pack_id not in RETIRED_PACK_IDS:
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

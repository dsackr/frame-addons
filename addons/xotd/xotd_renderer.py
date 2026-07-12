#!/usr/bin/env python3
"""xOTD (Day-of-the-Day) Renderer & Frame Uploader.

Fetches a daily joke, quote, or Bible verse -- depending on the configured
content_mode -- from the web or a local custom list, renders it onto a
premium high-contrast canvas, encodes it to the Spectra 6 4-bit binary
format, and uploads it to the Fraimic e-ink canvas frame.
"""

from __future__ import annotations

import argparse
import os
import sys
import json
import datetime
import urllib.request
import urllib.parse
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Constants & Color Palette
# ---------------------------------------------------------------------------
COLOR_BLACK = (0, 0, 0)         # Body text, borders, references/authors
COLOR_WHITE = (255, 255, 255)   # Background canvas
COLOR_RED = (178, 19, 24)      # Decorative quote marks, joke punchline
COLOR_BLUE = (33, 87, 186)     # Footer label / translation badge
COLOR_YELLOW = (239, 222, 68)   # Accent color (unused here, reserved)
COLOR_GREEN = (18, 95, 32)     # Accent color (unused here, reserved)

SPECTRA6_REAL_WORLD_RGB = (
    COLOR_BLACK,
    COLOR_WHITE,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_BLUE,
    COLOR_GREEN,
)

SPECTRA6_NIBBLE_VALUES = (0, 1, 2, 3, 5, 6)

# Premium fallback content in case the internet or an API is unreachable.
# Each list cycles by day-of-year so the fallback content still changes daily.
FALLBACK_QUOTES = [
    {"q": "The only way to do great work is to love what you do.", "a": "Steve Jobs"},
    {"q": "Difficulties strengthen the mind, as labor does the body.", "a": "Seneca"},
    {"q": "It is not that we have a short time to live, but that we waste a lot of it.", "a": "Seneca"},
    {"q": "Waste no more time arguing about what a good man should be. Be one.", "a": "Marcus Aurelius"},
    {"q": "The best way to predict the future is to create it.", "a": "Abraham Lincoln"},
    {"q": "In the middle of difficulty lies opportunity.", "a": "Albert Einstein"},
    {"q": "What you do makes a difference, and you have to decide what kind of difference you want to make.", "a": "Jane Goodall"},
    {"q": "Act as if what you do makes a difference. It does.", "a": "William James"},
    {"q": "We must use time as a tool, not as a couch.", "a": "John F. Kennedy"},
    {"q": "The only limit to our realization of tomorrow is our doubts of today.", "a": "Franklin D. Roosevelt"}
]

FALLBACK_VERSES = [
    {"q": "The LORD is my shepherd; I shall not want.", "r": "Psalm 23:1", "t": "KJV"},
    {"q": "For I know the plans I have for you, declares the LORD, plans for welfare and not for evil, to give you a future and a hope.", "r": "Jeremiah 29:11", "t": "NIV"},
    {"q": "I can do all things through him who strengthens me.", "r": "Philippians 4:13", "t": "KJV"},
    {"q": "Trust in the LORD with all your heart, and do not lean on your own understanding.", "r": "Proverbs 3:5", "t": "WEB"},
    {"q": "In all your ways acknowledge him, and he will make straight your paths.", "r": "Proverbs 3:6", "t": "WEB"},
    {"q": "But seek first the kingdom of God and his righteousness, and all these things will be added to you.", "r": "Matthew 6:33", "t": "NIV"},
    {"q": "Therefore do not be anxious about tomorrow, for tomorrow will be anxious for itself. Sufficient for the day is its own trouble.", "r": "Matthew 6:34", "t": "KJV"},
    {"q": "A new commandment I give to you, that you love one another: just as I have loved you, you also are to love one another.", "r": "John 13:34", "t": "KJV"},
    {"q": "Be strong and courageous. Do not fear or be in dread of them, for it is the LORD your God who goes with you. He will not leave you or forsake you.", "r": "Deuteronomy 31:6", "t": "WEB"},
    {"q": "Do not be conformed to this world, but be transformed by the renewal of your mind, that by testing you may discern what is the will of God, what is good and acceptable and perfect.", "r": "Romans 12:2", "t": "KJV"}
]

FALLBACK_JOKES = [
    {"setup": "Why don't scientists trust atoms?", "punchline": "Because they make up everything."},
    {"setup": "Why did the scarecrow win an award?", "punchline": "Because he was outstanding in his field."},
    {"setup": "What do you call fake spaghetti?", "punchline": "An impasta."},
    {"setup": "Why did the bicycle fall over?", "punchline": "It was two-tired."},
    {"setup": "How does a penguin build its house?", "punchline": "Igloos it together."},
    {"setup": "What do you call a fish with no eyes?", "punchline": "A fsh."},
    {"setup": "Why can't you give Elsa a balloon?", "punchline": "Because she'll let it go."},
    {"setup": "What did the ocean say to the shore?", "punchline": "Nothing, it just waved."},
    {"setup": "Why don't eggs tell jokes?", "punchline": "They'd crack each other up."},
    {"setup": "What do you call a bear with no teeth?", "punchline": "A gummy bear."},
]

FALLBACK_WORDS = [
    {"word": "Serendipity", "pos": "noun", "definition": "The occurrence of finding pleasant or valuable things without looking for them.", "example": "A chance meeting turned into a serendipity that changed her career."},
    {"word": "Ephemeral", "pos": "adjective", "definition": "Lasting for a very short time.", "example": "The beauty of cherry blossoms is ephemeral, lasting only a week or two."},
    {"word": "Resilience", "pos": "noun", "definition": "The capacity to recover quickly from difficulties; toughness.", "example": "Her resilience helped her rebuild after the setback."},
    {"word": "Luminous", "pos": "adjective", "definition": "Full of or shedding light; bright or shining.", "example": "The luminous moon lit up the entire valley."},
    {"word": "Meticulous", "pos": "adjective", "definition": "Showing great attention to detail; very careful and precise.", "example": "He kept meticulous records of every transaction."},
    {"word": "Wanderlust", "pos": "noun", "definition": "A strong desire to travel and explore the world.", "example": "Her wanderlust took her to six continents before she turned thirty."},
    {"word": "Eloquent", "pos": "adjective", "definition": "Fluent or persuasive in speaking or writing.", "example": "The eloquent speech moved the entire audience to tears."},
    {"word": "Tenacious", "pos": "adjective", "definition": "Tending to keep a firm hold of something; persistent.", "example": "Her tenacious pursuit of the goal finally paid off."},
    {"word": "Solitude", "pos": "noun", "definition": "The state or situation of being alone.", "example": "He found peace in the solitude of the mountains."},
    {"word": "Curiosity", "pos": "noun", "definition": "A strong desire to know or learn something.", "example": "Her curiosity led her to explore every corner of the old library."},
]

# ---------------------------------------------------------------------------
# Themes: each maps semantic roles (headline/accent font, badge/footer
# colors) onto real font families and the fixed 6-entry Spectra6 palette --
# themes never introduce new colors, only re-assign which of the 6 hardware
# colors plays which role, since the frame's e-ink panel can't render
# anything outside that palette anyway.
# ---------------------------------------------------------------------------
THEMES = {
    "classic": {
        "label": "Classic",
        "headline_font": "Outfit",
        "accent_font": "Outfit",
        "primary_color": COLOR_BLACK,
        "accent_color": COLOR_RED,
        "footer_color": COLOR_BLUE,
        "badge_bg": COLOR_BLUE,
        "badge_text": COLOR_WHITE,
    },
    "retro_atomic": {
        "label": "Retro Atomic Age",
        "headline_font": "Bungee",
        "accent_font": "Bungee",
        "primary_color": COLOR_BLACK,
        "accent_color": COLOR_RED,
        "footer_color": COLOR_BLACK,
        "badge_bg": COLOR_YELLOW,
        "badge_text": COLOR_BLACK,
    },
}

def get_theme(theme_name: str) -> dict:
    """Look up a theme by name, falling back to "classic" for an unknown
    or missing value so an old/malformed config.json never crashes render."""
    return THEMES.get(theme_name, THEMES["classic"])

# ---------------------------------------------------------------------------
# Helpers: Font Loader & Text Wrapper
# ---------------------------------------------------------------------------
# Each font family used by any theme has its own source repo and filename
# convention -- load_font looks a family up here instead of assuming
# Outfit's Outfitio/Outfit-Fonts layout for everything. Bungee is a single
# static-weight display font (Google Fonts), so every style name maps to
# its one file; requesting "Bold"/"SemiBold" just gets the same Regular
# glyphs, which is fine since Bungee is used only for short headline/accent
# text, never long body copy.
FONT_SOURCES = {
    "Outfit": {
        "base_url": "https://raw.githubusercontent.com/Outfitio/Outfit-Fonts/main/fonts/ttf",
        "styles": {
            "Regular": "Outfit-Regular.ttf",
            "Medium": "Outfit-Medium.ttf",
            "SemiBold": "Outfit-SemiBold.ttf",
            "Bold": "Outfit-Bold.ttf",
        },
    },
    "Bungee": {
        "base_url": "https://raw.githubusercontent.com/google/fonts/main/ofl/bungee",
        "styles": {
            "Regular": "Bungee-Regular.ttf",
            "Medium": "Bungee-Regular.ttf",
            "SemiBold": "Bungee-Regular.ttf",
            "Bold": "Bungee-Regular.ttf",
        },
    },
}

def load_font(font_name="Outfit", font_style="Regular", size=24) -> ImageFont.ImageFont:
    """Download a font (from whichever family's source is registered in
    FONT_SOURCES) if not cached locally, else load it."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "fonts")
    os.makedirs(font_dir, exist_ok=True)

    source = FONT_SOURCES.get(font_name, FONT_SOURCES["Outfit"])
    font_filename = source["styles"].get(font_style, source["styles"]["Regular"])
    font_path = os.path.join(font_dir, font_filename)

    if not os.path.exists(font_path):
        url = f"{source['base_url']}/{font_filename}"
        try:
            print(f"Downloading {font_filename} font from {url}...")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                with open(font_path, "wb") as f:
                    f.write(response.read())
        except Exception as e:
            print(f"Error downloading font: {e}. Falling back to default system font.")
            return ImageFont.load_default()

    try:
        return ImageFont.truetype(font_path, size)
    except Exception as e:
        print(f"Error loading font {font_path}: {e}. Falling back to default.")
        return ImageFont.load_default()

def wrap_text(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """Wrap words to fit within a maximum width boundary."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]

        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                # Word is wider than max_width, force onto its own line
                lines.append(word)
                current_line = []

    if current_line:
        lines.append(" ".join(current_line))

    return lines

def fit_text_to_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    font_loader,
    max_size: int,
    min_size: int = 16,
    step: int = 2,
    line_spacing_ratio: float = 0.28,
):
    """Find the largest font size in [min_size, max_size] whose word-wrapped
    text fits inside max_width x max_height, so a single block of content
    fills whatever room a given frame orientation leaves for it -- a short
    quote/joke renders big, a long one shrinks only as much as it has to."""
    size = max_size
    while size >= min_size:
        font = font_loader(size)
        lines = wrap_text(text, draw, font, max_width)
        line_spacing = max(int(size * line_spacing_ratio), 4)
        heights = []
        total = 0
        max_line_width = 0
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            heights.append(bbox[3] - bbox[1])
            total += heights[-1]
            max_line_width = max(max_line_width, bbox[2] - bbox[0])
        total += line_spacing * (len(lines) - 1)
        if total <= max_height and max_line_width <= max_width:
            return font, lines, heights, line_spacing, total
        size -= step

    # Even the floor size overflows (an unusually long passage) -- use it
    # anyway rather than shrinking past readability.
    font = font_loader(min_size)
    lines = wrap_text(text, draw, font, max_width)
    line_spacing = max(int(min_size * line_spacing_ratio), 4)
    heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
    total = sum(heights) + line_spacing * (len(lines) - 1)
    return font, lines, heights, line_spacing, total

def _wrapped_block_metrics(draw: ImageDraw.ImageDraw, lines: list[str], font: ImageFont.ImageFont, line_spacing: int) -> tuple[list[int], int, int]:
    """Per-line heights, total block height (with inter-line spacing), and the widest line."""
    heights = []
    total = 0
    max_line_width = 0
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        heights.append(bbox[3] - bbox[1])
        total += heights[-1]
        max_line_width = max(max_line_width, bbox[2] - bbox[0])
    total += line_spacing * (len(lines) - 1)
    return heights, total, max_line_width

def fit_two_blocks_to_box(
    draw: ImageDraw.ImageDraw,
    text_a: str,
    text_b: str,
    max_width: int,
    max_height: int,
    font_loader,
    max_size: int,
    min_size: int = 16,
    step: int = 2,
    line_spacing_ratio: float = 0.28,
    block_gap_ratio: float = 0.5,
):
    """Find the largest font size in [min_size, max_size] at which two
    stacked text blocks -- both set at that same size, so the second block
    reads as co-equal with the first rather than a footnote -- still
    word-wrap to fit inside max_width x max_height together. Used for
    scripture's verse+reference and a two-line joke's setup+punchline."""
    size = max_size
    while size >= min_size:
        font = font_loader(size)
        line_spacing = max(int(size * line_spacing_ratio), 4)
        block_gap = max(int(size * block_gap_ratio), 8)

        lines_a = wrap_text(text_a, draw, font, max_width)
        lines_b = wrap_text(text_b, draw, font, max_width)
        heights_a, total_a, max_w_a = _wrapped_block_metrics(draw, lines_a, font, line_spacing)
        heights_b, total_b, max_w_b = _wrapped_block_metrics(draw, lines_b, font, line_spacing)

        total_height = total_a + block_gap + total_b
        max_line_width = max(max_w_a, max_w_b)
        if total_height <= max_height and max_line_width <= max_width:
            return font, lines_a, heights_a, lines_b, heights_b, line_spacing, block_gap, total_height
        size -= step

    # Even the floor size overflows (an unusually long passage) -- use it
    # anyway rather than shrinking past readability.
    font = font_loader(min_size)
    line_spacing = max(int(min_size * line_spacing_ratio), 4)
    block_gap = max(int(min_size * block_gap_ratio), 8)
    lines_a = wrap_text(text_a, draw, font, max_width)
    lines_b = wrap_text(text_b, draw, font, max_width)
    heights_a, total_a, _ = _wrapped_block_metrics(draw, lines_a, font, line_spacing)
    heights_b, total_b, _ = _wrapped_block_metrics(draw, lines_b, font, line_spacing)
    total_height = total_a + block_gap + total_b
    return font, lines_a, heights_a, lines_b, heights_b, line_spacing, block_gap, total_height

# ---------------------------------------------------------------------------
# Drop Cap: a decorative oversized-first-letter tile, drawn as its own row
# above the paragraph rather than true wrap-around typography (which needs
# per-line variable-width wrapping that wrap_text/fit_text_to_box don't
# do) -- simpler to get right, and still reads clearly as "drop cap" at
# this canvas size. Enabling it switches that block from centered to
# left-aligned, since drop caps are a left/justified-text convention.
#
# The tile duplicates the first letter rather than replacing it: the tile
# sits in its own row above the paragraph (not inline beside its first
# line, which would need real per-line variable-width wrapping), so
# removing the letter from the body text would just read as a typo --
# "hy did the..." with no visual link back to the "W" tile above it.
# Showing it in both places costs nothing (the tile is purely decorative)
# and guarantees the body text is never mangled.
# ---------------------------------------------------------------------------
def first_letter_for_drop_cap(text: str) -> str:
    text = text.strip()
    return text[0] if text else ""

def draw_drop_cap_tile(
    draw: ImageDraw.ImageDraw, letter: str, x: int, y: int, size: int,
    fill_color: tuple, text_color: tuple, font_loader,
) -> None:
    """A filled square tile with one large centered letter."""
    draw.rectangle((x, y, x + size, y + size), fill=fill_color)
    font = font_loader(int(size * 0.62))
    bbox = draw.textbbox((0, 0), letter, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (x + (size - tw) // 2 - bbox[0], y + (size - th) // 2 - bbox[1]),
        letter, fill=text_color, font=font,
    )

def draw_text_block(
    draw: ImageDraw.ImageDraw, lines: list[str], heights: list[int], line_spacing: int,
    font: ImageFont.ImageFont, text_color: tuple, width: int, start_y: int, left_x: int = None,
) -> int:
    """Draw pre-wrapped lines either centered (left_x=None, the default
    for every non-drop-cap block) or left-aligned at left_x. Returns the y
    position just below the block, for callers stacking more content after
    it."""
    curr_y = start_y
    for i, line in enumerate(lines):
        if left_x is None:
            draw.text((width // 2, curr_y), line, fill=text_color, font=font, anchor="ma")
        else:
            draw.text((left_x, curr_y), line, fill=text_color, font=font, anchor="la")
        curr_y += heights[i] + line_spacing
    return curr_y

# ---------------------------------------------------------------------------
# Content Fetchers
# ---------------------------------------------------------------------------
def fetch_quote(quote_feed: str, custom_quotes: list[dict], api_url: str = None) -> dict:
    """Retrieve quote from chosen API feed or local custom list, falling back to built-ins if needed."""
    if quote_feed == "custom":
        if api_url:
            print(f"Fetching daily quote from custom API: {api_url}")
            url = api_url
        elif custom_quotes:
            print("Selecting quote from custom list...")
            day_of_year = datetime.datetime.now().timetuple().tm_yday
            index = day_of_year % len(custom_quotes)
            return custom_quotes[index]
        else:
            print("Warning: custom feed selected but no custom_quotes or custom API URL. Falling back to ZenQuotes.")
            url = api_url or "https://zenquotes.io/api/today"
    elif quote_feed == "favqs":
        print("Fetching daily quote from FavQs API...")
        url = api_url or "https://favqs.com/api/qotd"
    else:  # Default/zenquotes/api
        print("Fetching daily quote from ZenQuotes API...")
        url = api_url or "https://zenquotes.io/api/today"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FraimicXotdAddon/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        if "favqs.com" in url or quote_feed == "favqs":
            # FavQs returns {"quote": {"body": "...", "author": "..."}}
            quote_data = data.get("quote", {})
            return {
                "q": quote_data.get("body", ""),
                "a": quote_data.get("author", "Unknown")
            }
        else:
            # ZenQuotes returns a list: [{"q": "...", "a": "..."}]
            if isinstance(data, list) and len(data) > 0:
                return {
                    "q": data[0].get("q", ""),
                    "a": data[0].get("a", "Unknown")
                }
            elif isinstance(data, dict):
                return {
                    "q": data.get("q", data.get("quote", data.get("body", ""))),
                    "a": data.get("a", data.get("author", "Unknown"))
                }
    except Exception as e:
        print(f"Error fetching quote from API: {e}. Falling back to default list.")

    # Built-in fallback
    day_of_year = datetime.datetime.now().timetuple().tm_yday
    index = day_of_year % len(FALLBACK_QUOTES)
    return FALLBACK_QUOTES[index]

def fetch_scripture(translation: str, custom_scriptures: list[dict], source_type: str = "daily_api", ourmanna_url: str = None, bible_api_url: str = None) -> dict:
    """Retrieve scripture from OurManna/Bible-API or custom list, falling back if needed."""
    if source_type == "custom_list" and custom_scriptures:
        print("Selecting scripture from custom list...")
        day_of_year = datetime.datetime.now().timetuple().tm_yday
        index = day_of_year % len(custom_scriptures)
        item = custom_scriptures[index]
        return {
            "q": item.get("q", "").strip(),
            "r": item.get("r", "Unknown").strip(),
            "t": item.get("t", translation.upper()).strip()
        }

    print("Fetching daily verse of the day from OurManna...")
    ourmanna_endpoint = ourmanna_url or "https://beta.ourmanna.com/api/v1/get?format=json&order=daily"
    ref = None
    text = None
    ver = "NIV"

    try:
        req = urllib.request.Request(ourmanna_endpoint, headers={"User-Agent": "FraimicXotdAddon/1.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            verse_data = data.get("verse", {}).get("details", {})
            text = verse_data.get("text", "")
            ref = verse_data.get("reference", "")
            ver = verse_data.get("version", "NIV")
    except Exception as e:
        print(f"Error fetching from OurManna: {e}")

    target_translation = translation.lower().strip()
    if ref and target_translation != "niv":
        supported = ["kjv", "web", "bbe", "oeb", "webbe", "almeida", "rvr1960"]
        api_trans = target_translation
        if api_trans not in supported:
            # Fallback to KJV if ESV/NIV was requested but they want a keyless translation
            api_trans = "kjv"
            print(f"Translation '{translation}' not supported by keyless API. Falling back to KJV.")

        print(f"Fetching '{ref}' in '{api_trans.upper()}' translation from Bible-API...")
        if bible_api_url:
            url = bible_api_url.replace("{reference}", urllib.parse.quote(ref)).replace("{translation}", api_trans)
        else:
            ref_encoded = urllib.parse.quote(ref)
            url = f"https://bible-api.com/{ref_encoded}?translation={api_trans}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FraimicXotdAddon/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                api_data = json.loads(response.read().decode("utf-8"))
                text = api_data.get("text", "").strip()
                ref = api_data.get("reference", "").strip()
                ver = api_trans.upper()
        except Exception as e:
            print(f"Error fetching translation from Bible-API: {e}. Using OurManna default text (NIV).")

    if text and ref:
        return {
            "q": text.strip(),
            "r": ref.strip(),
            "t": ver.upper()
        }

    print("Using local fallback scripture...")
    day_of_year = datetime.datetime.now().timetuple().tm_yday
    index = day_of_year % len(FALLBACK_VERSES)
    return FALLBACK_VERSES[index]

def fetch_joke(joke_feed: str, custom_jokes: list[dict], api_url: str = None) -> dict:
    """Retrieve a joke from the chosen web feed or local custom list, falling
    back to built-ins if needed. Always returns {"setup": str, "punchline": str}
    -- punchline may be "" for a flat single-line joke (e.g. icanhazdadjoke's
    default response, or a custom {"joke": "..."} entry)."""
    def _normalize(item: dict) -> dict:
        if "setup" in item or "punchline" in item:
            return {"setup": item.get("setup", "").strip(), "punchline": item.get("punchline", "").strip()}
        return {"setup": item.get("joke", "").strip(), "punchline": ""}

    if joke_feed == "custom":
        if api_url:
            print(f"Fetching daily joke from custom API: {api_url}")
            url = api_url
        elif custom_jokes:
            print("Selecting joke from custom list...")
            day_of_year = datetime.datetime.now().timetuple().tm_yday
            index = day_of_year % len(custom_jokes)
            return _normalize(custom_jokes[index])
        else:
            print("Warning: custom feed selected but no custom_jokes or custom API URL. Falling back to icanhazdadjoke.")
            url = "https://icanhazdadjoke.com/"
    else:  # default/icanhazdadjoke
        print("Fetching daily joke from icanhazdadjoke.com...")
        url = api_url or "https://icanhazdadjoke.com/"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FraimicXotdAddon/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        return _normalize(data)
    except Exception as e:
        print(f"Error fetching joke from API: {e}. Falling back to default list.")

    day_of_year = datetime.datetime.now().timetuple().tm_yday
    index = day_of_year % len(FALLBACK_JOKES)
    return FALLBACK_JOKES[index]

def fetch_word(
    word_feed: str,
    custom_words: list[dict],
    api_url: str = None,
    random_word_api_url: str = None,
    dictionary_api_url: str = None,
) -> dict:
    """Retrieve a word of the day (word + part of speech + definition +
    optional example) from a free two-hop lookup (a random word, then its
    definition) or a local custom list, falling back to built-ins if
    needed. Always returns {"word", "pos", "definition", "example"}."""
    if word_feed == "custom":
        if api_url:
            print(f"Fetching daily word from custom API: {api_url}")
            try:
                req = urllib.request.Request(api_url, headers={"User-Agent": "FraimicXotdAddon/1.0"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return {
                    "word": data.get("word", "").strip(),
                    "pos": data.get("pos", "").strip(),
                    "definition": data.get("definition", "").strip(),
                    "example": data.get("example", "").strip(),
                }
            except Exception as e:
                print(f"Error fetching word from custom API: {e}. Falling back to default list.")
        elif custom_words:
            print("Selecting word from custom list...")
            day_of_year = datetime.datetime.now().timetuple().tm_yday
            index = day_of_year % len(custom_words)
            item = custom_words[index]
            return {
                "word": item.get("word", "").strip(),
                "pos": item.get("pos", "").strip(),
                "definition": item.get("definition", "").strip(),
                "example": item.get("example", "").strip(),
            }
        else:
            print("Warning: custom feed selected but no custom_words or custom API URL. Falling back to random word lookup.")
    else:
        print("Fetching daily word from a random word + dictionary lookup...")

    # Default feed: pull a random word, then look up its definition -- retry
    # a handful of times since not every random word has a dictionary entry.
    random_word_url = random_word_api_url or "https://random-word-api.herokuapp.com/word"
    for attempt in range(5):
        try:
            req = urllib.request.Request(random_word_url, headers={"User-Agent": "FraimicXotdAddon/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                words = json.loads(response.read().decode("utf-8"))
            word = (words[0] if words else "").strip()
            if not word:
                continue

            if dictionary_api_url:
                def_url = dictionary_api_url.replace("{word}", urllib.parse.quote(word))
            else:
                def_url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"

            req2 = urllib.request.Request(def_url, headers={"User-Agent": "FraimicXotdAddon/1.0"})
            with urllib.request.urlopen(req2, timeout=10) as response2:
                entries = json.loads(response2.read().decode("utf-8"))

            meanings = entries[0].get("meanings", []) if entries else []
            if not meanings:
                continue
            first_meaning = meanings[0]
            pos = first_meaning.get("partOfSpeech", "")
            defs = first_meaning.get("definitions", [])
            if not defs:
                continue
            definition = defs[0].get("definition", "")
            example = defs[0].get("example", "")

            if word and definition:
                return {"word": word.capitalize(), "pos": pos, "definition": definition, "example": example}
        except Exception as e:
            print(f"Error fetching word/definition (attempt {attempt + 1}): {e}")

    print("Using local fallback word...")
    day_of_year = datetime.datetime.now().timetuple().tm_yday
    index = day_of_year % len(FALLBACK_WORDS)
    return FALLBACK_WORDS[index]

# ---------------------------------------------------------------------------
# Visual Composition Renderers
# ---------------------------------------------------------------------------
def render_quote_image(width: int, height: int, quote: str, author: str, theme: str = "classic", drop_cap: bool = False) -> Image.Image:
    """Compose the quote layout with double borders, quotation marks, and footer."""
    t = get_theme(theme)
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    is_landscape = width > height

    # Structural layout (margins, decorative offsets) still differs by
    # orientation -- but quote_font_size is auto-fit below to whatever room
    # this orientation leaves, so a short quote renders bigger on a portrait
    # frame than on a squatter landscape one, and a long quote shrinks only
    # as needed, instead of every quote sharing one static size per
    # orientation.
    if is_landscape:
        border_outer_margin = 20
        border_inner_margin = 26
        author_font_size = 24
        footer_font_size = 14
        quote_marks_size = 100  # decorative flourish, sized off the canvas, not the fitted quote font
        wrap_width = width - 240  # 560px wrap
        quote_marks_y_offset = 30
        author_y_offset = 30
        max_quote_font_size = 220  # generous ceiling -- the width/height fit below is what actually caps it
        min_quote_font_size = 20
    else:
        border_outer_margin = 40
        border_inner_margin = 50
        author_font_size = 34
        footer_font_size = 20
        quote_marks_size = 150
        wrap_width = width - 360  # 840px wrap
        quote_marks_y_offset = 70
        author_y_offset = 50
        max_quote_font_size = 400
        min_quote_font_size = 28

    font_author = load_font(t["accent_font"], "SemiBold", author_font_size)
    font_footer = load_font(t["accent_font"], "SemiBold", footer_font_size)
    font_quote_marks = load_font(t["accent_font"], "Bold", quote_marks_size)

    # 1. Draw borders
    draw.rectangle(
        (border_outer_margin, border_outer_margin, width - border_outer_margin, height - border_outer_margin),
        outline=t["primary_color"], width=3 if not is_landscape else 2
    )
    draw.rectangle(
        (border_inner_margin, border_inner_margin, width - border_inner_margin, height - border_inner_margin),
        outline=t["primary_color"], width=1
    )

    # 2. Auto-fit the quote's font size to the room left after reserving
    # space for the (fixed-size) opening quote mark above (or, in drop-cap
    # mode, the decorative letter tile occupying that same reserved space)
    # and the author + footer band below -- this reserve is independent of
    # max_quote_font_size so raising that ceiling to let short quotes grow
    # doesn't also shrink the room being fit into.
    top_reserved = quote_marks_y_offset + quote_marks_size * 0.6
    bottom_reserved = author_y_offset + author_font_size + footer_font_size + 60
    available_height = (height - 2 * border_inner_margin) - top_reserved - bottom_reserved

    drop_letter = first_letter_for_drop_cap(quote) if drop_cap else ""

    font_quote, wrapped_lines, line_heights, line_spacing, total_text_height = fit_text_to_box(
        draw, quote, wrap_width, available_height,
        font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
        max_size=max_quote_font_size, min_size=min_quote_font_size
    )

    total_block_height = total_text_height + author_y_offset + author_font_size
    start_y = (height - total_block_height) // 2
    left_x = (width - wrap_width) // 2

    if drop_cap and drop_letter:
        # 3. Drop cap tile stands in for the decorative opening quote mark
        # -- clamped to the space top_reserved already budgeted for that
        # mark, since a long quote's tiny fitted font would otherwise size
        # the tile far smaller than the reserve, while a short quote's huge
        # fitted font would otherwise size it far larger and overflow
        # above the border.
        font_size = getattr(font_quote, "size", min_quote_font_size)
        tile_size = min(int(font_size * 1.7), int(top_reserved) - 15)
        draw_drop_cap_tile(
            draw, drop_letter, left_x, start_y - tile_size - 10, tile_size,
            t["accent_color"], COLOR_WHITE,
            font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
        )
        # 4. Quote lines, left-aligned (drop caps are a left-text convention)
        current_y = draw_text_block(
            draw, wrapped_lines, line_heights, line_spacing, font_quote,
            t["primary_color"], width, start_y, left_x=left_x,
        )
    else:
        # 3. Opening quote mark (top-left)
        draw.text(
            (border_inner_margin + 40, start_y - quote_marks_y_offset),
            "“", fill=t["accent_color"], font=font_quote_marks
        )
        # 4. Quote lines, centered
        current_y = draw_text_block(
            draw, wrapped_lines, line_heights, line_spacing, font_quote,
            t["primary_color"], width, start_y,
        )
        # Closing quote mark (bottom-right, drawn after author position is known below)

    # 5. Author (aligned right)
    author_y = current_y + author_y_offset
    draw.text(
        (width - (border_inner_margin + 60), author_y),
        f"— {author}", fill=t["primary_color"], font=font_author, anchor="ra"
    )

    if not drop_cap:
        draw.text(
            (width - (border_inner_margin + 40 + quote_marks_size // 2), author_y + author_font_size // 2),
            "”", fill=t["accent_color"], font=font_quote_marks
        )

    # 6. Footer Label
    draw.text(
        (width // 2, height - border_inner_margin - 30),
        "QUOTE OF THE DAY", fill=t["footer_color"], font=font_footer, anchor="ma"
    )

    return img

def render_scripture_image(width: int, height: int, quote: str, reference: str, translation: str, theme: str = "classic", drop_cap: bool = False) -> Image.Image:
    """Compose the scripture layout with double borders and a reference set
    co-equal in size with the verse itself (no decorative emblem)."""
    t = get_theme(theme)
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    is_landscape = width > height

    # Structural layout (margins, top/bottom padding) still differs by
    # orientation -- but the verse and reference font size is auto-fit below
    # to whatever room this orientation leaves, so a short verse renders
    # bigger on a portrait frame than on a squatter landscape one, and a
    # long passage shrinks only as needed, instead of every verse sharing
    # one static size per orientation.
    if is_landscape:
        border_outer_margin = 20
        border_inner_margin = 26
        badge_font_size = 14
        wrap_width = width - 200
        top_padding = 25
        bottom_padding = 55  # keeps the last line clear of the translation badge
        max_quote_font_size = 200  # generous ceiling -- the width/height fit below is what actually caps it
        min_quote_font_size = 18
        dropcap_reserve = 70
    else:
        border_outer_margin = 40
        border_inner_margin = 50
        badge_font_size = 18
        wrap_width = width - 300
        top_padding = 40
        bottom_padding = 80
        max_quote_font_size = 350
        min_quote_font_size = 24
        dropcap_reserve = 130

    font_badge = load_font(t["accent_font"], "Bold", badge_font_size)

    # 1. Draw double borders
    draw.rectangle(
        (border_outer_margin, border_outer_margin, width - border_outer_margin, height - border_outer_margin),
        outline=t["primary_color"], width=3 if not is_landscape else 2
    )
    draw.rectangle(
        (border_inner_margin, border_inner_margin, width - border_inner_margin, height - border_inner_margin),
        outline=t["primary_color"], width=1
    )

    # 2. Clean up quote marks (skipped entirely in drop-cap mode, where the
    # tile itself is the decorative opening mark), then auto-fit the verse
    # and its reference -- both measured at the same candidate size, so the
    # reference reads as co-equal with the verse instead of a footnote --
    # to the room between the borders (minus top/bottom padding, plus a
    # fixed reserve above for the drop-cap tile when enabled).
    raw_verse = quote.replace('"', '').replace('“', '').replace('”', '').strip()
    drop_letter = first_letter_for_drop_cap(raw_verse) if drop_cap else ""
    clean_quote = raw_verse if drop_cap else f"“ {raw_verse} ”"
    clean_ref = reference.strip()

    content_top = border_inner_margin + top_padding + (dropcap_reserve if drop_cap else 0)
    available_height = (height - border_inner_margin - bottom_padding) - content_top

    (font_quote, quote_lines, quote_heights, ref_lines, ref_heights,
     line_spacing, block_gap, total_height) = fit_two_blocks_to_box(
        draw, clean_quote, clean_ref, wrap_width, available_height,
        font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
        max_size=max_quote_font_size, min_size=min_quote_font_size
    )
    # SemiBold at the same point size the fit found for the (Bold) verse --
    # SemiBold glyphs run slightly narrower than Bold, so reusing the Bold
    # wrap decisions here is a conservative choice that can't overflow.
    font_ref = load_font(t["accent_font"], "SemiBold", getattr(font_quote, "size", min_quote_font_size))

    left_x = (width - wrap_width) // 2

    if drop_cap and drop_letter:
        tile_size = dropcap_reserve - 20
        draw_drop_cap_tile(
            draw, drop_letter, left_x, content_top - dropcap_reserve + 10, tile_size,
            t["accent_color"], COLOR_WHITE,
            font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
        )

    # 3. Draw the verse, then its reference, as one block -- centered by
    # default, or left-aligned under the drop-cap tile when enabled.
    curr_y = content_top + (available_height - total_height) // 2
    for i, line in enumerate(quote_lines):
        if drop_cap:
            x = left_x
        else:
            bbox = draw.textbbox((0, 0), line, font=font_quote)
            x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, curr_y), line, fill=t["primary_color"], font=font_quote)
        curr_y += quote_heights[i] + line_spacing

    curr_y += block_gap - line_spacing  # swap the quote loop's trailing line gap for the wider block gap
    for i, line in enumerate(ref_lines):
        if drop_cap:
            x = left_x
        else:
            bbox = draw.textbbox((0, 0), line, font=font_ref)
            x = (width - (bbox[2] - bbox[0])) // 2
        draw.text((x, curr_y), line, fill=t["primary_color"], font=font_ref)
        curr_y += ref_heights[i] + line_spacing

    # 4. Draw Translation Badge in bottom right corner
    badge_text = translation.upper().strip()
    bbox_b = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = bbox_b[2] - bbox_b[0] + 16
    bh = bbox_b[3] - bbox_b[1] + 10
    bx = width - border_inner_margin - bw - 15
    by = height - border_inner_margin - bh - 15

    draw.rectangle((bx, by, bx + bw, by + bh), fill=t["badge_bg"])
    draw.text((bx + 8, by + 5), badge_text, fill=t["badge_text"], font=font_badge)

    return img

def render_joke_image(width: int, height: int, setup: str, punchline: str, theme: str = "classic", drop_cap: bool = False) -> Image.Image:
    """Compose the joke layout: double border (matching quote/scripture),
    setup and punchline auto-fit as co-equal stacked blocks when a
    punchline exists (reusing fit_two_blocks_to_box, the same helper
    scripture uses for verse+reference) -- setup in the theme's primary
    color, punchline in its accent color for a visual "reveal" pop -- with
    a centered "JOKE OF THE DAY" footer label (quote's footer convention;
    there's no per-joke metadata to badge the way scripture badges its
    translation). A flat single-string joke (punchline empty, e.g.
    icanhazdadjoke's default response) instead auto-fits as one block via
    fit_text_to_box, matching quote's single-block path. Drop cap (when
    enabled) always applies to the setup, left-aligning both blocks."""
    t = get_theme(theme)
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    is_landscape = width > height

    if is_landscape:
        border_outer_margin = 20
        border_inner_margin = 26
        footer_font_size = 14
        wrap_width = width - 200
        top_padding = 25
        bottom_padding = 55
        max_font_size = 200
        min_font_size = 18
        dropcap_reserve = 70
    else:
        border_outer_margin = 40
        border_inner_margin = 50
        footer_font_size = 20
        wrap_width = width - 300
        top_padding = 40
        bottom_padding = 80
        max_font_size = 350
        min_font_size = 24
        dropcap_reserve = 130

    font_footer = load_font(t["accent_font"], "SemiBold", footer_font_size)

    # 1. Draw double borders
    draw.rectangle(
        (border_outer_margin, border_outer_margin, width - border_outer_margin, height - border_outer_margin),
        outline=t["primary_color"], width=3 if not is_landscape else 2
    )
    draw.rectangle(
        (border_inner_margin, border_inner_margin, width - border_inner_margin, height - border_inner_margin),
        outline=t["primary_color"], width=1
    )

    content_top = border_inner_margin + top_padding + (dropcap_reserve if drop_cap else 0)
    available_height = (height - border_inner_margin - bottom_padding) - content_top
    left_x = (width - wrap_width) // 2

    drop_letter = first_letter_for_drop_cap(setup) if drop_cap else ""

    if punchline:
        (font_joke, setup_lines, setup_heights, punch_lines, punch_heights,
         line_spacing, block_gap, total_height) = fit_two_blocks_to_box(
            draw, setup, punchline, wrap_width, available_height,
            font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
            max_size=max_font_size, min_size=min_font_size
        )

        if drop_cap and drop_letter:
            tile_size = dropcap_reserve - 20
            draw_drop_cap_tile(
                draw, drop_letter, left_x, content_top - dropcap_reserve + 10, tile_size,
                t["accent_color"], COLOR_WHITE,
                font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
            )

        curr_y = content_top + (available_height - total_height) // 2
        for i, line in enumerate(setup_lines):
            if drop_cap:
                x = left_x
            else:
                bbox = draw.textbbox((0, 0), line, font=font_joke)
                x = (width - (bbox[2] - bbox[0])) // 2
            draw.text((x, curr_y), line, fill=t["primary_color"], font=font_joke)
            curr_y += setup_heights[i] + line_spacing

        curr_y += block_gap - line_spacing
        for i, line in enumerate(punch_lines):
            if drop_cap:
                x = left_x
            else:
                bbox = draw.textbbox((0, 0), line, font=font_joke)
                x = (width - (bbox[2] - bbox[0])) // 2
            draw.text((x, curr_y), line, fill=t["accent_color"], font=font_joke)
            curr_y += punch_heights[i] + line_spacing
    else:
        font_joke, lines, heights, line_spacing, total_height = fit_text_to_box(
            draw, setup, wrap_width, available_height,
            font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
            max_size=max_font_size, min_size=min_font_size
        )

        if drop_cap and drop_letter:
            tile_size = dropcap_reserve - 20
            draw_drop_cap_tile(
                draw, drop_letter, left_x, content_top - dropcap_reserve + 10, tile_size,
                t["accent_color"], COLOR_WHITE,
                font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
            )

        curr_y = content_top + (available_height - total_height) // 2
        draw_text_block(
            draw, lines, heights, line_spacing, font_joke, t["primary_color"], width, curr_y,
            left_x=left_x if drop_cap else None,
        )

    # Footer Label
    draw.text(
        (width // 2, height - border_inner_margin - 30),
        "JOKE OF THE DAY", fill=t["footer_color"], font=font_footer, anchor="ma"
    )

    return img

def render_word_image(width: int, height: int, word: str, pos: str, definition: str, example: str, theme: str = "classic", drop_cap: bool = False) -> Image.Image:
    """Compose the word-of-the-day layout: double border (matching the
    other modes), the word itself auto-fit large in a reserved top region
    (so a one-letter word and a fifteen-letter word both read as the hero
    content), its part of speech as a small badge beneath it, then the
    definition -- and, if present, an example sentence -- auto-fit within a
    deliberately low size ceiling so they always read as secondary/caption
    text rather than competing with the word for attention. Drop cap (when
    enabled) applies to the definition only -- the word itself stays
    centered as the hero, a drop cap on a single giant word wouldn't mean
    anything."""
    t = get_theme(theme)
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    is_landscape = width > height

    if is_landscape:
        border_outer_margin = 20
        border_inner_margin = 26
        pos_font_size = 15
        example_font_size = 15
        footer_font_size = 14
        wrap_width = width - 200
        top_padding = 20
        bottom_padding = 55
        max_word_font_size = 140
        min_word_font_size = 28
        max_def_font_size = 22
        min_def_font_size = 14
        word_area_ratio = 0.45
        dropcap_reserve = 60
    else:
        border_outer_margin = 40
        border_inner_margin = 50
        pos_font_size = 20
        example_font_size = 20
        footer_font_size = 20
        wrap_width = width - 300
        top_padding = 30
        bottom_padding = 80
        max_word_font_size = 260
        min_word_font_size = 40
        max_def_font_size = 40
        min_def_font_size = 20
        word_area_ratio = 0.45
        dropcap_reserve = 100

    font_pos = load_font(t["accent_font"], "SemiBold", pos_font_size)
    font_example = load_font(t["accent_font"], "SemiBold", example_font_size)
    font_footer = load_font(t["accent_font"], "SemiBold", footer_font_size)

    # 1. Draw double borders
    draw.rectangle(
        (border_outer_margin, border_outer_margin, width - border_outer_margin, height - border_outer_margin),
        outline=t["primary_color"], width=3 if not is_landscape else 2
    )
    draw.rectangle(
        (border_inner_margin, border_inner_margin, width - border_inner_margin, height - border_inner_margin),
        outline=t["primary_color"], width=1
    )

    content_top = border_inner_margin + top_padding
    content_bottom = height - border_inner_margin - bottom_padding
    available_total = content_bottom - content_top
    left_x = (width - wrap_width) // 2

    # 2. Measure every block first (word, part-of-speech badge, definition,
    # example) so the whole stack can be centered as one unit -- the same
    # approach quote/scripture use -- rather than anchoring the word to the
    # top and leaving a dead gap below a short definition.
    font_word, word_lines, word_heights, word_line_spacing, word_total_height = fit_text_to_box(
        draw, word, wrap_width, int(available_total * word_area_ratio),
        font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
        max_size=max_word_font_size, min_size=min_word_font_size,
    )

    pos_text = pos.upper().strip() if pos else ""
    if pos_text:
        bbox_p = draw.textbbox((0, 0), pos_text, font=font_pos)
        pos_w = bbox_p[2] - bbox_p[0] + 20
        pos_h = bbox_p[3] - bbox_p[1] + 10
    else:
        pos_w = pos_h = 0

    # Definition is capped to a low size ceiling (max_def_font_size is
    # small, independent of how much room is actually available) so it
    # always reads as secondary/caption text underneath the word rather
    # than competing with it.
    drop_letter = first_letter_for_drop_cap(definition) if drop_cap else ""
    font_def, def_lines, def_heights, def_line_spacing, def_total_height = fit_text_to_box(
        draw, definition, wrap_width, available_total,
        font_loader=lambda size: load_font(t["accent_font"], "SemiBold", size),
        max_size=max_def_font_size, min_size=min_def_font_size,
        line_spacing_ratio=0.35,
    )

    example_lines = wrap_text(f"“{example}”", draw, font_example, wrap_width) if example else []
    example_heights = [draw.textbbox((0, 0), line, font=font_example)[3] - draw.textbbox((0, 0), line, font=font_example)[1] for line in example_lines]

    gap_word_to_pos = 20 if pos_text else 0
    gap_pos_to_def = (24 if pos_text else 16) + (dropcap_reserve if drop_cap and drop_letter else 0)
    gap_def_to_example = 24 if example_lines else 0

    total_content_height = (
        word_total_height + gap_word_to_pos + pos_h + gap_pos_to_def
        + def_total_height + gap_def_to_example + sum(example_heights) + 8 * max(0, len(example_heights) - 1)
    )

    curr_y = content_top + max(0, (available_total - total_content_height) // 2)

    # 3. Draw the word (always centered -- see docstring)
    for i, line in enumerate(word_lines):
        draw.text((width // 2, curr_y), line, fill=t["primary_color"], font=font_word, anchor="ma")
        curr_y += word_heights[i] + word_line_spacing
    curr_y += gap_word_to_pos

    # 4. Part-of-speech badge
    if pos_text:
        px = (width - pos_w) // 2
        draw.rectangle((px, curr_y, px + pos_w, curr_y + pos_h), fill=t["badge_bg"])
        draw.text((px + 10, curr_y + 5), pos_text, fill=t["badge_text"], font=font_pos)
        curr_y += pos_h
    curr_y += gap_pos_to_def

    # 5. Definition -- centered by default, or left-aligned under a
    # drop-cap tile when enabled.
    if drop_cap and drop_letter:
        tile_size = dropcap_reserve - 15
        draw_drop_cap_tile(
            draw, drop_letter, left_x, curr_y - dropcap_reserve + 5, tile_size,
            t["accent_color"], COLOR_WHITE,
            font_loader=lambda size: load_font(t["headline_font"], "Bold", size),
        )
    curr_y = draw_text_block(
        draw, def_lines, def_heights, def_line_spacing, font_def, t["primary_color"], width, curr_y,
        left_x=left_x if drop_cap else None,
    )
    curr_y += gap_def_to_example

    # 6. Example sentence, if present -- matches the definition's alignment
    for i, line in enumerate(example_lines):
        if drop_cap:
            draw.text((left_x, curr_y), line, fill=t["footer_color"], font=font_example, anchor="la")
        else:
            draw.text((width // 2, curr_y), line, fill=t["footer_color"], font=font_example, anchor="ma")
        curr_y += example_heights[i] + 8

    # 7. Footer Label
    draw.text(
        (width // 2, height - border_inner_margin - 30),
        "WORD OF THE DAY", fill=t["footer_color"], font=font_footer, anchor="ma"
    )

    return img

# ---------------------------------------------------------------------------
# Binary Encoding for Spectra 6
# ---------------------------------------------------------------------------
def get_closest_nibble(r: int, g: int, b: int) -> int:
    """Map any RGB value to the closest hardware-supported Spectra 6 color code."""
    min_dist = float('inf')
    best_nibble = 1  # Default to white

    for i, color in enumerate(SPECTRA6_REAL_WORLD_RGB):
        dist = (r - color[0])**2 + (g - color[1])**2 + (b - color[2])**2
        if dist < min_dist:
            min_dist = dist
            best_nibble = SPECTRA6_NIBBLE_VALUES[i]

    return best_nibble

def pack_row_half(image: Image.Image, y: int, start_x: int, end_x: int) -> bytes:
    """Pack an interval of pixels into 4-bit nibbles (2 pixels per byte)."""
    out = bytearray()
    pixels = image.load()
    width = image.width

    for x in range(start_x, end_x, 2):
        r, g, b = pixels[x, y][:3]
        high_nibble = get_closest_nibble(r, g, b)

        odd_x = x + 1
        if odd_x < end_x and odd_x < width:
            r2, g2, b2 = pixels[odd_x, y][:3]
            low_nibble = get_closest_nibble(r2, g2, b2)
        else:
            low_nibble = 1  # Pad missing pixel with White (nibble 1)

        out.append((high_nibble << 4) | low_nibble)

    return bytes(out)

def pack_split_halves(image: Image.Image) -> bytes:
    """Pack portrait/split-half display buffers (e.g. 13.3" 1200x1600):
    every row's left-half pixels first for the whole image, then every
    row's right-half pixels."""
    width, height = image.size
    half = width // 2

    left_bytes = bytearray()
    right_bytes = bytearray()

    for y in range(height):
        left_bytes.extend(pack_row_half(image, y, 0, half))
        right_bytes.extend(pack_row_half(image, y, half, width))

    return bytes(left_bytes) + bytes(right_bytes)

def pack_sequential(image: Image.Image) -> bytes:
    """Pack landscape/sequential display buffers (e.g. 7.3" 800x480)."""
    width, height = image.size
    out = bytearray()

    for y in range(height):
        out.extend(pack_row_half(image, y, 0, width))

    return bytes(out)

def encode_spectra6_bin(image: Image.Image, layout: str) -> bytes:
    """Convert rendered PIL image to the raw packed 4bpp binary format."""
    print(f"Encoding image buffer using layout: {layout}...")
    if layout == "split_half":
        return pack_split_halves(image)
    else:
        return pack_sequential(image)

# ---------------------------------------------------------------------------
# REST API Uploader
# ---------------------------------------------------------------------------
def upload_bin_to_frame(frame_ip: str, binary_bytes: bytes) -> bool:
    """Upload raw packed .bin file directly to the frame's /api/image REST API endpoint."""
    url = f"http://{frame_ip}/api/image"
    print(f"Uploading {len(binary_bytes)} bytes to frame at {url}...")

    try:
        req = urllib.request.Request(
            url,
            data=binary_bytes,
            headers={"Content-Type": "application/octet-stream"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            status = response.status
            print(f"Upload successful! Frame returned status: {status}")
            return True
    except Exception as e:
        print(f"Error during upload: {e}")
        return False

# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.json (default: config.json next to this script). "
             "The .bin/preview outputs are written next to this path too, so a "
             "caller can isolate concurrent renders in their own directories.",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Render and pack the .bin file but skip uploading it to the frame. "
             "Lets a caller read the .bin back off disk and send it through its "
             "own delivery pipeline instead.",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.abspath(args.config) if args.config else os.path.join(script_dir, "config.json")
    output_dir = os.path.dirname(config_path)

    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        print("Please copy config.example.json to config.json and adjust settings.")
        sys.exit(1)

    with open(config_path, "r") as f:
        config = json.load(f)

    frame_conf = config.get("frame", {})
    resolution = frame_conf.get("resolution", [1200, 1600])
    width, height = resolution[0], resolution[1]

    content_mode = config.get("content_mode", "quote")
    theme = config.get("theme", "classic")
    drop_cap = bool(config.get("drop_cap", False))

    if content_mode == "joke":
        joke_feed = config.get("joke_feed", "icanhazdadjoke")
        custom_jokes = config.get("custom_jokes", [])
        joke_api_url = config.get("joke_api_url")

        joke_data = fetch_joke(joke_feed, custom_jokes, joke_api_url)
        setup = joke_data.get("setup", "").strip()
        punchline = joke_data.get("punchline", "").strip()

        if not setup:
            print("Error: Could not obtain a valid joke.")
            sys.exit(1)

        print(f'Selected Joke: "{setup}"' + (f" — {punchline}" if punchline else ""))
        label = "Joke of the Day"
        print(f"Generating {label} layout ({width}x{height})...")
        img = render_joke_image(width, height, setup, punchline, theme, drop_cap)

    elif content_mode == "scripture":
        translation = config.get("bible_translation", "niv")
        custom_scriptures = config.get("custom_scriptures", [])
        source_type = config.get("scripture_source", "daily_api")
        ourmanna_url = config.get("ourmanna_api_url")
        bible_api_url = config.get("bible_api_url")

        scripture_data = fetch_scripture(translation, custom_scriptures, source_type, ourmanna_url, bible_api_url)
        quote = scripture_data.get("q", "").strip()
        ref = scripture_data.get("r", "Unknown").strip()
        ver = scripture_data.get("t", translation.upper()).strip()

        if not quote:
            print("Error: Could not obtain a valid scripture.")
            sys.exit(1)

        print(f'Selected Scripture: "{quote}" — {ref} ({ver})')
        label = "Scripture of the Day"
        print(f"Generating {label} layout ({width}x{height})...")
        img = render_scripture_image(width, height, quote, ref, ver, theme, drop_cap)

    elif content_mode == "word":
        word_feed = config.get("word_feed", "random_word")
        custom_words = config.get("custom_words", [])
        word_api_url = config.get("word_api_url")
        random_word_api_url = config.get("random_word_api_url")
        dictionary_api_url = config.get("dictionary_api_url")

        word_data = fetch_word(word_feed, custom_words, word_api_url, random_word_api_url, dictionary_api_url)
        word = word_data.get("word", "").strip()
        pos = word_data.get("pos", "").strip()
        definition = word_data.get("definition", "").strip()
        example = word_data.get("example", "").strip()

        if not word or not definition:
            print("Error: Could not obtain a valid word.")
            sys.exit(1)

        print(f'Selected Word: "{word}" ({pos}) — {definition}')
        label = "Word of the Day"
        print(f"Generating {label} layout ({width}x{height})...")
        img = render_word_image(width, height, word, pos, definition, example, theme, drop_cap)

    else:  # "quote" (default)
        quote_feed = config.get("quote_feed", "zenquotes")
        custom_quotes = config.get("custom_quotes", [])
        api_url = config.get("quote_api_url")

        quote_data = fetch_quote(quote_feed, custom_quotes, api_url)
        quote = quote_data.get("q", "").strip()
        author = quote_data.get("a", "Unknown").strip()

        if not quote:
            print("Error: Could not obtain a valid quote.")
            sys.exit(1)

        print(f'Selected Quote: "{quote}" — {author}')
        label = "Quote of the Day"
        print(f"Generating {label} layout ({width}x{height})...")
        img = render_quote_image(width, height, quote, author, theme, drop_cap)

    # Save a PNG preview alongside the config for debug/visual verification
    preview_path = os.path.join(output_dir, "xotd_preview.png")
    img.save(preview_path)
    print(f"Saved local PNG preview to {preview_path}")

    # Pack binary file
    layout_type = frame_conf.get("layout", "split_half")
    binary_bytes = encode_spectra6_bin(img, layout_type)

    # Save local bin backup
    bin_path = os.path.join(output_dir, "xotd.bin")
    with open(bin_path, "wb") as f:
        f.write(binary_bytes)
    print(f"Saved local Spectra 6 binary to {bin_path}")

    if args.render_only:
        print("--render-only set: skipping upload to frame.")
        return

    # Upload
    frame_ip = frame_conf.get("ip_address", "fraimic.local")
    success = upload_bin_to_frame(frame_ip, binary_bytes)
    if success:
        print(f"Successfully updated {label} frame!")
    else:
        print(f"Failed to upload {label.lower()} to the frame.")

if __name__ == "__main__":
    main()

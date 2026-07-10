#!/usr/bin/env python3
"""Quote of the Day Renderer & Frame Uploader.

Fetches the daily quote (via ZenQuotes API or a custom configured list),
renders it onto a premium high-contrast canvas, encodes it to the Spectra 6 4-bit
binary format, and uploads it to the Fraimic e-ink canvas frame.
"""

from __future__ import annotations

import os
import sys
import json
import random
import datetime
import urllib.request
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Constants & Color Palette
# ---------------------------------------------------------------------------
COLOR_BLACK = (0, 0, 0)         # Quote text, borders, author name
COLOR_WHITE = (255, 255, 255)   # Background canvas
COLOR_RED = (178, 19, 24)      # Decorative quote marks
COLOR_BLUE = (33, 87, 186)     # Footer label color
COLOR_YELLOW = (239, 222, 68)   # Highlight accents (unused here, reserved)
COLOR_GREEN = (18, 95, 32)     # Success/active indicators (unused here)

SPECTRA6_REAL_WORLD_RGB = (
    COLOR_BLACK,
    COLOR_WHITE,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_BLUE,
    COLOR_GREEN,
)

SPECTRA6_NIBBLE_VALUES = (0, 1, 2, 3, 5, 6)

# Premium fallback quotes in case the internet or API is unreachable
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

# ---------------------------------------------------------------------------
# Helpers: Font Loader & Text Wrapper
# ---------------------------------------------------------------------------
def load_font(font_name="Outfit", font_style="Regular", size=24) -> ImageFont.ImageFont:
    """Download standard ttf font from Google Fonts if not cached locally, else load it."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "fonts")
    os.makedirs(font_dir, exist_ok=True)
    
    style_map = {
        "Regular": "Regular",
        "Medium": "Medium",
        "SemiBold": "SemiBold",
        "Bold": "Bold"
    }
    style_suffix = style_map.get(font_style, "Regular")
    font_filename = f"Outfit-{style_suffix}.ttf"
    font_path = os.path.join(font_dir, font_filename)
    
    if not os.path.exists(font_path):
        url = f"https://raw.githubusercontent.com/Outfitio/Outfit-Fonts/main/fonts/ttf/{font_filename}"
        try:
            print(f"Downloading {font_filename} font from Google Fonts (Outfitio)...")
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
        # textbbox returns (left, top, right, bottom)
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
    text fits inside max_width x max_height, so the quote fills whatever
    room a given frame orientation leaves for it -- a short quote renders
    big, a long one shrinks only as much as it has to, and the same logic
    naturally scales across resolutions instead of picking from a fixed
    per-orientation size table. max_size is deliberately generous (a short
    quote should be allowed to grow large); the width check below is what
    actually stops it once a wrapped line would run past max_width, since
    wrap_text's own "force a too-wide single word onto its own line" escape
    hatch doesn't shrink that word to fit."""
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

    # Even the floor size overflows (an unusually long quote) -- use it
    # anyway rather than shrinking past readability.
    font = font_loader(min_size)
    lines = wrap_text(text, draw, font, max_width)
    line_spacing = max(int(min_size * line_spacing_ratio), 4)
    heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
    total = sum(heights) + line_spacing * (len(lines) - 1)
    return font, lines, heights, line_spacing, total

# ---------------------------------------------------------------------------
# Quote Fetcher
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
        req = urllib.request.Request(url, headers={"User-Agent": "FraimicQuoteAddon/1.0"})
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

# ---------------------------------------------------------------------------
# Visual Composition Renderer
# ---------------------------------------------------------------------------
def render_quote_image(width: int, height: int, quote: str, author: str) -> Image.Image:
    """Compose the quote layout with double borders, quotation marks, and footer."""
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)
    
    is_landscape = width > height

    # Structural layout (margins, decorative offsets) still differs by
    # orientation -- but quote_font_size is no longer one of these fixed
    # values. It's auto-fit below to whatever room this orientation leaves,
    # so the same short quote renders bigger on a portrait frame than on a
    # squatter landscape one, and a long quote shrinks only as needed,
    # instead of every quote sharing one static size per orientation.
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

    font_author = load_font("Outfit", "SemiBold", author_font_size)
    font_footer = load_font("Outfit", "SemiBold", footer_font_size)
    font_quote_marks = load_font("Outfit", "Bold", quote_marks_size)

    # 1. Draw borders
    # Outer
    draw.rectangle(
        (border_outer_margin, border_outer_margin, width - border_outer_margin, height - border_outer_margin),
        outline=COLOR_BLACK, width=3 if not is_landscape else 2
    )
    # Inner
    draw.rectangle(
        (border_inner_margin, border_inner_margin, width - border_inner_margin, height - border_inner_margin),
        outline=COLOR_BLACK, width=1
    )

    # 2. Auto-fit the quote's font size to the room left after reserving
    # space for the (fixed-size) opening quote mark above and the author +
    # footer band below -- this reserve is independent of max_quote_font_size
    # so raising that ceiling to let short quotes grow doesn't also shrink
    # the room being fit into.
    top_reserved = quote_marks_y_offset + quote_marks_size * 0.6
    bottom_reserved = author_y_offset + author_font_size + footer_font_size + 60
    available_height = (height - 2 * border_inner_margin) - top_reserved - bottom_reserved

    font_quote, wrapped_lines, line_heights, line_spacing, total_text_height = fit_text_to_box(
        draw, quote, wrap_width, available_height,
        font_loader=lambda size: load_font("Outfit", "Bold", size),
        max_size=max_quote_font_size, min_size=min_quote_font_size
    )

    total_block_height = total_text_height + author_y_offset + author_font_size
    start_y = (height - total_block_height) // 2

    # 3. Draw Opening Quote Mark (top-left)
    draw.text(
        (border_inner_margin + 40, start_y - quote_marks_y_offset),
        "“", fill=COLOR_RED, font=font_quote_marks
    )

    # 4. Draw Quote Lines (centered)
    current_y = start_y
    for i, line in enumerate(wrapped_lines):
        draw.text(
            (width // 2, current_y),
            line, fill=COLOR_BLACK, font=font_quote, anchor="ma"
        )
        current_y += line_heights[i] + line_spacing

    # 5. Draw Author (aligned right)
    author_y = current_y + author_y_offset
    draw.text(
        (width - (border_inner_margin + 60), author_y),
        f"— {author}", fill=COLOR_BLACK, font=font_author, anchor="ra"
    )

    # Draw Closing Quote Mark (bottom-right)
    draw.text(
        (width - (border_inner_margin + 40 + quote_marks_size // 2), author_y + author_font_size // 2),
        "”", fill=COLOR_RED, font=font_quote_marks
    )

    # 6. Draw Footer Label
    draw.text(
        (width // 2, height - border_inner_margin - 30),
        "QUOTE OF THE DAY", fill=COLOR_BLUE, font=font_footer, anchor="ma"
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
    """Pack portrait/split-half display buffers (e.g. 13.3" 1200x1600)."""
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
def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.json")
    
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found at {config_path}")
        print("Please copy config.example.json to config.json and adjust settings.")
        sys.exit(1)
        
    with open(config_path, "r") as f:
        config = json.load(f)
        
    # 1. Fetch Quote
    quote_feed = config.get("quote_feed", config.get("quote_source", "zenquotes"))
    custom_quotes = config.get("custom_quotes", [])
    api_url = config.get("quote_api_url")  # Option to override for testing
    
    quote_data = fetch_quote(quote_feed, custom_quotes, api_url)
    quote = quote_data.get("q", "").strip()
    author = quote_data.get("a", "Unknown").strip()
    
    if not quote:
        print("Error: Could not obtain a valid quote.")
        sys.exit(1)
        
    print(f'Selected Quote: "{quote}" — {author}')
    
    # 2. Render Visual Image
    frame_conf = config.get("frame", {})
    resolution = frame_conf.get("resolution", [1200, 1600])
    width, height = resolution[0], resolution[1]
    
    print(f"Generating quote layout ({width}x{height})...")
    img = render_quote_image(width, height, quote, author)
    
    # Save a PNG preview next to the script for debug/visual verification
    preview_path = os.path.join(script_dir, "quote_preview.png")
    img.save(preview_path)
    print(f"Saved local PNG preview to {preview_path}")
    
    # 3. Pack binary file
    layout_type = frame_conf.get("layout", "split_half")
    binary_bytes = encode_spectra6_bin(img, layout_type)
    
    # Save local bin backup
    bin_path = os.path.join(script_dir, "quote.bin")
    with open(bin_path, "wb") as f:
        f.write(binary_bytes)
    print(f"Saved local Spectra 6 binary to {bin_path}")
    
    # 4. Upload
    frame_ip = frame_conf.get("ip_address", "fraimic.local")
    success = upload_bin_to_frame(frame_ip, binary_bytes)
    if success:
        print("Successfully updated Quote of the Day frame!")
    else:
        print("Failed to upload quote to the frame.")

if __name__ == "__main__":
    main()

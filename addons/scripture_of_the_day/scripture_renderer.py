#!/usr/bin/env python3
"""Scripture of the Day Renderer & Frame Uploader.

Fetches the daily Bible Verse of the Day, queries the requested translation
(NIV, KJV, WEB, BBE, etc.), renders it onto a premium high-contrast canvas,
encodes it to the Spectra 6 4-bit binary format, and uploads it to the frame.
"""

from __future__ import annotations

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
COLOR_BLACK = (0, 0, 0)         # Scripture text, borders, reference
COLOR_WHITE = (255, 255, 255)   # Background canvas
COLOR_RED = (178, 19, 24)      # Decorative icons (cross/leaves)
COLOR_BLUE = (33, 87, 186)     # Translation badge
COLOR_YELLOW = (239, 222, 68)   # Accent color (unused here)
COLOR_GREEN = (18, 95, 32)     # Highlight color (unused here)

SPECTRA6_REAL_WORLD_RGB = (
    COLOR_BLACK,
    COLOR_WHITE,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_BLUE,
    COLOR_GREEN,
)

SPECTRA6_NIBBLE_VALUES = (0, 1, 2, 3, 5, 6)

# Premium fallback scriptures in case of network failures
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
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        
        if w <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
                current_line = [word]
            else:
                lines.append(word)
                current_line = []
                
    if current_line:
        lines.append(" ".join(current_line))
        
    return lines

# ---------------------------------------------------------------------------
# Scripture Fetcher
# ---------------------------------------------------------------------------
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
        req = urllib.request.Request(ourmanna_endpoint, headers={"User-Agent": "FraimicScriptureAddon/1.0"})
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
            req = urllib.request.Request(url, headers={"User-Agent": "FraimicScriptureAddon/1.0"})
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

# ---------------------------------------------------------------------------
# Visual Composition Renderer
# ---------------------------------------------------------------------------
def render_scripture_image(width: int, height: int, quote: str, reference: str, translation: str) -> Image.Image:
    """Compose the scripture layout with double borders, decorative cross emblem, and reference."""
    img = Image.new("RGB", (width, height), COLOR_WHITE)
    draw = ImageDraw.Draw(img)
    
    is_landscape = width > height
    
    if is_landscape:
        border_outer_margin = 20
        border_inner_margin = 26
        quote_font_size = 32
        ref_font_size = 22
        badge_font_size = 14
        emblem_size = 30
        wrap_width = width - 200
        line_spacing = 8
        emblem_y_offset = 35
        ref_y_offset = 25
    else:
        border_outer_margin = 40
        border_inner_margin = 50
        quote_font_size = 46
        ref_font_size = 30
        badge_font_size = 18
        emblem_size = 50
        wrap_width = width - 300
        line_spacing = 14
        emblem_y_offset = 80
        ref_y_offset = 45
        
    font_quote = load_font("Outfit", "Bold", quote_font_size)
    font_ref = load_font("Outfit", "SemiBold", ref_font_size)
    font_badge = load_font("Outfit", "Bold", badge_font_size)
    
    # 1. Draw double borders
    draw.rectangle(
        (border_outer_margin, border_outer_margin, width - border_outer_margin, height - border_outer_margin),
        outline=COLOR_BLACK, width=3 if not is_landscape else 2
    )
    draw.rectangle(
        (border_inner_margin, border_inner_margin, width - border_inner_margin, height - border_inner_margin),
        outline=COLOR_BLACK, width=1
    )
    
    # 2. Draw Decorative Emblem (Classic Cross emblem representation)
    # We draw a clean geometric representation of a decorative cross in RED at the top center
    cx = width // 2
    cy = border_inner_margin + emblem_y_offset
    
    # Cross dimensions
    v_len = emblem_size
    v_w = emblem_size // 4
    h_len = emblem_size * 2 // 3
    h_w = v_w
    
    # Vertical bar
    draw.rectangle(
        (cx - v_w // 2, cy - v_len // 3, cx + v_w // 2, cy + v_len * 2 // 3),
        fill=COLOR_RED
    )
    # Horizontal bar
    draw.rectangle(
        (cx - h_len // 2, cy - h_w // 2, cx + h_len // 2, cy + h_w // 2),
        fill=COLOR_RED
    )
    
    # 3. Word wrap the scripture text
    # Clean up double quotes and wrap
    clean_quote = quote.replace('"', '').replace('“', '').replace('”', '').strip()
    clean_quote = f"“ {clean_quote} ”"
    wrapped_lines = wrap_text(clean_quote, draw, font_quote, wrap_width)
    
    # Calculate text heights and draw
    line_heights = []
    total_text_height = 0
    for line in wrapped_lines:
        bbox = draw.textbbox((0, 0), line, font=font_quote)
        h = bbox[3] - bbox[1]
        line_heights.append(h)
        total_text_height += h
    total_text_height += line_spacing * (len(wrapped_lines) - 1)
    
    # Draw scripture centered
    start_y = cy + emblem_size + (height - border_inner_margin - (cy + emblem_size) - total_text_height - ref_y_offset - 30) // 2
    curr_y = start_y
    for i, line in enumerate(wrapped_lines):
        bbox = draw.textbbox((0, 0), line, font=font_quote)
        w = bbox[2] - bbox[0]
        x = (width - w) // 2
        draw.text((x, curr_y), line, fill=COLOR_BLACK, font=font_quote)
        curr_y += line_heights[i] + line_spacing
        
    # 4. Draw Reference
    clean_ref = reference.strip()
    bbox_ref = draw.textbbox((0, 0), clean_ref, font=font_ref)
    w_ref = bbox_ref[2] - bbox_ref[0]
    rx = (width - w_ref) // 2
    ry = curr_y + ref_y_offset
    draw.text((rx, ry), clean_ref, fill=COLOR_BLACK, font=font_ref)
    
    # 5. Draw Translation Badge in bottom right corner
    badge_text = translation.upper().strip()
    bbox_b = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = bbox_b[2] - bbox_b[0] + 16
    bh = bbox_b[3] - bbox_b[1] + 10
    bx = width - border_inner_margin - bw - 15
    by = height - border_inner_margin - bh - 15
    
    draw.rectangle((bx, by, bx + bw, by + bh), fill=COLOR_BLUE)
    draw.text((bx + 8, by + 5), badge_text, fill=COLOR_WHITE, font=font_badge)
    
    return img

# ---------------------------------------------------------------------------
# Spectra 6 Byte Packing
# ---------------------------------------------------------------------------
def encode_spectra6_bin(img: Image.Image, layout_type: str = "split_half") -> bytes:
    """Encode RGB image into Spectra 6 4-bit binary layout."""
    width, height = img.size
    pixels = img.load()
    
    # Map each pixel to nearest Spectra 6 index
    color_indices = []
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            
            # Find closest color in our palette
            min_dist = float("inf")
            best_idx = 0
            for idx, spec_rgb in enumerate(SPECTRA6_REAL_WORLD_RGB):
                dist = (r - spec_rgb[0])**2 + (g - spec_rgb[1])**2 + (b - spec_rgb[2])**2
                if dist < min_dist:
                    min_dist = dist
                    best_idx = idx
            
            # Convert palette index to physical hardware nibble value
            color_indices.append(SPECTRA6_NIBBLE_VALUES[best_idx])
            
    # Pack nibbles into bytes
    output_bytes = bytearray()
    
    if layout_type == "split_half":
        # First half of the file is even pixels (high nibbles), second half is odd pixels (low nibbles)
        num_pixels = width * height
        half_pixels = num_pixels // 2
        for i in range(half_pixels):
            even_val = color_indices[2 * i]
            odd_val = color_indices[2 * i + 1]
            packed_byte = (even_val << 4) | (odd_val & 0x0F)
            output_bytes.append(packed_byte)
    else:  # "sequential"
        # Standard sequential pixel packing
        for i in range(0, len(color_indices), 2):
            pix1 = color_indices[i]
            pix2 = color_indices[i+1] if i+1 < len(color_indices) else 0
            packed_byte = (pix1 << 4) | (pix2 & 0x0F)
            output_bytes.append(packed_byte)
            
    return bytes(output_bytes)

def upload_bin_to_frame(frame_ip: str, binary_bytes: bytes) -> bool:
    """Upload packed binary payload to Fraimic frame endpoint."""
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
        sys.exit(1)
        
    with open(config_path, "r") as f:
        config = json.load(f)
        
    # 1. Fetch Scripture
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
    
    # 2. Render Visual Image
    frame_conf = config.get("frame", {})
    resolution = frame_conf.get("resolution", [1200, 1600])
    width, height = resolution[0], resolution[1]
    
    print(f"Generating scripture layout ({width}x{height})...")
    img = render_scripture_image(width, height, quote, ref, ver)
    
    # Save a PNG preview next to the script for debug/visual verification
    preview_path = os.path.join(script_dir, "scripture_preview.png")
    img.save(preview_path)
    print(f"Saved local PNG preview to {preview_path}")
    
    # 3. Pack binary file
    layout_type = frame_conf.get("layout", "split_half")
    binary_bytes = encode_spectra6_bin(img, layout_type)
    
    # Save local bin backup
    bin_path = os.path.join(script_dir, "scripture.bin")
    with open(bin_path, "wb") as f:
        f.write(binary_bytes)
    print(f"Saved local Spectra 6 binary to {bin_path}")
    
    # 4. Upload
    frame_ip = frame_conf.get("ip_address", "fraimic.local")
    success = upload_bin_to_frame(frame_ip, binary_bytes)
    if success:
        print("Successfully updated Scripture of the Day frame!")
    else:
        print("Failed to upload scripture to the frame.")

if __name__ == "__main__":
    main()

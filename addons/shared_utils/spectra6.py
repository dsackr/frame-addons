"""Spectra 6 Palette and Encoding Utilities.

Shared utilities for converting PIL Images to raw packed 4bpp binary formats
expected by Spectra 6 e-ink hardware.
"""

from __future__ import annotations
from PIL import Image

# Exact RGB values expected by the Spectra 6 hardware to avoid dithering noise
COLOR_BLACK = (0, 0, 0)         # Primary text, timeline lines, body text
COLOR_WHITE = (255, 255, 255)   # Background canvas
COLOR_YELLOW = (239, 222, 68)   # Sun, highlights, accent background
COLOR_RED = (178, 19, 24)      # Alert icons, meetings, agenda/quote/joke accents
COLOR_BLUE = (33, 87, 186)     # Cloud outlines, rain drops, badge background
COLOR_GREEN = (18, 95, 32)     # Secondary tags, battery OK state

SPECTRA6_REAL_WORLD_RGB = (
    COLOR_BLACK,
    COLOR_WHITE,
    COLOR_YELLOW,
    COLOR_RED,
    COLOR_BLUE,
    COLOR_GREEN,
)

SPECTRA6_NIBBLE_VALUES = (0, 1, 2, 3, 5, 6)


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
    row's right-half pixels.
    """
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
    """Convert a rendered PIL Image to the raw packed 4bpp binary format."""
    print(f"Encoding image buffer using layout: {layout}...")
    if layout == "split_half":
        return pack_split_halves(image)
    else:
        return pack_sequential(image)

#!/usr/bin/env python3
"""Generate the social preview and benchmark cards with Pillow.

Usage:
    python scripts/make_assets.py
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

BG = "#0b0d10"
PANEL = "#141820"
TEXT = "#f2f3f5"
MUTED = "#9aa0a6"
ACCENT = "#ff6a00"
ACCENT_2 = "#ffb27a"
GRID = "#252b35"

FONT_BOLD = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/TTF/DejaVuSans.ttf"

FALLBACK = {
    "lightpanda-patched": {
        "cold_mean_ms": 1144,
        "warm_p50_ms": 71,
        "rss_mb": 155,
    },
    "cloak": {"cold_mean_ms": 778, "warm_p50_ms": 84, "rss_mb": 848},
    "chrome": {"cold_mean_ms": 943, "warm_p50_ms": 72, "rss_mb": 1052},
    "playwright-chromium": {
        "cold_mean_ms": 255,
        "warm_p50_ms": 67,
        "rss_mb": 572,
    },
}

LABELS = {
    "playwright-chromium": "Playwright",
    "cloak": "Cloak",
    "chrome": "Chrome",
    "lightpanda-patched": "Lightpanda",
}


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont):
    box = draw.textbbox((0, 0), text, font=f)
    return box[2] - box[0], box[3] - box[1]


def centered(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    f: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    width, height = text_size(draw, text, f)
    draw.text((xy[0] - width / 2, xy[1] - height / 2), text, font=f, fill=fill)


def load_speed() -> dict:
    path = ROOT / "out" / "speed-stable.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return FALLBACK


def social_preview() -> None:
    width, height = 1280, 640
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, width, 8), fill=ACCENT)
    draw.rectangle((0, height - 8, width, height), fill=PANEL)

    title = font(FONT_BOLD, 116)
    tagline = font(FONT_REGULAR, 34)
    metric = font(FONT_BOLD, 54)
    metric_label = font(FONT_REGULAR, 22)
    small = font(FONT_REGULAR, 17)
    chip = font(FONT_BOLD, 18)

    draw.text((72, 70), "PLAGUE", font=title, fill=TEXT)
    draw.text(
        (78, 206),
        "CloakBrowser stealth. Lightpanda speed.",
        font=tagline,
        fill=ACCENT_2,
    )
    draw.text(
        (78, 254),
        "One router. Three engines. No pretending.",
        font=tagline,
        fill=MUTED,
    )

    metrics = [
        ("71 ms", "warm p50"),
        ("155 MB", "per session"),
        ("2x", "faster on large pages"),
    ]
    x = 72
    for value, label in metrics:
        draw.rounded_rectangle(
            (x, 340, x + 350, 500), radius=18, fill=PANEL, outline=GRID, width=2
        )
        draw.text((x + 28, 366), value, font=metric, fill=TEXT)
        draw.text((x + 28, 440), label, font=metric_label, fill=MUTED)
        x += 380

    # Simple engine flow.
    flow_y = 560
    boxes = [("Lightpanda", 72), ("Cloak", 390), ("Chrome", 708)]
    for name, bx in boxes:
        draw.rounded_rectangle(
            (bx, flow_y - 26, bx + 230, flow_y + 26),
            radius=26,
            outline=GRID,
            width=2,
            fill=PANEL,
        )
        centered(draw, (bx + 115, flow_y), name, chip, TEXT)
    for ax in (310, 628):
        draw.line((ax, flow_y, ax + 64, flow_y), fill=ACCENT, width=3)
        draw.polygon(
            [(ax + 64, flow_y), (ax + 52, flow_y - 7), (ax + 52, flow_y + 7)],
            fill=ACCENT,
        )

    url = "github.com/weaion-labs/plague"
    url_width, _ = text_size(draw, url, small)
    draw.text((width - 72 - url_width, 596), url, font=small, fill=MUTED)
    site = "weaionlabs.com"
    site_width, _ = text_size(draw, site, small)
    draw.text((width - 72 - site_width, 618), site, font=small, fill=MUTED)

    image.save(ASSETS / "social-preview.png", optimize=True)


def bar_panel(
    draw: ImageDraw.ImageDraw,
    origin: tuple[int, int],
    size: tuple[int, int],
    title: str,
    rows: list[tuple[str, float]],
    max_value: float,
    bar_color: str,
    value_suffix: str = "ms",
) -> None:
    x, y = origin
    w, h = size
    title_font = font(FONT_BOLD, 24)
    label_font = font(FONT_REGULAR, 19)
    value_font = font(FONT_BOLD, 19)

    draw.text((x, y), title, font=title_font, fill=TEXT)
    top = y + 58
    row_height = 54
    label_width = 150
    bar_width = w - label_width - 110

    for index, (label, value) in enumerate(rows):
        row_y = top + index * row_height
        draw.text((x, row_y + 10), label, font=label_font, fill=MUTED)
        length = max(4, int(bar_width * value / max_value))
        draw.rounded_rectangle(
            (x + label_width, row_y + 8, x + label_width + length, row_y + 36),
            radius=8,
            fill=bar_color,
        )
        draw.text(
            (x + label_width + length + 12, row_y + 10),
            f"{value:.0f}{value_suffix}",
            font=value_font,
            fill=TEXT,
        )


def benchmark_latency() -> None:
    data = load_speed()
    order = ["playwright-chromium", "cloak", "chrome", "lightpanda-patched"]
    cold = [
        (LABELS[key], data.get(key, FALLBACK[key])["cold_mean_ms"])
        for key in order
    ]
    warm = [
        (LABELS[key], data.get(key, FALLBACK[key])["warm_p50_ms"])
        for key in order
    ]

    image = Image.new("RGB", (1280, 720), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1280, 8), fill=ACCENT)
    draw.text((56, 44), "Plague benchmarks", font=font(FONT_BOLD, 40), fill=TEXT)
    draw.text(
        (58, 98),
        "Local deterministic pages, repeat 3. Lower is better.",
        font=font(FONT_REGULAR, 21),
        fill=MUTED,
    )

    bar_panel(
        draw, (56, 170), (560, 440), "Cold fetch", cold, 1200, ACCENT
    )
    bar_panel(
        draw, (664, 170), (560, 440), "Warm p50", warm, 100, ACCENT_2
    )

    draw.text(
        (58, 660),
        "github.com/weaion-labs/plague  |  weaionlabs.com",
        font=font(FONT_REGULAR, 18),
        fill=MUTED,
    )
    image.save(ASSETS / "benchmark-latency.png", optimize=True)


def benchmark_memory() -> None:
    data = load_speed()
    order = ["playwright-chromium", "cloak", "chrome", "lightpanda-patched"]
    rows = [
        (LABELS[key], data.get(key, FALLBACK[key])["rss_mb"]) for key in order
    ]

    image = Image.new("RGB", (1100, 560), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1100, 8), fill=ACCENT)
    draw.text((56, 44), "Memory per warm session", font=font(FONT_BOLD, 40), fill=TEXT)
    draw.text(
        (58, 98),
        "One browser, one page, measured process tree RSS.",
        font=font(FONT_REGULAR, 21),
        fill=MUTED,
    )
    bar_panel(draw, (56, 170), (990, 280), "", rows, 1150, ACCENT, " MB")

    draw.text(
        (58, 500),
        "github.com/weaion-labs/plague  |  weaionlabs.com",
        font=font(FONT_REGULAR, 18),
        fill=MUTED,
    )
    image.save(ASSETS / "benchmark-memory.png", optimize=True)


if __name__ == "__main__":
    social_preview()
    benchmark_latency()
    benchmark_memory()
    print("wrote assets/social-preview.png")
    print("wrote assets/benchmark-latency.png")
    print("wrote assets/benchmark-memory.png")

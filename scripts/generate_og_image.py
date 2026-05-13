"""
generate_og_image.py — produit og-image.png (1200x630) avec la pile typographique
canonique du projet : Newsreader (display), Newsreader Italic (subtitle),
Hanken Grotesk (compteur), JetBrains Mono (eyebrow / méta).

Les TTF variables sont commités dans assets/fonts/.
Régénérer après tout changement du compteur de cas.

Usage : python scripts/generate_og_image.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
CASES_PATH = ROOT / "data" / "cases.json"
OUT_PATH = ROOT / "og-image.png"

W, H = 1200, 630
PAPER = (243, 237, 226)
INK = (13, 12, 10)
INK_SOFT = (58, 54, 49)
INK_FAINT = (117, 110, 98)
DEATH = (42, 8, 8)


def load_font(filename: str, size: int, axes: dict | None = None) -> ImageFont.FreeTypeFont:
    """Load a variable TTF and pin axis values if provided."""
    path = FONTS / filename
    font = ImageFont.truetype(str(path), size)
    if axes:
        try:
            font.set_variation_by_axes(list(axes.values()))
        except Exception:
            pass
    return font


def read_counters() -> tuple[int, int]:
    data = json.loads(CASES_PATH.read_text())
    cases = data.get("cases", [])
    confirmed = sum(c.get("count", 1) for c in cases if c.get("type") == "confirmed")
    deaths = sum(c.get("count", 1) for c in cases if c.get("type") == "death")
    return confirmed, deaths


def main() -> int:
    confirmed, deaths = read_counters()

    title_font = load_font("Newsreader.ttf", 132, {"opsz": 72, "wght": 700})
    italic_font = load_font("Newsreader-Italic.ttf", 36, {"opsz": 36, "wght": 400})
    mono_eyebrow = load_font("JetBrainsMono.ttf", 20, {"wght": 500})
    mono_stamp = load_font("JetBrainsMono.ttf", 18, {"wght": 500})
    mono_label = load_font("JetBrainsMono.ttf", 20, {"wght": 400})
    mono_footer = load_font("JetBrainsMono.ttf", 18, {"wght": 400})
    count_big = load_font("HankenGrotesk.ttf", 140, {"wght": 700})
    count_md = load_font("HankenGrotesk.ttf", 60, {"wght": 700})

    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)

    # Double rule top
    draw.line([(60, 50), (W - 60, 50)], fill=INK, width=2)
    draw.line([(60, 56), (W - 60, 56)], fill=INK, width=1)

    # Eyebrow
    draw.text((60, 80), "TRACKER MONDIAL INDÉPENDANT  ·  MAI 2026", font=mono_eyebrow, fill=INK_FAINT)

    # Stamp top right
    stamp_text = "BROADSHEET TRACKER"
    tw = draw.textlength(stamp_text, font=mono_stamp)
    pad_x, pad_y = 18, 10
    stamp_w = tw + 2 * pad_x
    stamp_x2 = W - 60
    stamp_x1 = stamp_x2 - stamp_w
    draw.rectangle([(stamp_x1, 75), (stamp_x2, 75 + 18 + pad_y * 2)], fill=INK)
    draw.text((stamp_x1 + pad_x, 75 + pad_y), stamp_text, font=mono_stamp, fill=PAPER)

    # Title
    draw.text((60, 130), "Hantavirus", font=title_font, fill=INK)

    # Italic subtitle
    draw.text((62, 300), "Tracker mondial : cas, actualités et factchecks", font=italic_font, fill=INK_SOFT)

    # Big counter (confirmed)
    draw.text((60, 380), str(confirmed), font=count_big, fill=INK)
    draw.text((180, 430), "CAS CONFIRMÉS", font=mono_label, fill=INK_FAINT)
    draw.text((180, 460), "DANS LE MONDE", font=mono_label, fill=INK_FAINT)

    # Smaller counter (deaths)
    draw.text((400, 430), str(deaths), font=count_md, fill=DEATH)
    draw.text((460, 460), "DÉCÈS À BORD", font=mono_label, fill=INK_FAINT)

    # Bottom rule + footer line
    draw.line([(60, H - 90), (W - 60, H - 90)], fill=INK, width=1)
    draw.line([(60, H - 84), (W - 60, H - 84)], fill=INK, width=2)
    draw.text((60, H - 65), "krwz00.github.io/hantavirus-tracker", font=mono_footer, fill=INK_SOFT)

    right_label = "Sourcé  ·  Bilingue  ·  Mis à jour /h"
    rl_w = draw.textlength(right_label, font=mono_footer)
    draw.text((W - 60 - rl_w, H - 65), right_label, font=mono_footer, fill=INK_SOFT)

    img.save(OUT_PATH, "PNG", optimize=True)
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({OUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

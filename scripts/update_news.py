"""
update_news.py — aggregates the latest hantavirus-related news from official RSS feeds.

Run by GitHub Actions every hour (see .github/workflows/update.yml).
Reads from public RSS endpoints, filters on keywords, writes data/news.json.

Dependencies: feedparser, requests, python-dateutil (see scripts/requirements.txt).

Environment variables: none. This script only reads public RSS.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import feedparser
from dateutil import parser as dateparser

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

KEYWORDS = ("hantavirus", "hondius", "andes virus", "virus des andes")

# Official sources to monitor. Add/remove as needed.
# `tag` controls the colored pill in the UI (gov, who, ship, research, alert, media).
FEEDS = [
    {
        "name": "OMS — Disease Outbreak News",
        "name_en": "WHO — Disease Outbreak News",
        "url": "https://www.who.int/feeds/entity/csr/don/en/rss.xml",
        "tag": "who",
    },
    {
        "name": "ECDC — News & Events",
        "name_en": "ECDC — News & Events",
        "url": "https://www.ecdc.europa.eu/en/taxonomy/term/4926/feed",
        "tag": "who",
    },
    {
        "name": "Santé publique France",
        "name_en": "Santé publique France",
        "url": "https://www.santepubliquefrance.fr/content/rss/actualites",
        "tag": "gov",
    },
    {
        "name": "info.gouv.fr",
        "name_en": "info.gouv.fr",
        "url": "https://www.info.gouv.fr/rss/actualites.xml",
        "tag": "gov",
    },
    {
        "name": "ANRS Maladies infectieuses émergentes",
        "name_en": "ANRS Emerging Infectious Diseases",
        "url": "https://anrs.fr/feed/",
        "tag": "research",
    },
    {
        "name": "Institut Pasteur",
        "name_en": "Institut Pasteur",
        "url": "https://www.pasteur.fr/fr/rss.xml",
        "tag": "research",
    },
    # Add more here. Reuters Health, AFP Factuel, Le Monde Santé all have RSS too.
]

MAX_ITEMS = 30
TRUNCATE_BODY = 320  # characters

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "news.json"

MONTHS_FR = ("", "janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre")

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def matches_keywords(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS)


def strip_html(s: str) -> str:
    """Crude HTML stripper for RSS summary fields."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def truncate(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    return s[: n - 1].rsplit(" ", 1)[0] + "…"


def parse_date(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return dateparser.parse(raw)
    except (ValueError, TypeError):
        return None


def format_date_fr(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_FR[dt.month]} {dt.year}"


def stable_id(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return f"feed-{h[:10]}"


def fetch_feed(feed: dict) -> Iterable[dict]:
    parsed = feedparser.parse(feed["url"])
    if parsed.bozo:
        print(f"  [warn] {feed['name']}: parse warning ({parsed.bozo_exception})", file=sys.stderr)

    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        link = entry.get("link", "")

        # Filter on keywords (title OR summary)
        if not (matches_keywords(title) or matches_keywords(summary)):
            continue

        dt = parse_date(entry.get("published") or entry.get("updated"))
        iso_date = dt.isoformat() if dt else ""
        date_label = format_date_fr(dt) if dt else ""

        yield {
            "id": stable_id(feed["name"], link or title),
            "date": iso_date,
            "date_label": date_label,
            "tag": feed["tag"],
            "title": title,
            "title_en": title,  # source feeds are bilingual or single-language; English-language feeds will pass through
            "body": truncate(summary, TRUNCATE_BODY),
            "body_en": truncate(summary, TRUNCATE_BODY),
            "source": feed["name"],
            "source_url": link,
        }


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main() -> int:
    print(f"Aggregating hantavirus news from {len(FEEDS)} feeds")
    items: list[dict] = []

    for feed in FEEDS:
        try:
            count_before = len(items)
            items.extend(fetch_feed(feed))
            count_added = len(items) - count_before
            print(f"  + {feed['name']}: {count_added} matching item(s)")
        except Exception as exc:  # noqa: BLE001 — log and continue
            print(f"  ! {feed['name']}: error — {exc}", file=sys.stderr)

    # Deduplicate by URL (some items may appear in multiple feeds)
    seen = set()
    deduped = []
    for it in items:
        key = it["source_url"] or it["id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    # Sort by date descending; fall back to today for items without a parseable date
    deduped.sort(key=lambda x: x["date"] or "0000", reverse=True)
    deduped = deduped[:MAX_ITEMS]

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": deduped,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(deduped)} items to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

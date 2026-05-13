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

KEYWORDS = ("hantavirus", "hondius", "andes virus", "virus des andes", "hantaan")

# Official sources to monitor. Add/remove as needed.
# `tag` controls the colored pill in the UI (gov, who, ship, research, alert, media).
FEEDS = [
    # =====================================================================
    # FILET DE SÉCURITÉ — Google News
    # Captures toute mention "hantavirus" dans la presse mondiale, indépendamment
    # des flux individuels qui peuvent casser. Très large, possiblement bruité,
    # mais garantit qu'on ne rate rien tant que le mot-clé apparaît dans un titre.
    # =====================================================================
    {"name": "Google Actualités (FR)", "url": "https://news.google.com/rss/search?q=hantavirus&hl=fr&gl=FR&ceid=FR:fr", "tag": "media"},
    {"name": "Google News (EN)", "url": "https://news.google.com/rss/search?q=hantavirus&hl=en&gl=US&ceid=US:en", "tag": "media"},

    # =====================================================================
    # INSTITUTIONNEL — agences sanitaires et organismes de recherche
    # =====================================================================
    {"name": "OMS — News", "url": "https://www.who.int/rss-feeds/news-english.xml", "tag": "who"},
    {"name": "ECDC — News & press releases", "url": "https://www.ecdc.europa.eu/en/taxonomy/term/1307/feed", "tag": "who"},
    {"name": "ECDC — Communicable disease threats report", "url": "https://www.ecdc.europa.eu/en/taxonomy/term/1505/feed", "tag": "who"},
    {"name": "Santé publique France", "url": "https://www.santepubliquefrance.fr/rss.xml", "tag": "gov"},
    {"name": "ANRS Maladies infectieuses émergentes", "url": "https://anrs.fr/feed/", "tag": "research"},
    {"name": "Inserm", "url": "https://www.inserm.fr/feed/", "tag": "research"},

    # =====================================================================
    # PRESSE INTERNATIONALE ANGLOPHONE
    # =====================================================================
    {"name": "BBC News — Health", "url": "https://feeds.bbci.co.uk/news/health/rss.xml", "tag": "media"},
    {"name": "BBC News — World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "tag": "media"},
    {"name": "BBC News — Science & Environment", "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "tag": "media"},
    {"name": "The Guardian — World", "url": "https://www.theguardian.com/world/rss", "tag": "media"},
    {"name": "The Guardian — Health", "url": "https://www.theguardian.com/society/health/rss", "tag": "media"},
    {"name": "The New York Times — Health", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Health.xml", "tag": "media"},
    {"name": "The New York Times — Science", "url": "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml", "tag": "media"},
    {"name": "Al Jazeera English", "url": "https://www.aljazeera.com/xml/rss/all.xml", "tag": "media"},
    {"name": "Deutsche Welle — World", "url": "https://rss.dw.com/rdf/rss-en-world", "tag": "media"},
    {"name": "France 24 — International", "url": "https://www.france24.com/en/rss", "tag": "media"},

    # =====================================================================
    # PRESSE FRANÇAISE
    # =====================================================================
    {"name": "Le Monde — Sciences", "url": "https://www.lemonde.fr/sciences/rss_full.xml", "tag": "media"},
    {"name": "Le Monde — Planète", "url": "https://www.lemonde.fr/planete/rss_full.xml", "tag": "media"},
    {"name": "France Info — Santé", "url": "https://www.francetvinfo.fr/sante.rss", "tag": "media"},
    {"name": "Sciences et Avenir — Santé", "url": "https://www.sciencesetavenir.fr/sante/rss.xml", "tag": "media"},
    {"name": "Le Quotidien du Médecin", "url": "https://www.lequotidiendumedecin.fr/rss.xml", "tag": "media"},
    {"name": "Radio France — France Inter", "url": "https://radiofrance.fr/franceinter/rss", "tag": "media"},
    {"name": "Libération", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/?outputType=xml", "tag": "media"},

    # =====================================================================
    # SCIENCE & SANTÉ SPÉCIALISÉES
    # =====================================================================
    {"name": "STAT News", "url": "https://www.statnews.com/feed/", "tag": "research"},
    {"name": "Nature — News", "url": "https://www.nature.com/nature.rss", "tag": "research"},
    {"name": "Science Magazine", "url": "https://www.science.org/rss/news_current.xml", "tag": "research"},
    {"name": "The Lancet", "url": "https://www.thelancet.com/rssfeed/lancet_current.xml", "tag": "research"},

    # =====================================================================
    # AJOUTE / RETIRE DES SOURCES ICI
    # =====================================================================
    # Format : {"name": "…", "url": "https://…/rss.xml", "tag": "media"}
    # Tags disponibles : who, gov, ship, research, alert, media
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
        dt = dateparser.parse(raw)
    except (ValueError, TypeError):
        return None
    # Clamp obviously-broken future dates to "now" so they don't float to the
    # top of the feed when a publisher misformats pubDate.
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt > now:
        return now
    return dt


def sort_key(item: dict) -> str:
    """Sort key for descending date sort. Items without a parseable date
    fall to the bottom (empty string sorts smallest, then reversed -> last)."""
    return item.get("date") or ""


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
            "manual": False,
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


def load_existing_manual() -> list[dict]:
    """Load existing news.json and return only items marked manual: true.

    This preserves the curated seed entries (initial Hondius timeline)
    across runs, even if the RSS feeds remontent rien.
    """
    if not OUTPUT_PATH.exists():
        return []
    try:
        data = json.loads(OUTPUT_PATH.read_text())
    except json.JSONDecodeError:
        return []
    return [it for it in data.get("items", []) if it.get("manual")]


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

    # Preserve curated seed entries (manual: true) from previous run
    manual = load_existing_manual()
    print(f"Preserving {len(manual)} manual entry(ies); adding {len(deduped)} auto-detected")

    # Sort the full merged list by date desc. Manual + auto are interleaved
    # purely by recency so a 12 May article never sits below an 8 May one.
    # Items without a parseable date fall to the bottom.
    all_items = manual + deduped
    all_items.sort(key=sort_key, reverse=True)
    all_items = all_items[:MAX_ITEMS]

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": all_items,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(all_items)} items to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

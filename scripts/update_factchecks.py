"""
update_factchecks.py — aggregates fact-check articles about hantavirus from
international newspapers' fact-checking sections.

Same architecture as update_news.py, just with a different source list and a
different output file. No LLM call: we trust professional fact-checkers to
have already done the verification work.

Run by GitHub Actions every hour (see .github/workflows/update.yml).
Reads from public RSS endpoints, filters on keywords, writes data/factchecks.json.

Dependencies: feedparser, python-dateutil.
Environment: none required (no API keys).
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

# Professional fact-checking units, organized by language. Add/remove as you wish.
FACTCHECK_SOURCES = [
    # =====================================================================
    # FRANCOPHONE
    # =====================================================================
    {"name": "AFP Factuel", "url": "https://factuel.afp.com/list/all/feed", "tag": "alert"},
    {"name": "Libération — CheckNews", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/category/checknews/?outputType=xml", "tag": "alert"},
    {"name": "Le Monde — Les Décodeurs", "url": "https://www.lemonde.fr/les-decodeurs/rss_full.xml", "tag": "alert"},
    {"name": "20 Minutes — Fake Off", "url": "https://www.20minutes.fr/feeds/rss-fake-off.xml", "tag": "alert"},

    # =====================================================================
    # ANGLOPHONE
    # =====================================================================
    {"name": "PolitiFact", "url": "https://www.politifact.com/rss/factchecks/", "tag": "alert"},
    {"name": "FactCheck.org", "url": "https://www.factcheck.org/feed/", "tag": "alert"},
    {"name": "Snopes", "url": "https://www.snopes.com/feed/", "tag": "alert"},
    {"name": "Full Fact (UK)", "url": "https://fullfact.org/feed/", "tag": "alert"},
    {"name": "Lead Stories", "url": "https://leadstories.com/atom.xml", "tag": "alert"},

    # =====================================================================
    # HISPANOPHONE
    # =====================================================================
    {"name": "Maldita.es", "url": "https://www.maldita.es/feed/", "tag": "alert"},
    {"name": "Newtral", "url": "https://www.newtral.es/feed", "tag": "alert"},
    {"name": "Chequeado (Argentine)", "url": "https://chequeado.com/feed/", "tag": "alert"},

    # =====================================================================
    # GERMANOPHONE
    # =====================================================================
    {"name": "Correctiv (Allemagne)", "url": "https://correctiv.org/feed/", "tag": "alert"},

    # =====================================================================
    # LUSOPHONE
    # =====================================================================
    {"name": "Aos Fatos (Brésil)", "url": "https://www.aosfatos.org/noticias/feed/", "tag": "alert"},

    # =====================================================================
    # AJOUTE / RETIRE DES SOURCES ICI
    # =====================================================================
]

MAX_ITEMS = 30
TRUNCATE_BODY = 320  # characters

OUTPUT_PATH = Path(__file__).parent.parent / "data" / "factchecks.json"

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
    # Clamp future-dated items (typically broken pubDate fields) to "now" so
    # they don't artificially float to the top of the list.
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
    return f"fc-{h[:10]}"


def fetch_feed(feed: dict) -> Iterable[dict]:
    parsed = feedparser.parse(feed["url"])
    if parsed.bozo:
        print(f"  [warn] {feed['name']}: parse warning ({parsed.bozo_exception})", file=sys.stderr)

    for entry in parsed.entries:
        title = entry.get("title", "").strip()
        summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
        link = entry.get("link", "")

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
            "title_en": title,
            "body": truncate(summary, TRUNCATE_BODY),
            "body_en": truncate(summary, TRUNCATE_BODY),
            "source": feed["name"],
            "source_url": link,
        }


def load_existing_manual() -> list[dict]:
    """Preserve curated seed entries (manual: true) across runs."""
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
    print(f"Aggregating hantavirus fact-checks from {len(FACTCHECK_SOURCES)} sources")
    items: list[dict] = []

    for source in FACTCHECK_SOURCES:
        try:
            count_before = len(items)
            items.extend(fetch_feed(source))
            count_added = len(items) - count_before
            print(f"  + {source['name']}: {count_added} matching item(s)")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {source['name']}: error — {exc}", file=sys.stderr)

    # Dedupe by source URL
    seen = set()
    deduped = []
    for it in items:
        key = it["source_url"] or it["id"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    manual = load_existing_manual()
    print(f"Preserving {len(manual)} manual entry(ies); adding {len(deduped)} auto-detected")

    # Sort the full merged list by date desc so manual + auto entries are
    # interleaved purely by recency. Items without a parseable date fall last.
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

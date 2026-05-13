"""
test_feeds.py — diagnostic local des flux RSS.

Parse tous les flux configurés dans update_news.py (FEEDS) et update_factchecks.py
(FACTCHECK_SOURCES), affiche un rapport tabulé sans rien écrire dans data/.

Usage :
    python scripts/test_feeds.py
    python scripts/test_feeds.py --news        # uniquement les flux news
    python scripts/test_feeds.py --factchecks  # uniquement les flux factcheck
    python scripts/test_feeds.py --json        # sortie JSON brute

Dépendances : feedparser (et requests pour la vérif HTTP HEAD).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import feedparser  # noqa: E402

from update_news import FEEDS as NEWS_FEEDS, KEYWORDS as NEWS_KEYWORDS  # noqa: E402
from update_factchecks import (  # noqa: E402
    FACTCHECK_SOURCES,
    KEYWORDS as FC_KEYWORDS,
)


HTTP_TIMEOUT = 10
UA = "Mozilla/5.0 (compatible; HantavirusTrackerDiag/1.0)"


def http_status(url: str) -> tuple[str, str]:
    """Return (status_code, content_type). Best effort, never raises."""
    try:
        req = Request(url, headers={"User-Agent": UA})
        # HEAD often gets blocked → use GET with stream-like cancel.
        with urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return str(getattr(r, "status", r.getcode())), r.headers.get("Content-Type", "")
    except HTTPError as e:
        return str(e.code), ""
    except URLError as e:
        return f"ERR({e.reason})", ""
    except Exception as e:  # noqa: BLE001
        return f"ERR({type(e).__name__})", ""


def matches(text: str, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in keywords)


def probe_feed(name: str, url: str, keywords: tuple[str, ...]) -> dict:
    t0 = time.monotonic()
    status, ctype = http_status(url)
    parsed = feedparser.parse(url)
    entries = parsed.entries or []
    matching = 0
    for e in entries:
        title = e.get("title", "") or ""
        summary = e.get("summary", "") or e.get("description", "") or ""
        if matches(title, keywords) or matches(summary, keywords):
            matching += 1
    return {
        "name": name,
        "url": url,
        "http_status": status,
        "content_type": ctype.split(";")[0].strip() if ctype else "",
        "parse_ok": not parsed.bozo,
        "bozo_reason": str(parsed.bozo_exception)[:80] if parsed.bozo else "",
        "entries": len(entries),
        "matching": matching,
        "elapsed_s": round(time.monotonic() - t0, 2),
    }


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no feeds)")
        return
    name_w = min(40, max(len(r["name"]) for r in rows))
    host_w = min(38, max(len(urlsplit(r["url"]).netloc) for r in rows))
    header = (
        f"{'SOURCE'.ljust(name_w)}  "
        f"{'HOST'.ljust(host_w)}  "
        f"{'HTTP'.ljust(8)}  "
        f"{'PARSE'.ljust(7)}  "
        f"{'ENTRIES'.rjust(7)}  "
        f"{'MATCH'.rjust(5)}  "
        f"{'T(s)'.rjust(5)}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        host = urlsplit(r["url"]).netloc
        parse = "OK" if r["parse_ok"] else "warn"
        line = (
            f"{truncate(r['name'], name_w).ljust(name_w)}  "
            f"{truncate(host, host_w).ljust(host_w)}  "
            f"{r['http_status'].ljust(8)}  "
            f"{parse.ljust(7)}  "
            f"{str(r['entries']).rjust(7)}  "
            f"{str(r['matching']).rjust(5)}  "
            f"{str(r['elapsed_s']).rjust(5)}"
        )
        print(line)
        if r.get("bozo_reason") and r["entries"] == 0:
            print(f"    └─ {r['bozo_reason']}")


def summarize(rows: list[dict], label: str) -> None:
    total = len(rows)
    parse_ok = sum(1 for r in rows if r["parse_ok"])
    http_ok = sum(1 for r in rows if r["http_status"].startswith("2"))
    with_entries = sum(1 for r in rows if r["entries"] > 0)
    with_match = sum(1 for r in rows if r["matching"] > 0)
    total_matching = sum(r["matching"] for r in rows)
    print()
    print(f"== {label} ==")
    print(f"  Sources         : {total}")
    print(f"  HTTP 2xx        : {http_ok}/{total}")
    print(f"  Parse propre    : {parse_ok}/{total}")
    print(f"  Avec entries    : {with_entries}/{total}")
    print(f"  Avec match kw   : {with_match}/{total}")
    print(f"  Articles trouvés: {total_matching}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--news", action="store_true", help="Tester uniquement les flux news")
    ap.add_argument("--factchecks", action="store_true", help="Tester uniquement les flux factchecks")
    ap.add_argument("--json", action="store_true", help="Sortie JSON brute")
    args = ap.parse_args()

    run_news = args.news or not args.factchecks
    run_fc = args.factchecks or not args.news

    news_rows: list[dict] = []
    fc_rows: list[dict] = []

    if run_news:
        for feed in NEWS_FEEDS:
            news_rows.append(probe_feed(feed["name"], feed["url"], NEWS_KEYWORDS))
    if run_fc:
        for feed in FACTCHECK_SOURCES:
            fc_rows.append(probe_feed(feed["name"], feed["url"], FC_KEYWORDS))

    if args.json:
        print(json.dumps({"news": news_rows, "factchecks": fc_rows}, ensure_ascii=False, indent=2))
        return 0

    if run_news:
        print("=" * 80)
        print("NEWS")
        print("=" * 80)
        print_table(news_rows)
        summarize(news_rows, "NEWS")

    if run_fc:
        print()
        print("=" * 80)
        print("FACTCHECKS")
        print("=" * 80)
        print_table(fc_rows)
        summarize(fc_rows, "FACTCHECKS")

    return 0


if __name__ == "__main__":
    sys.exit(main())

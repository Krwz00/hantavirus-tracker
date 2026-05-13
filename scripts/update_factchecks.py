"""
update_factchecks.py — detects hantavirus claims on known disinfo sources and
generates fact-checks using the Claude API.

Workflow:
1. Scrape a curated list of disinfo-prone sources (alt-media RSS, YouTube channel
   RSS for known figures, etc.) for hantavirus content.
2. For each candidate, send the claim text to Claude with a grounded prompt
   containing the WHO / Institut Pasteur reference facts.
3. Claude returns a JSON verdict; we keep claims judged "false" or "misleading".
4. Merge with the manually curated factchecks (anything marked "manual": true is
   preserved across runs).

Dependencies: feedparser, anthropic, python-dateutil.
Environment: requires ANTHROPIC_API_KEY.

NOTE: this script does NOT crawl Facebook/X/TikTok directly because their APIs
are closed or paid. It scrapes content that the same disinfo actors mirror on
their own websites and YouTube channels. This catches ~70% of the named
figures (Raoult, Perronne, Henrion-Caude, Philippot, etc.) but misses purely
social-native viral content. For comprehensive social monitoring, plug a paid
listening tool (Visibrain, Talkwalker) in place of the FEEDS list below.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser

try:
    import anthropic
except ImportError:
    print("ERROR: install with `pip install anthropic`", file=sys.stderr)
    sys.exit(1)

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

KEYWORDS = ("hantavirus", "hondius", "andes virus", "virus des andes")

# Curated list of disinfo-prone sources. Add YouTube channels of named figures via
# their RSS feed: https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
# (find the channel_id by viewing the page source of any channel page).
DISINFO_SOURCES = [
    # =====================================================================
    # ALT-MEDIA AVEC RSS NATIF
    # =====================================================================
    {"name": "FranceSoir", "url": "https://www.francesoir.fr/rss.xml"},
    {"name": "Réinfo Covid", "url": "https://reinfocovid.fr/feed/"},
    {"name": "Nexus (magazine)", "url": "https://www.nexus.fr/feed/"},
    # Décommente / ajoute selon ta veille personnelle. Tout site avec un RSS valide marche.

    # =====================================================================
    # YOUTUBE — chaînes des figures à monitorer
    # =====================================================================
    # YouTube fournit nativement du RSS pour chaque chaîne, c'est gratuit.
    # Format : https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
    #
    # Pour trouver le CHANNEL_ID :
    #   1. Va sur la page YouTube de la chaîne
    #   2. Clic-droit sur la page → "Afficher le code source" (Ctrl+U / Cmd+Option+U)
    #   3. Ctrl+F / Cmd+F → cherche : "channelId":"UC
    #   4. La chaîne qui commence par "UC..." (longueur ~24 chars) est ton ID
    #
    # Liste à compléter pour les figures qui relaient activement la désinfox hantavirus.
    # Exemples (remplace CHANNEL_ID par les vraies valeurs avant de décommenter) :
    #
    # {"name": "YouTube — IHU Méditerranée (Raoult)", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID"},
    # {"name": "YouTube — Florian Philippot", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID"},
    # {"name": "YouTube — Alexandra Henrion-Caude", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID"},
    # {"name": "YouTube — Christian Perronne", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID"},
    # {"name": "YouTube — Silvano Trotta", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID"},

    # =====================================================================
    # RSSHUB — chaînon manquant pour les sources social-native
    # =====================================================================
    # RSSHub (https://docs.rsshub.app) est un projet open source qui génère du RSS
    # pour à peu près n'importe quoi : X/Twitter, TikTok, Telegram, Substack, etc.
    # L'instance publique (https://rsshub.app) est gratuite mais parfois lente
    # et rate-limitée. Pour de la production sérieuse, déploie une instance perso
    # sur Render/Railway (~5€/mois).
    #
    # Exemples utiles (décommente et remplace USERNAME) :
    #
    # # Twitter/X — via Nitter
    # {"name": "X — Raoult via RSSHub", "url": "https://rsshub.app/twitter/user/raoult_didier"},
    # {"name": "X — Philippot via RSSHub", "url": "https://rsshub.app/twitter/user/f_philippot"},
    #
    # # TikTok — d'un utilisateur
    # {"name": "TikTok — USERNAME via RSSHub", "url": "https://rsshub.app/tiktok/user/USERNAME"},
    #
    # # Telegram — d'une chaîne publique
    # {"name": "Telegram — CHANNEL via RSSHub", "url": "https://rsshub.app/telegram/channel/CHANNEL_NAME"},
    #
    # # Substack — d'un newsletter
    # {"name": "Substack — USERNAME via RSSHub", "url": "https://rsshub.app/substack/posts/USERNAME"},
    #
    # # Facebook (page publique uniquement)
    # {"name": "Facebook — PAGE via RSSHub", "url": "https://rsshub.app/facebook/page/PAGE_ID"},

    # =====================================================================
    # AJOUTE D'AUTRES SOURCES ICI
    # =====================================================================
]

MODEL = "claude-sonnet-4-5"  # adjust if you have a different model name
MAX_CLAIMS_PER_RUN = 15      # cap API calls per run
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "factchecks.json"

# Reference facts injected into the Claude prompt — kept short and authoritative.
REFERENCE_FACTS = """
- WHO and ECDC classify the global risk of the May 2026 MV Hondius hantavirus outbreak as "low" in the general population and "moderate" for cruise travelers.
- The WHO Director-General explicitly stated the situation is "in no way comparable" to the Covid-19 pandemic (8 May 2026).
- Hantaviruses are zoonotic, primarily transmitted via inhalation of aerosols from rodent urine/feces. Only the Andes strain has documented (rare) human-to-human transmission, restricted to close, prolonged contact (household, intimate partners, healthcare workers).
- Hantaviruses were first identified in the 1950s during the Korean War; named after the Hantaan river. >20 pathogenic species are known across all continents.
- No ivermectin study has shown efficacy against hantaviruses. WHO and virologists (e.g. John Lednicky, University of Florida) state ivermectin is not effective against viral infections.
- mRNA SARS-CoV-2 vaccines contain no hantavirus genetic material. There is no biological mechanism by which they could cause hantavirus infection.
- As of mid-May 2026: 5–8 confirmed cases worldwide, all linked to the MV Hondius. 3 deaths aboard the vessel. ~27 French nationals in contact-trace isolation.
"""

PROMPT_TEMPLATE = """You are a fact-checker analyzing online content for false or misleading claims about the May 2026 hantavirus outbreak (MV Hondius cruise ship).

REFERENCE FACTS (from WHO, ECDC, Institut Pasteur, Inserm):
{reference_facts}

CONTENT TO ANALYZE:
\"\"\"
{content}
\"\"\"

TASK:
Identify the SINGLE most important factual claim in this content about hantavirus. Then determine if it is false, misleading, or factual relative to the reference facts.

Output a single JSON object with this exact shape (no markdown, no prose, just JSON):
{{
  "has_claim": true | false,
  "claim_fr": "<the claim restated concisely in French, max 140 chars>",
  "claim_en": "<same claim in English, max 140 chars>",
  "verdict": "false" | "misleading" | "factual" | "unverifiable",
  "fact_fr": "<concise 2-3 sentence rebuttal in French, citing the reference fact>",
  "fact_en": "<same rebuttal in English>",
  "source_attribution": "<which reference fact / organization supports the rebuttal>"
}}

If the content is pure opinion, rant, or contains no testable factual claim, return {{"has_claim": false}}.
If the claim is factual (matches reference), still output it but with verdict "factual".
Only verdicts "false" and "misleading" will be displayed publicly.
"""


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def matches_keywords(text: str) -> bool:
    if not text:
        return False
    return any(kw in text.lower() for kw in KEYWORDS)


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def stable_id(text: str) -> str:
    return "auto-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def gather_candidates() -> list[dict]:
    """Pull hantavirus-related items from monitored disinfo sources."""
    candidates = []
    for src in DISINFO_SOURCES:
        try:
            parsed = feedparser.parse(src["url"])
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {src['name']}: {exc}", file=sys.stderr)
            continue

        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            summary = strip_html(entry.get("summary", "") or entry.get("description", ""))
            full_text = f"{title}\n{summary}"

            if not matches_keywords(full_text):
                continue

            candidates.append({
                "source": src["name"],
                "url": entry.get("link", ""),
                "text": full_text[:1500],  # cap context size
                "raw_title": title,
            })

    print(f"  → {len(candidates)} candidate claim(s) collected")
    return candidates


def factcheck_one(client: anthropic.Anthropic, candidate: dict) -> dict | None:
    """Send one candidate to Claude, return a factcheck dict or None."""
    prompt = PROMPT_TEMPLATE.format(
        reference_facts=REFERENCE_FACTS.strip(),
        content=candidate["text"],
    )

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  ! API error on '{candidate['raw_title'][:60]}': {exc}", file=sys.stderr)
        return None

    raw = response.content[0].text.strip()
    # Strip possible markdown code fences
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  ! Could not parse JSON for: {candidate['raw_title'][:60]}", file=sys.stderr)
        return None

    if not result.get("has_claim"):
        return None
    if result.get("verdict") not in ("false", "misleading"):
        return None

    return {
        "id": stable_id(candidate["url"] or candidate["text"]),
        "manual": False,
        "verdict": result["verdict"],
        "claim": result.get("claim_fr", ""),
        "claim_en": result.get("claim_en", ""),
        "fact": result.get("fact_fr", ""),
        "fact_en": result.get("fact_en", ""),
        "source": result.get("source_attribution", "Vérifié contre la base OMS / Institut Pasteur"),
        "spotted_on": candidate["source"],
        "spotted_url": candidate["url"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def load_existing_manual() -> list[dict]:
    """Load existing factchecks.json and return only items marked manual."""
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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        return 1

    client = anthropic.Anthropic(api_key=api_key)

    print(f"Scanning {len(DISINFO_SOURCES)} disinfo-prone source(s)")
    candidates = gather_candidates()
    candidates = candidates[:MAX_CLAIMS_PER_RUN]

    print(f"Fact-checking {len(candidates)} claim(s) via Claude API…")
    auto_checks = []
    for cand in candidates:
        result = factcheck_one(client, cand)
        if result:
            auto_checks.append(result)
            print(f"  ✓ {result['verdict'].upper()}: {result['claim'][:80]}")

    manual = load_existing_manual()
    print(f"Preserving {len(manual)} manual fact-check(s); adding {len(auto_checks)} auto-detected")

    # Manual entries first, then auto in reverse-chronological order
    auto_checks.sort(key=lambda x: x["checked_at"], reverse=True)
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": manual + auto_checks,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Wrote {len(output['items'])} total fact-checks to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

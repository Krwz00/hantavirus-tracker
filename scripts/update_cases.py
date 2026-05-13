"""
update_cases.py — pipeline semi-auto de proposition de mise à jour pour
data/cases.json. NE TOUCHE JAMAIS cases.json directement : écrit uniquement
data/cases-proposed.json + data/cases-proposal-body.md, et c'est le workflow
GitHub Actions qui en fait une Pull Request review-required.

Flux :
  1. Fetch les flux RSS des sources autoritaires (WHO, ECDC, SpF, Google News).
  2. Filtre par fenêtre temporelle (FRESHNESS_DAYS) ET keyword.
  3. Envoie le contenu à Claude (modèle ANTHROPIC_MODEL, défaut Sonnet 4.6)
     avec un system prompt strict (cf. SYSTEM_PROMPT).
  4. Valide la réponse contre le schéma de cases.json.
  5. Diff vs cases.json actuel. Si diff non vide, écrit la proposition + le
     body markdown. Sinon exit 78 (neutral GH Actions).

Codes de sortie :
  0  — proposition générée (cases-proposed.json + body écrits)
  78 — rien à proposer (pas d'articles dans la fenêtre, ou pas de diff)
  1  — erreur dure (clé API absente, JSON invalide, schema KO). Pas de PR.

Variables d'env :
  ANTHROPIC_API_KEY  (obligatoire en mode normal, inutile en --dry-run)
  ANTHROPIC_MODEL    (optionnel, défaut claude-sonnet-4-6)

Usage :
  python scripts/update_cases.py            # mode normal (appel API)
  python scripts/update_cases.py --dry-run  # fetch+filter sans API
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import feedparser

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "data" / "cases.json"
PROPOSED_PATH = ROOT / "data" / "cases-proposed.json"
BODY_PATH = ROOT / "data" / "cases-proposal-body.md"

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 6000
FRESHNESS_DAYS = 14
MAX_ARTICLES = 25  # cap envoyé à Claude — priorisation par autorité de source

KEYWORDS = ("hantavirus", "hondius", "andes virus", "andes hantavirus")

# Sources autoritaires. Liste extensible : ajouter une entrée RSS ici.
# `priority` plus petit = plus prioritaire dans la sélection des MAX_ARTICLES
# articles envoyés à Claude. Les sources officielles passent devant la presse.
# Le scraping HTML (ECDC threats page, SpF communiqués, info.gouv.fr) est
# déféré ; en pratique Google News agrège déjà ces sites quand ils publient.
SOURCES = [
    {"name": "OMS — News", "url": "https://www.who.int/rss-feeds/news-english.xml", "priority": 1},
    {"name": "ECDC — News & press releases", "url": "https://www.ecdc.europa.eu/en/taxonomy/term/1307/feed", "priority": 1},
    {"name": "ECDC — Communicable disease threats report", "url": "https://www.ecdc.europa.eu/en/taxonomy/term/1505/feed", "priority": 1},
    {"name": "Santé publique France", "url": "https://www.santepubliquefrance.fr/rss.xml", "priority": 2},
    {"name": "ANRS — MIE", "url": "https://anrs.fr/feed/", "priority": 2},
    {"name": "Inserm", "url": "https://www.inserm.fr/feed/", "priority": 2},
    {"name": "Google News — official sources (site filter)",
     "url": "https://news.google.com/rss/search?q=hantavirus+(site%3Awho.int+OR+site%3Aecdc.europa.eu+OR+site%3Asantepubliquefrance.fr+OR+site%3Ainfo.gouv.fr+OR+site%3Apasteur.fr)&hl=en&gl=US&ceid=US:en",
     "priority": 3},
    {"name": "Google News (FR)", "url": "https://news.google.com/rss/search?q=hantavirus&hl=fr&gl=FR&ceid=FR:fr", "priority": 4},
    {"name": "Google News (EN)", "url": "https://news.google.com/rss/search?q=hantavirus&hl=en&gl=US&ceid=US:en", "priority": 4},
]

# -----------------------------------------------------------------------------
# PROMPT
# -----------------------------------------------------------------------------

SYSTEM_PROMPT = """Tu es un agent d'extraction de données épidémiologiques. Ton seul rôle est d'extraire des chiffres explicitement présents dans des textes officiels et de les transcrire dans un JSON strict.

Règles absolues :
1. Tu ne dois JAMAIS inventer un chiffre, une localisation, ou une date. Si l'information n'est pas dans le texte fourni, tu ne la mets pas.
2. Tu réponds UNIQUEMENT avec du JSON valide, conforme au schéma fourni. Pas de prose autour, pas de markdown, pas de fences ```json. Le premier caractère de ta réponse est `{`, le dernier est `}`.
3. Pour chaque cas, décès, ou contact ajouté ou modifié, tu cites obligatoirement la source exacte dans les champs `source` et `source_url`.
4. Si tu trouves une contradiction entre deux sources (par exemple OMS dit 5 cas, presse dit 7), tu prends la source la plus officielle ET la plus récente. Tu n'inventes pas de moyenne.
5. Si aucune information nouvelle n'est présente dans les textes, tu renvoies le cases.json fourni À L'IDENTIQUE.
6. Ne modifie PAS endemic_zones ni hondius_route sauf si une source officielle ajoute une escale documentée du MV Hondius.
7. Conserve tous les champs FR/EN existants en bilingue. Si tu ajoutes un cas, fournis title, title_en, location, location_en, detail, detail_en.
8. Format date : YYYY-MM-DD strict. Tous les ids existants doivent rester inchangés."""

SCHEMA_DOC = """Schéma de data/cases.json (champs critiques) :

{
  "updated_at": "ISO 8601 UTC datetime",
  "stats": {
    "suspected": int,                          // cas suspects en attente
    "contacts_monitored": int,                 // contacts surveillés
    "transmission_label_fr": str,              // ex. "limitée"
    "transmission_label_en": str               // ex. "limited"
  },
  "cases": [
    {
      "id": "xx-NNN",                          // unique, préfixe pays (fr-001, za-001, etc.)
      "type": "confirmed" | "death" | "monitoring",
      "count": int,                            // strictement > 0
      "lat": float,                            // -90..90
      "lng": float,                            // -180..180
      "location": "Localisation FR",
      "location_en": "Location EN",
      "title": "Titre court FR",
      "title_en": "Short title EN",
      "detail": "Phrase descriptive FR.",
      "detail_en": "Descriptive sentence EN.",
      "date": "YYYY-MM-DD",
      "source": "Nom de la source",
      "source_url": "https://..."              // non vide
    }
  ],
  "endemic_zones": [...],                      // NE PAS modifier
  "hondius_route": [[lat, lng], ...]           // NE PAS modifier sauf escale officielle
}"""


# -----------------------------------------------------------------------------
# FETCH + FILTER
# -----------------------------------------------------------------------------

def strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def matches_keywords(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in KEYWORDS)


def fetch_recent(source: dict, cutoff: datetime) -> Iterable[dict]:
    """Yield entries published >= cutoff that mention any keyword."""
    parsed = feedparser.parse(source["url"])
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        if not (matches_keywords(title) or matches_keywords(summary)):
            continue

        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if not date_struct:
            # Articles sans date publiée : on skip pour rester strict sur la fenêtre.
            continue
        dt = datetime(*date_struct[:6], tzinfo=timezone.utc)
        if dt < cutoff:
            continue

        yield {
            "source_name": source["name"],
            "source_priority": source.get("priority", 9),
            "title": title,
            "summary": summary[:1800],
            "url": entry.get("link", ""),
            "published": dt.isoformat(),
        }


def normalize_title(s: str) -> str:
    """Lowercase + strip punctuation + collapse spaces for dedup."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    # Garde les 60 premiers caractères du titre normalisé comme clé : suffit
    # pour repérer un même article republié par plusieurs aggregateurs.
    return s[:60]


def collect_articles(cutoff: datetime) -> list[dict]:
    articles: list[dict] = []
    for src in SOURCES:
        try:
            n_before = len(articles)
            articles.extend(fetch_recent(src, cutoff))
            n_added = len(articles) - n_before
            print(f"  + {src['name']}: {n_added} relevant in window")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {src['name']}: {exc}", file=sys.stderr)

    # Dédup par titre normalisé : Google News encode chaque URL différemment
    # même pour le même article, donc dedup par URL n'attrape pas grand chose.
    # On garde la version la plus prioritaire (= source la plus officielle).
    by_title: dict[str, dict] = {}
    for a in articles:
        key = normalize_title(a["title"])
        if not key:
            continue
        existing = by_title.get(key)
        if existing is None or a["source_priority"] < existing["source_priority"]:
            by_title[key] = a
    deduped = list(by_title.values())

    # Tri : (priorité asc, date desc). Sources officielles d'abord, puis plus récent.
    deduped.sort(key=lambda a: (a["source_priority"], -datetime.fromisoformat(a["published"]).timestamp()))

    if len(deduped) > MAX_ARTICLES:
        print(f"  → cap à {MAX_ARTICLES} articles sur {len(deduped)} (priorisation autorité+date)")
        deduped = deduped[:MAX_ARTICLES]
    return deduped


# -----------------------------------------------------------------------------
# LLM CALL
# -----------------------------------------------------------------------------

def build_user_prompt(current: dict, articles: list[dict]) -> str:
    parts: list[str] = [SCHEMA_DOC, "", "État actuel de data/cases.json :", "```json",
                        json.dumps(current, ensure_ascii=False, indent=2), "```", ""]
    parts.append(f"Publications à analyser ({len(articles)} article(s) dans les {FRESHNESS_DAYS} derniers jours) :")
    for i, a in enumerate(articles, 1):
        parts.extend([
            "",
            f"--- Article {i} ---",
            f"Source : {a['source_name']}",
            f"Titre : {a['title']}",
            f"URL : {a['url']}",
            f"Publié : {a['published']}",
            f"Résumé : {a['summary']}",
        ])
    parts.extend([
        "",
        "Tâche : si ces textes contiennent un chiffre, une date, ou une localisation NOUVEAUX ou MODIFIÉS par rapport au cases.json fourni, retourne le cases.json mis à jour. Conserve tous les champs existants non concernés. Si rien à changer, retourne le JSON IDENTIQUE à l'entrée.",
        "Réponse attendue : JSON pur, rien d'autre.",
    ])
    return "\n".join(parts)


def call_claude(api_key: str, prompt: str) -> str:
    # Import paresseux pour permettre --dry-run sans dépendance installée.
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    text = "".join(parts).strip()
    # Robustesse : si le LLM enveloppe quand même en ```json, on l'enlève.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# -----------------------------------------------------------------------------
# VALIDATION + DIFF
# -----------------------------------------------------------------------------

ALLOWED_TYPES = {"confirmed", "death", "monitoring"}
REQUIRED_CASE_FIELDS = ("id", "type", "count", "lat", "lng", "date",
                       "source", "source_url",
                       "title", "title_en", "location", "location_en",
                       "detail", "detail_en")


def validate_schema(data) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["racine pas un objet"]

    if not isinstance(data.get("cases"), list):
        errors.append("'cases' absent ou pas une liste")
        return errors

    seen_ids: set[str] = set()
    for i, c in enumerate(data["cases"]):
        prefix = f"cases[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{prefix} pas un objet")
            continue
        for fld in REQUIRED_CASE_FIELDS:
            if fld not in c:
                errors.append(f"{prefix} champ manquant '{fld}'")
        if c.get("type") not in ALLOWED_TYPES:
            errors.append(f"{prefix} type invalide '{c.get('type')}'")
        count = c.get("count")
        if not isinstance(count, int) or count <= 0:
            errors.append(f"{prefix} count invalide {count!r}")
        try:
            datetime.strptime(str(c.get("date", "")), "%Y-%m-%d")
        except (ValueError, TypeError):
            errors.append(f"{prefix} date invalide {c.get('date')!r} (attendu YYYY-MM-DD)")
        lat = c.get("lat")
        lng = c.get("lng")
        if not isinstance(lat, (int, float)) or not (-90 <= lat <= 90):
            errors.append(f"{prefix} lat invalide {lat!r}")
        if not isinstance(lng, (int, float)) or not (-180 <= lng <= 180):
            errors.append(f"{prefix} lng invalide {lng!r}")
        if not c.get("source"):
            errors.append(f"{prefix} source vide")
        if not c.get("source_url"):
            errors.append(f"{prefix} source_url vide")
        cid = c.get("id", "")
        if not isinstance(cid, str) or not cid:
            errors.append(f"{prefix} id vide")
        elif cid in seen_ids:
            errors.append(f"{prefix} id dupliqué '{cid}'")
        else:
            seen_ids.add(cid)
    return errors


def diff_cases(old: dict, new: dict) -> dict:
    old_by_id = {c["id"]: c for c in old.get("cases", []) if isinstance(c, dict) and c.get("id")}
    new_by_id = {c["id"]: c for c in new.get("cases", []) if isinstance(c, dict) and c.get("id")}
    added = [c for cid, c in new_by_id.items() if cid not in old_by_id]
    removed = [c for cid, c in old_by_id.items() if cid not in new_by_id]
    modified: list[dict] = []
    for cid in set(old_by_id) & set(new_by_id):
        if old_by_id[cid] != new_by_id[cid]:
            modified.append({"id": cid, "old": old_by_id[cid], "new": new_by_id[cid]})
    stats_changed = old.get("stats") != new.get("stats")
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "stats_changed": stats_changed,
        "old_stats": old.get("stats"),
        "new_stats": new.get("stats"),
        "total_changes": len(added) + len(removed) + len(modified) + (1 if stats_changed else 0),
    }


# -----------------------------------------------------------------------------
# PR BODY
# -----------------------------------------------------------------------------

def build_body(diff: dict, articles: list[dict], raw_response: str) -> str:
    L: list[str] = []
    L.append("## Proposition automatique de mise à jour de `data/cases.json`")
    L.append("")
    L.append(f"- Date du run : `{datetime.now(timezone.utc).isoformat()}`")
    L.append(f"- Modèle : `{MODEL}`")
    L.append(f"- Modifications : **{diff['total_changes']}**")
    L.append("")

    if diff["added"]:
        L.append(f"### Cas ajoutés ({len(diff['added'])})")
        for c in diff["added"]:
            L.append(f"- `{c['id']}` — **{c.get('title','?')}** ({c['type']} × {c['count']}, {c.get('date','?')})")
            L.append(f"  - location : {c.get('location','?')}")
            L.append(f"  - source : [{c.get('source','?')}]({c.get('source_url','#')})")
        L.append("")

    if diff["modified"]:
        L.append(f"### Cas modifiés ({len(diff['modified'])})")
        for m in diff["modified"]:
            o, n = m["old"], m["new"]
            changed_keys = sorted(k for k in set(o) | set(n) if o.get(k) != n.get(k))
            L.append(f"- `{m['id']}` ({n.get('title','?')})")
            for k in changed_keys[:8]:
                L.append(f"  - `{k}` : `{o.get(k)!r}` → `{n.get(k)!r}`")
            if len(changed_keys) > 8:
                L.append(f"  - … et {len(changed_keys) - 8} autre(s) champ(s)")
        L.append("")

    if diff["removed"]:
        L.append(f"### Cas supprimés ({len(diff['removed'])})")
        for c in diff["removed"]:
            L.append(f"- `{c['id']}` — {c.get('title','?')} (date : {c.get('date','?')})")
        L.append("")

    if diff["stats_changed"]:
        L.append("### stats modifié")
        L.append(f"- Ancien : `{json.dumps(diff['old_stats'], ensure_ascii=False)}`")
        L.append(f"- Nouveau : `{json.dumps(diff['new_stats'], ensure_ascii=False)}`")
        L.append("")

    L.append("---")
    L.append("")
    L.append(f"### Sources analysées ({len(articles)})")
    for a in articles:
        L.append(f"- [{a['source_name']}]({a['url']}) — {a['title']} ({a['published'][:10]})")
    L.append("")

    L.append("<details><summary>Réponse brute du LLM (audit)</summary>")
    L.append("")
    L.append("```json")
    truncated = raw_response if len(raw_response) <= 12000 else raw_response[:12000] + "\n...[truncated]..."
    L.append(truncated)
    L.append("```")
    L.append("</details>")
    L.append("")
    L.append("---")
    L.append("")
    L.append("⚠️ **Avant de merger** : vérifier que chaque chiffre est sourçable dans les textes ci-dessus. Le LLM peut halluciner ; cette PR est une proposition, pas une vérité.")
    return "\n".join(L)


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch + filter uniquement, pas d'appel API, pas d'écriture.")
    args = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
    print(f"Fetching {len(SOURCES)} sources (cutoff: {cutoff.isoformat()})")
    articles = collect_articles(cutoff)
    print(f"Articles uniques pertinents : {len(articles)}")

    if not articles:
        print("Aucun article dans la fenêtre. Rien à proposer.")
        return 78

    if args.dry_run:
        print()
        print("=== Dry run : articles qui seraient envoyés à Claude ===")
        for a in articles[:30]:
            print(f"- [{a['source_name']}] {a['title'][:90]}")
            print(f"    {a['url']}")
            print(f"    Publié : {a['published']}")
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[err] ANTHROPIC_API_KEY non défini. Utilise --dry-run pour tester sans clé.",
              file=sys.stderr)
        return 1

    current = json.loads(CASES_PATH.read_text())
    prompt = build_user_prompt(current, articles)
    print(f"Prompt size : {len(prompt)} chars, ~{len(prompt)//4} tokens estimés")
    print(f"Appel API → {MODEL}…")

    try:
        raw = call_claude(api_key, prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[err] appel API : {exc}", file=sys.stderr)
        return 1

    print(f"Réponse reçue : {len(raw)} chars")

    try:
        proposed = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[err] JSON invalide : {exc}", file=sys.stderr)
        print(f"Début réponse : {raw[:400]!r}", file=sys.stderr)
        return 1

    errors = validate_schema(proposed)
    if errors:
        print("[err] validation schéma KO :", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    diff = diff_cases(current, proposed)
    print(f"Diff : +{len(diff['added'])} added, -{len(diff['removed'])} removed, "
          f"~{len(diff['modified'])} modified, stats:{diff['stats_changed']}")

    if diff["total_changes"] == 0:
        print("Aucun changement détecté. Pas de proposition.")
        return 78

    PROPOSED_PATH.write_text(json.dumps(proposed, ensure_ascii=False, indent=2) + "\n")
    BODY_PATH.write_text(build_body(diff, articles, raw))
    print(f"Proposition écrite : {PROPOSED_PATH.relative_to(ROOT)}")
    print(f"Body écrit : {BODY_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

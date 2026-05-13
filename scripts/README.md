# scripts/

Tous les scripts Python utilitaires du projet. Lancés en local ou via GitHub
Actions (`.github/workflows/`). Voir aussi [CLAUDE.md](../CLAUDE.md) à la
racine pour les conventions transverses.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

Dépendances :
- `feedparser` — parsing RSS
- `python-dateutil` — parsing dates (formats variés des flux)
- `Pillow` — génération de l'image OG
- `anthropic` — SDK Claude API (uniquement pour `update_cases.py`)

## `update_news.py`

Agrège `data/news.json` depuis ~30 flux RSS (presse internationale, agences
santé, Google News safety net). Filtre par mots-clés hantavirus. Préserve
les entrées `manual: true` entre runs. Trie le résultat final par date desc.

```bash
python scripts/update_news.py
```

Lancé toutes les heures par `.github/workflows/update.yml`. Pas de secret
requis (sources publiques).

## `update_factchecks.py`

Même architecture que `update_news.py` mais cible les cellules de
fact-checking professionnelles (AFP Factuel, Libération CheckNews, Snopes,
Maldita.es, etc.). Écrit `data/factchecks.json`.

Lancé toutes les heures par `.github/workflows/update.yml`.

## `update_cases.py`

Pipeline semi-auto qui PROPOSE une mise à jour de `data/cases.json` via
l'API Claude, sous forme de PR draft review-required. **Ne touche jamais
cases.json directement.**

Voir la section dédiée dans [CLAUDE.md](../CLAUDE.md). Requiert le secret
`ANTHROPIC_API_KEY`.

```bash
# Dry-run sans clé API : ne fait que fetch + filter, affiche les articles
python scripts/update_cases.py --dry-run

# Mode normal : envoie à Claude, écrit data/cases-proposed.json si diff
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/update_cases.py
```

Lancé chaque jour à 09:00 UTC par `.github/workflows/update-cases.yml`.

## `test_feeds.py`

Diagnostic des flux RSS. Affiche un rapport tabulé : HTTP status, parse OK ?,
nombre d'entrées, nombre de matches keywords. Ne touche pas `data/`.

```bash
python scripts/test_feeds.py
python scripts/test_feeds.py --news
python scripts/test_feeds.py --factchecks
python scripts/test_feeds.py --json
```

## `generate_og_image.py`

Régénère `og-image.png` (1200x630, image de preview sociale). Lit les
compteurs depuis `data/cases.json` et utilise les TTF variables de
`assets/fonts/` (Newsreader, Hanken Grotesk, JetBrains Mono).

```bash
python scripts/generate_og_image.py
```

À relancer après tout changement significatif des chiffres dans
`data/cases.json`.

## Codes de sortie

| Script | 0 | 78 | 1 |
|---|---|---|---|
| `update_news.py` | OK | — | erreur fatale |
| `update_factchecks.py` | OK | — | erreur fatale |
| `update_cases.py` | proposition générée | rien à proposer (neutre) | erreur (clé API, schéma, JSON) |
| `test_feeds.py` | toujours 0 | — | — |
| `generate_og_image.py` | OK | — | erreur fatale |

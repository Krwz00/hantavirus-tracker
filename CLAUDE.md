# Notes Claude — hantavirus-tracker

Ce fichier est destiné à toute session Claude qui reprendra le projet. Il
documente l'architecture, les conventions strictes, et les opérations
courantes.

## Mission du projet

Tracker indépendant du foyer d'hantavirus Andes lié au MV Hondius (mai 2026),
conçu comme outil de **déflation de panique** face à la désinformation sur les
réseaux. Site en ligne : <https://krwz00.github.io/hantavirus-tracker/>.

Public visé : grand public francophone d'abord, anglophone ensuite. Ton à
respecter : factuel, sobre, calme. Aucune monétisation, aucun tracking.

## Architecture

```
hantavirus-tracker/
├── index.html              # frontend statique, tout-en-un (CSS + JS inline)
├── og-image.png            # image de preview pour les partages sociaux (1200x630)
├── CLAUDE.md               # ce fichier
├── README.md               # README public
├── assets/
│   └── fonts/              # TTF variables (Newsreader, HankenGrotesk, JetBrainsMono)
├── data/
│   ├── cases.json          # cas, décès, contacts, zones endémiques, route Hondius
│   ├── news.json           # actus (manuelles + scrappées par GH Actions)
│   └── factchecks.json     # factchecks (manuels + scrappés)
├── scripts/
│   ├── requirements.txt    # feedparser, python-dateutil, Pillow (pour og-image)
│   ├── update_news.py      # agrège data/news.json depuis les flux RSS
│   ├── update_factchecks.py# agrège data/factchecks.json depuis les flux RSS
│   ├── generate_og_image.py# régénère og-image.png avec les fontes du projet
│   └── test_feeds.py       # diagnostic local des flux
└── .github/workflows/
    └── update.yml          # GH Actions cron toutes les heures
```

Hébergement : GitHub Pages, branche `main`, racine du repo. Pas de build step.

## Conventions strictes (à respecter sans demander)

### Typographie / contenu

- **Pas de tirets cadratins (`—`) dans le contenu visible.** Le user n'en veut
  pas. Utiliser `:` ou `,` à la place. Les tirets dans le code (commentaires,
  identifiants) sont OK, c'est seulement le contenu visible utilisateur.
- **Bilingue FR/EN complet** : toute chaîne texte visible doit basculer via
  `data-i18n="…"` (HTML statique) ou via `currentLang()` (chaînes JS dynamiques).
  Le FR est la langue par défaut (`<html lang="fr">`), l'EN est la traduction.
  Voir bloc `translations.en` dans `index.html`.
- **Ton broadsheet sobre** : pas d'emojis, pas de couleurs criardes, pas de
  call-to-action commerciaux. Inspiration : NYT/Le Monde/Reuters en version
  imprimée.

### Couleurs (variables CSS)

```
--paper:      #f3ede2   fond crème
--paper-deep: #ebe3d3   fond stats / sidebar
--ink:        #0d0c0a   texte principal
--ink-soft:   #3a3631   texte secondaire
--ink-faint:  #756e62   labels mono / méta
--rule:       #1a1814   filets / séparateurs
--rule-soft:  #c9c0ae   filets discrets
--confirmed:  #8b1a1a   cas confirmé (rouge sombre)
--death:      #2a0808   décès (rouge presque noir)
--monitoring: #a06b1a   monitoring (ambre)
--endemic:    #2c3e5c   zones endémiques (bleu nuit)
--debunk:     #4a6741   factcheck vert sombre
```

Identité accessoire (favicon, brand) : **navy `#0F2240`** + **or `#C8A064`**.

### Typographies

- **Newsreader** (serif) — display (titres, popups, italiques) ; variations
  `opsz` exploitées
- **Hanken Grotesk** (sans) — corps de texte courant
- **JetBrains Mono** (mono) — labels stats, eyebrow, méta dates, badges

Toutes chargées via Google Fonts dans `<head>`.

## Comment ajouter une source RSS

### News (`scripts/update_news.py`)

Ajouter une entrée dans la liste `FEEDS` :

```python
{"name": "Nom affiché dans l'UI", "url": "https://.../rss.xml", "tag": "media"}
```

Tags disponibles (contrôlent la pill colorée dans la sidebar) :
`who`, `gov`, `ship`, `research`, `alert`, `media`.

**Filet de sécurité** : Google News couvre déjà tout titre mentionnant
« hantavirus » dans la presse mondiale (FR + EN). Ne pas l'enlever sauf
remplacement par mieux. Les flux individuels (BBC, NYT, Le Monde…) restent
utiles pour les articles dont le titre ne contient pas le mot-clé mais où
le corps en parle.

### Factchecks (`scripts/update_factchecks.py`)

Même format dans `FACTCHECK_SOURCES`, tag `"alert"` par défaut.

### Vérifier avant de commit

```bash
python scripts/test_feeds.py
```

Rapport tabulé : HTTP status, parse OK ?, entrées, matches keywords.
Si un flux passe à `404`/`403`/`ERR(...)`, le remplacer ou le retirer.

### Mots-clés

`KEYWORDS = ("hantavirus", "hondius", "andes virus", "virus des andes", "hantaan")`

Définis dans chacun des deux scripts. Garder la liste serrée pour éviter les
faux positifs (ne pas ajouter de mots génériques comme « virus »).

## Comment ajouter un cas

Éditer `data/cases.json`, tableau `cases`. Schéma :

```json
{
  "id": "xx-NNN",                       // unique, prefixe pays
  "type": "confirmed" | "death" | "monitoring",
  "count": 1,                            // nombre — détermine la taille du marker
  "lat": 48.8970,
  "lng": 2.3389,
  "location":    "Localisation (FR)",
  "location_en": "Location (EN)",
  "title":    "Titre court (FR)",
  "title_en": "Short title (EN)",
  "detail":    "Phrase descriptive (FR).",
  "detail_en": "Descriptive sentence (EN).",
  "date": "2026-05-12",
  "source":     "Nom de la source",
  "source_url": "https://..."
}
```

Le compteur top (`#total-confirmed`, `#total-deaths`) est calculé en JS depuis
ces entrées (somme des `count` par `type`). Pas besoin de toucher au HTML.

Pour ajouter une **zone endémique historique** : tableau `endemic_zones`,
mêmes paires FR/EN pour `name` et `detail`, plus `radius_km`.

Pour ajuster la **route du Hondius** : tableau `hondius_route` de paires
`[lat, lng]`.

Champs `stats.suspected`, `stats.contacts_monitored`,
`stats.transmission_label_fr/_en` aussi dans `cases.json`.

## Le flag `manual: true`

Dans `data/news.json` et `data/factchecks.json`, toute entrée avec
`"manual": true` est **préservée** entre runs (voir `load_existing_manual()`
dans les scripts). C'est utile pour :

- La timeline manuelle du foyer Hondius (init du tracker)
- Les claims emblématiques à garder en tête de liste (Covid 2.0, ivermectine…)

Les entrées sans `manual` sont écrasées à chaque run par les flux RSS, triées
par date desc, plafonnées à `MAX_ITEMS = 30`. L'ordre final : manuelles
d'abord, puis auto.

Pour ajouter une entrée manuelle : éditer le JSON directement avec `"manual":
true` et un `id` stable. Le commit du fichier suffit, le prochain run la
préservera.

## Relancer les workflows à la main

GitHub UI : `Actions → Update tracker feeds → Run workflow` (branch `main`).

CLI :

```bash
gh workflow run "Update tracker feeds"
gh run watch
```

Le cron tourne toutes les heures (`cron: "0 * * * *"`). En cas de bug d'un
script, l'étape `Update news feed` ou `Update fact-checks` échouera et
le workflow s'arrêtera avant le commit. Logs : `Actions → run le plus récent`.

## Tests locaux

```bash
# Setup unique
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

# Diagnostic des flux (rapide, sans toucher data/)
python scripts/test_feeds.py
python scripts/test_feeds.py --news
python scripts/test_feeds.py --factchecks

# Run complet (réécrit data/news.json et data/factchecks.json)
python scripts/update_news.py
python scripts/update_factchecks.py

# Servir le front en local
python -m http.server 8000
# puis http://localhost:8000
```

Le frontend utilise `fetch('./data/…')`, donc nécessite un serveur HTTP
(ouvrir `index.html` en `file://` ne marche pas).

## Régénérer og-image.png

`og-image.png` est la preview 1200x630 servie aux partages sociaux. Le
compteur affiché (« 5 cas confirmés », « 3 décès à bord ») est lu depuis
`data/cases.json` ; il faut donc régénérer l'image après tout changement
significatif des chiffres :

```bash
pip install Pillow
python scripts/generate_og_image.py
```

Les fontes TTF utilisées sont dans `assets/fonts/` (Newsreader, Newsreader
Italic, Hanken Grotesk, JetBrains Mono — variables). Elles sont commitées
pour reproductibilité, **ne pas les ajouter au .gitignore**.

## Pièges connus

- **`feedparser.bozo == 1` n'est pas bloquant** : le parser est tolérant et
  remonte souvent des entrées même quand le XML est légèrement cassé. Ne pas
  retirer un flux uniquement parce qu'il a un warning, regarder d'abord si
  `entries > 0` dans `test_feeds.py`.
- **Reuters, AP News, info.gouv.fr, Le Figaro Sciences, Les Échos, Institut
  Pasteur** : leurs flux RSS historiques sont morts ou bloqués (404/403/DNS).
  Pour les capter, on passe désormais par Google News (filet de sécurité).
- **Le LLM est désactivé** dans `update_factchecks.py` — pas de clé Anthropic
  requise. Le script aggrège juste les flux de cellules factcheck pro. Si le
  user veut réintroduire du factchecking auto, l'historique du README en parle.

## Conventions de commit

Pas d'exigence stricte. Le bot Actions fait `auto: update feeds YYYY-MM-DDTHHMMZ`.
Pour les commits humains, garder court et factuel. Pas besoin de
co-authoring tag sauf si Claude pousse directement (alors ajouter
`Co-Authored-By: Claude …`).

## Quand demander confirmation au user

- Avant tout `git push --force` ou `reset --hard`.
- Avant de modifier la clé API Anthropic ou tout secret.
- Avant de supprimer une entrée `manual: true`.
- Avant de changer l'URL Stripe (`https://buy.stripe.com/00w4gy0yg7P30Ct1l55Ne00`).
- Avant de toucher au LinkedIn `https://www.linkedin.com/in/mehdi-triki/`.

Sinon le user a explicitement délégué l'autorité de commit-push sur `main`.

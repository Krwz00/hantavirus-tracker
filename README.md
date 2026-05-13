# Hantavirus Tracker

Outil indépendant de suivi de l'épidémie d'hantavirus Andes (foyer du MV Hondius, mai 2026), conçu comme un dispositif de **déflation de panique** face à la vague de désinformation qui accompagne l'événement sur les réseaux sociaux.

- **Compteur global** des cas confirmés, dans la durée
- **Carte mondiale** des cas, des décès et des zones endémiques historiques
- **Feed d'actualité** mis à jour toutes les heures depuis les flux RSS officiels (OMS, ECDC, Santé publique France, ANRS MIE, Institut Pasteur)
- **Désinfox automatique** : détection des claims dubieuses sur sources connues + factcheck généré via Claude API et grounded sur les références OMS/Pasteur

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  GitHub repo (hosted on GitHub Pages or Cloudflare Pages) │
│                                                          │
│  ├── index.html              ◄── served to users         │
│  ├── data/                                               │
│  │   ├── news.json           ◄── fetched by frontend     │
│  │   └── factchecks.json     ◄── fetched by frontend     │
│  ├── scripts/                                            │
│  │   ├── update_news.py                                  │
│  │   └── update_factchecks.py                            │
│  └── .github/workflows/                                  │
│      └── update.yml          ◄── runs scripts hourly     │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

GitHub Actions exécute les scripts Python toutes les heures, commit les JSON mis à jour, et GitHub Pages les sert. Pas de serveur à payer, juste un compte GitHub gratuit et une clé Anthropic API (~5 €/mois pour le fact-checking, plus si tu montes en fréquence).

## Setup

### 1. Clone et push sur GitHub

```bash
git init
git add .
git commit -m "initial"
git remote add origin git@github.com:<user>/hantavirus-tracker.git
git push -u origin main
```

### 2. Configurer la clé Anthropic

Dans le repo GitHub : `Settings → Secrets and variables → Actions → New repository secret`
- Name: `ANTHROPIC_API_KEY`
- Value: ta clé `sk-ant-...`

### 3. Activer GitHub Pages

`Settings → Pages → Source: Deploy from a branch → main / root`

Le site sera disponible sur `https://<user>.github.io/hantavirus-tracker/`.

### 4. (Optionnel) Domaine perso

`Settings → Pages → Custom domain` + DNS CNAME chez ton registrar.

### 5. Tester localement

Le front utilise `fetch()` pour charger les JSON, donc il faut un serveur HTTP (pas `file://`) :

```bash
python -m http.server 8000
# Ouvrir http://localhost:8000
```

Pour tester les scripts en local :

```bash
pip install -r scripts/requirements.txt
python scripts/update_news.py
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/update_factchecks.py
```

## Configurer les sources

### Actualités (`scripts/update_news.py`)

Liste `FEEDS` en haut du script. Chaque entrée :
```python
{
    "name": "Nom affiché dans le tracker",
    "url": "https://.../rss.xml",
    "tag": "who" | "gov" | "ship" | "research" | "alert" | "media"
}
```

Mots-clés de filtrage : variable `KEYWORDS` (par défaut : "hantavirus", "hondius", "andes virus", "virus des andes").

### Désinfox (`scripts/update_factchecks.py`)

Liste `DISINFO_SOURCES`. Mêmes principes. Pour ajouter une chaîne YouTube :
```
https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
```

Le `channel_id` se trouve en regardant le code source d'une page de chaîne (chercher `channelId`).

### Factchecks manuels (curated)

Les fact-checks marqués `"manual": true` dans `data/factchecks.json` sont **préservés à chaque run du script**. C'est utile pour les claims emblématiques qu'on veut garder en tête de liste (Covid 2.0, ivermectine, etc.).

## Limites assumées

- **Le fact-checking automatique ne couvre PAS les contenus purement social-natifs** (TikTok, X, Facebook stories) car leurs API sont fermées ou payantes. On capture ce que les mêmes acteurs publient sur leurs sites et chaînes YouTube — c'est ~70% du volume pour les figures nommées (Raoult, Perronne, Henrion-Caude, Philippot).
- **Pour une couverture totale**, plug un outil de social listening payant (Visibrain, Talkwalker, Brandwatch) à la place de la liste `DISINFO_SOURCES`.
- **Le LLM peut halluciner.** Le prompt grounding et la liste de référence facts limitent fortement le risque mais ne l'annulent pas. Reviser manuellement avant de publier en grand. Tout claim généré doit pouvoir être tracé vers une source de référence.

## Crédits

Sources de référence systématiquement citées :
- [Organisation mondiale de la Santé — Disease Outbreak News](https://www.who.int/emergencies/disease-outbreak-news)
- [European Centre for Disease Prevention and Control](https://www.ecdc.europa.eu/)
- [Santé publique France](https://www.santepubliquefrance.fr/)
- [Institut Pasteur — CNR Hantavirus](https://www.pasteur.fr/)
- [ANRS Maladies infectieuses émergentes](https://anrs.fr/)

Licence : à définir. MIT recommandée pour permettre la réutilisation du dispositif sur d'autres maladies.

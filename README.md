# weizmann-website

Site académique personnel de R. Weizmann Kiendrebeogo, construit avec [Hugo](https://gohugo.io/)
et le thème [HugoBlox](https://github.com/HugoBlox/hugo-blox-builder) (Hugo Academic).

Le CV et les publications ne sont édités qu'à un seul endroit (`data/cv.yml` et
`bibliography/publications.bib`), puis régénérés vers le site et le PDF — voir la section
[Structure](#structure) plus bas.

Convention : chaque publication porte un champ `publication_type` parmi `refereed`,
`submitted`, `in_preparation`, `proceedings`, `collaboration`, `technical_report`. Ces
catégories ne doivent jamais être mélangées, ni sur le site ni dans le CV.

## Lancer le site en local

Prérequis : [Hugo extended](https://gohugo.io/installation/) et Node (pour les dépendances
front-end du thème).

```bash
npm install                # une seule fois, installe les dépendances du thème
hugo server -D             # démarre le serveur local avec les brouillons (-D)
```

Le site est servi sur http://localhost:1313/, avec rechargement automatique à chaque
modification d'un fichier de contenu.

Pour arrêter le serveur : `Ctrl+C` dans le terminal où il tourne, ou
`lsof -ti:1313 | xargs kill` si vous l'avez lancé en arrière-plan.

## Régénérer le CV et les publications

```bash
python scripts/fetch_publications.py    # met à jour publications.bib depuis ADS + ORCID
python scripts/build_cv.py --variant full   # génère static/uploads/CV_Kiendrebeogo.pdf
```

`ADS_TOKEN` doit être défini dans l'environnement pour `fetch_publications.py`. La génération
du PDF nécessite une distribution LaTeX (pdflatex) avec les packages listés en tête de
`scripts/build_cv.py`.

## Structure

```
bibliography/publications.bib   source unique des publications
data/cv.yml                     source unique du reste du CV
        │
        ├── scripts/build_cv.py ──> static/uploads/CV_*.pdf
        └── Hugo                ──> site web
```

Ce dépôt part du thème [Hugo Academic Resume](https://github.com/HugoBlox/theme-academic-cv) ;
les fichiers du thème lui-même vivent en module Hugo (`config/_default/module.yaml`) et ne
sont pas dans ce dépôt.

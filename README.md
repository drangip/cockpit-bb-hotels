# Cockpit B&B HOTELS

Tableau de bord de suivi des revenus digitaux des hôtels B&B HOTELS : carte du réseau, fiche hôtel, revenu mensuel par channel (graphique en aires), suivi de l'objectif du dernier mois et volet par channel média.

## Données

`perf/b&b-adresse & performance.xlsx`, deux onglets :

- **hotel** : référentiel (Hotel ID Vertical Booking / PIM / PMS, nom, URL, ville et ID City, adresse, `Obj Room Rev Mois`).
- **performance** : revenu par hôtel, année, mois et channel. Jointure sur `Hotel ID - Vertical Booking`.

Les adresses sont géocodées via la Base Adresse Nationale (cache : `data/geocode_hotels.csv`).

## Objectif du mois

`Obj Room Rev Mois` est un objectif de revenu chambres tous canaux ; le revenu digital n'en couvre qu'une partie (≈ 10 % sur le réseau).
Le cockpit calcule donc pour le dernier mois disponible :

- **Couverture** = revenu digital / Obj Room Rev Mois
- **Objectif digital** = Obj Room Rev Mois × couverture moyenne du réseau
- **Indice** = revenu digital / objectif digital × 100 (≥ 105 au-dessus, 95–105 en ligne, < 95 en dessous)

## Mettre à jour les données

1. Remplacer `perf/b&b-adresse & performance.xlsx` (fichier fermé dans Excel).
2. Lancer :

```bash
python build_dashboard.py
```

Le script génère `site/index.html` (déployé par Vercel) et `cockpit_bb_hotels.html` (copie locale).
`python build_dashboard.py --template` regénère la page sans relire l'Excel (après une modification de `dashboard_template.html`).

3. Commit + push : Vercel redéploie automatiquement.

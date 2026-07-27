# Registre Contrôle — Backoffice de suivi des contrôles techniques

Application Django remplaçant le registre papier de suivi des clients soumis à des
contrôles techniques périodiques (électricité, gaz, ascenseurs, groupes
électrogènes, …).

- **Authentification** par email + code de vérification à 6 chiffres (inscription,
  connexion, mot de passe oublié), avec throttling et verrouillage anti-bruteforce.
- **Backoffice custom** (pas le Django Admin) : tableau des clients filtrable et
  paginé, fiche client complète, page Alertes & Rappels avec badge compteur.
- **Alertes calculées dynamiquement** (jamais stockées) selon les règles métier :
  rapport inspecteurs dû le **lundi de la semaine suivant la visite**, rapport
  assistante dû **15 jours après la remise** du rapport inspecteurs.

## Stack

Django 5.2 · Python 3.12+ · PostgreSQL (SQLite en fallback dev) · Tailwind CSS
(CDN) + Alpine.js · django-environ · IBM Plex Sans/Mono.

## Installation

```bash
# 1. Cloner / se placer dans le dossier du projet
cd p2

# 2. Environnement virtuel + dépendances
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configuration
cp .env.example .env
# → éditer .env : SECRET_KEY, DATABASE_URL, SMTP…
```

### Base de données

**PostgreSQL** (recommandé) — créer la base puis renseigner `DATABASE_URL` :

```bash
sudo -u postgres psql -c "CREATE USER registre WITH PASSWORD 'registre';"
sudo -u postgres psql -c "CREATE DATABASE registre OWNER registre;"
# .env → DATABASE_URL=postgres://registre:registre@localhost:5432/registre
```

**SQLite** (test rapide sans PostgreSQL) : `DATABASE_URL=sqlite:///db.sqlite3`
(valeur déjà en place dans le `.env` fourni).

### Migrations, superuser, lancement

```bash
python manage.py migrate
python manage.py createsuperuser        # accès /django-admin/
python manage.py runserver              # → http://127.0.0.1:8000/
```

### Données de démonstration (optionnel)

```bash
python manage.py seed_demo
```

Crée 6 clients illustrant chaque type d'alerte **et un compte de test déjà
vérifié** (aucun email nécessaire) :

> **test@registre.local** / **Test-Registre-2025**

## Emails (codes de vérification)

Par défaut le `.env` utilise le **backend console** : les emails (et donc les
codes à 6 chiffres) s'affichent dans le terminal du `runserver` — aucun compte
SMTP requis pour tester.

Quand les identifiants Gmail seront disponibles, basculer dans `.env` :

```ini
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST_USER=votre.compte@gmail.com
EMAIL_HOST_PASSWORD=xxxx xxxx xxxx xxxx   # mot de passe d'application Google
```

> Gmail exige un **mot de passe d'application** :
> https://myaccount.google.com/apppasswords (nécessite la validation en 2 étapes).

## Règles métier des alertes

Pour chaque cycle (1ère et 2ème visite), calcul à chaque affichage :

| Type | Nature | Condition |
|------|--------|-----------|
| 1 | Rappel | Rapport inspecteurs non remis, avant le lundi de la semaine suivant la visite |
| 2 | Alerte | Rapport inspecteurs non remis, lundi dépassé |
| 3 | Rappel | Inspecteurs remis, rapport assistante non remis, dans les 15 jours |
| 4 | Alerte | Inspecteurs remis, rapport assistante non remis, 15 jours dépassés |

Le passage de `rapport_inspecteurs_X` à « Remis » enregistre automatiquement
`date_remise_inspecteurs_X = aujourd'hui` (et l'efface au retour à « Non remis »).

Logique dans `clients/services/alerts.py` (`get_client_alerts`, `get_all_alerts`),
testée indépendamment des vues.

## Tests

```bash
python manage.py test        # 42 tests (alertes, dates limites, auth, throttling)
```

## Structure

```
config/                 # settings (django-environ), urls
accounts/               # User custom (email + rôle), codes de vérification, vues auth
clients/                # modèle Client, formulaires, vues backoffice
  services/alerts.py    # calcul des rappels/alertes (logique métier pure)
  management/commands/seed_demo.py
templates/              # base + auth + backoffice + emails HTML
```

## Rôles

`User.role` : **admin** (accès complet), **assistante** (gestion clients + suivi
rapports), **inspecteur** (prévu pour extension). Le superuser accède aussi à
`/django-admin/` pour la maintenance technique.

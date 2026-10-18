<!-- Généré depuis docs/architecture-sprint1.md -->
## 1. Arborescence du dépôt et applications Django


```
alpha/
├── docker-compose.yml               # services communs (db, redis, backend, worker, beat, frontend)
├── docker-compose.override.yml      # dev : mailpit, ports exposés, volumes de code, runserver / next dev
├── docker-compose.recette.yml       # recette : caddy, images construites, pas de volumes de code
├── docker-compose.prod.yml          # production : idem recette + limites de ressources
├── .env.example                     # toutes les variables, sans valeurs secrètes
├── .gitattributes                   # * text=auto eol=lf (indispensable sous Windows pour les scripts shell)
├── .editorconfig
├── scripts/
│   ├── dev.ps1                      # Windows : up, down, migrate, test, seed, logs, shell
│   ├── dev.sh                       # même chose pour Linux / WSL / CI
│   ├── deploy.sh                    # déploiement VPS (pull, migrate, up -d)
│   └── backup.sh                    # pg_dump chiffré (age) + envoi hors site
├── infra/
│   ├── postgres/
│   │   ├── init/01-roles.sh         # crée alpha_owner, alpha_app, la base ; exécuté au 1er démarrage
│   │   └── postgresql.conf          # réglages VPS (shared_buffers, etc.)
│   └── caddy/Caddyfile              # TLS auto, /api → backend, / → frontend, en-têtes de sécurité
├── backend/
│   ├── Dockerfile                   # python:3.12-slim, multi-stage, utilisateur non root
│   ├── pyproject.toml               # dépendances (voir 1.2) + ruff + pytest
│   ├── manage.py
│   ├── config/
│   │   ├── settings/{base,dev,test,recette,prod}.py
│   │   ├── urls.py                  # /api/v1/… ; /api/v1/schema/ ; /api/v1/docs/ (dev et recette)
│   │   ├── celery.py
│   │   └── wsgi.py
│   ├── alpha/
│   │   ├── core/                    # contexte de requête, erreurs API, chiffrement de champ, pagination, permissions de base
│   │   ├── tenancy/                 # Etablissement, ParametresEtablissement, middleware de contexte, TenantModel, SQL RLS
│   │   ├── comptes/                 # Utilisateur, connexion, MFA, codes de secours, jetons, sessions, téléphone perdu
│   │   ├── organisation/            # unités (périmètres), catalogue des rôles, affectations, codes de permission
│   │   ├── delegations/             # absences et délégations
│   │   ├── taches/                  # boîte « À traiter » générique
│   │   ├── notifications/           # préférences, notifications in-app, e-mails (gabarits FR)
│   │   ├── audit/                   # journal chaîné, triggers, contrôle d'intégrité
│   │   └── plateforme/              # console super-administrateur FYXOP
│   └── tests/                       # tests transverses (isolation, RLS, sécurité) ; tests unitaires dans chaque app
├── frontend/
│   ├── Dockerfile                   # node:22-alpine, build "standalone"
│   ├── package.json
│   ├── next.config.ts               # rewrites /api → backend en dev ; output: "standalone"
│   ├── tailwind.config.ts           # jetons de la charte (section 7.3)
│   ├── src/
│   │   ├── app/                     # routes (section 7.1)
│   │   ├── components/{ui,shell,auth,taches,compte,admin,audit,console}/
│   │   ├── lib/api/{client.ts,schema.d.ts,hooks/}   # schema.d.ts généré depuis l'OpenAPI
│   │   ├── lib/{format.ts,permissions.ts}
│   │   └── middleware.ts            # redirection vers /connexion si pas de cookie de session
│   └── e2e/                         # Playwright
├── docs/
│   ├── sources/                     # CDC, prototype
│   └── architecture-sprint1.md      # ce document
└── .github/workflows/ci.yml
```

### 1.1 Applications Django (package `alpha.*`)

| App | Rôle au sprint 1 | Modèles |
|---|---|---|
| `core` | utilitaires transverses : `contexte` (contextvars : tenant, portée, utilisateur, IP, request_id), format d'erreur, `ChampChiffre`, pagination, `StepUpTOTP` | — |
| `tenancy` | établissements, contexte tenant, RLS | `Etablissement`, `ParametresEtablissement` |
| `comptes` | identité, authentification, MFA, sessions | `Utilisateur`, `AuthenticatorTOTP`, `CodeSecours`, `JetonUsageUnique`, `SessionAppareil`, `HistoriqueMotDePasse`, `SignalementTelephonePerdu` |
| `organisation` | périmètres et catalogue des rôles | `UniteOrganisationnelle`, `Role`, `AffectationRole` |
| `delegations` | absences avec délégation | `Absence`, `Delegation` |
| `taches` | boîte « À traiter » | `Tache` |
| `notifications` | préférences et notifications | `PreferencesNotification`, `Notification` |
| `audit` | journal en ajout seul | `EvenementAudit`, `ControleIntegriteAudit` |
| `plateforme` | console FYXOP | aucun modèle propre (utilise `Etablissement`, `Utilisateur` plateforme, `EvenementAudit`) |

Réservées, à ne pas créer au sprint 1 : `workflow`, `dossiers`, `documents` (S2) ; `rh`, `tresorerie`, `contrats`, `gouvernance`, `fiscal`, `pme`, `externes` (S3).

L'admin Django (`django.contrib.admin`) n'est **pas** monté : il contournerait la logique de contexte tenant. Les modèles `auth.Group` et `auth.Permission` ne sont pas utilisés (`Utilisateur` hérite de `AbstractBaseUser` sans `PermissionsMixin`).

### 1.2 Dépendances principales

Backend : `django==5.2.*` (LTS), `djangorestframework~=3.17`, `drf-spectacular`, `psycopg[binary]~=3.3`, `django-environ`, `argon2-cffi`, `pyotp`, `segno` (QR SVG), `cryptography` (MultiFernet), `celery[redis]`, `django-redis`, `openpyxl` (export du journal), `user-agents`, `gunicorn`. Dev/test : `pytest-django`, `factory-boy`, `freezegun`, `ruff`, `mypy` (optionnel).

Frontend : `next@15`, `react@19`, `typescript`, `@tanstack/react-query`, `react-hook-form`, `zod`, `tailwindcss`, `openapi-typescript`, `@playwright/test`, `otplib` (E2E uniquement).

### 1.3 Services docker-compose

| Service | Image | Dev | Recette / prod | Notes |
|---|---|---|---|---|
| `db` | `postgres:16-alpine` | port 127.0.0.1:5432 | réseau interne | volume `pgdata` ; `infra/postgres/init` monté sur `/docker-entrypoint-initdb.d` |
| `redis` | `redis:7-alpine` | interne | interne | cache, sessions (`cached_db`), limitation de débit, broker Celery |
| `migrate` | image backend | `manage.py migrate` | idem, avant `backend` | **se connecte avec `alpha_owner`** ; `depends_on: db (healthy)` ; `restart: "no"` |
| `backend` | image backend | `runserver 0.0.0.0:8000` | `gunicorn -w 3 --threads 2` | se connecte avec `alpha_app` ; `depends_on: migrate (completed_successfully)` |
| `worker` | image backend | `celery worker -c 2` | idem | `alpha_app` |
| `beat` | image backend | `celery beat` | idem | planification (section 6.5) |
| `frontend` | image frontend | `next dev` port 3000 | `node server.js` | dev : `WATCHPACK_POLLING=true` si le code est sur le disque Windows |
| `mailpit` | `axllent/mailpit` | SMTP 1025, UI 127.0.0.1:8025 | absent | recette : SMTP réel ou Mailpit protégé (point ouvert) |
| `caddy` | `caddy:2-alpine` | absent | 80/443 | TLS 1.2+ ; `/api/*` → backend ; reste → frontend |

En dev, le navigateur parle uniquement à `http://localhost:3000` ; Next.js réécrit `/api/:path*` vers `http://backend:8000/api/:path*`. En recette et production, Caddy sert front et API sur la **même origine** (`https://app.<domaine>`), ce qui permet des cookies `SameSite=Lax` sans CORS.

Poste Windows : cloner le dépôt **dans le système de fichiers WSL2** (`\\wsl$\Ubuntu\home\…`) et utiliser Docker Desktop en mode WSL2 ; c'est nettement plus rapide que les montages depuis `C:\` et évite les problèmes de surveillance de fichiers. `node_modules` est un volume anonyme du conteneur, jamais monté depuis l'hôte. `scripts/dev.ps1` encapsule `docker compose` pour PowerShell.

VPS Hostinger KVM 2 (2 vCPU, 8 Go) : recette et production sont deux projets compose distincts (`-p alpha-recette`, `-p alpha-prod`), avec réseaux, volumes, bases, secrets et sous-domaines séparés. Budget mémoire prod ≈ 4,5 Go (Postgres 2 Go avec `shared_buffers=512MB`, backend 1 Go, worker 512 Mo, frontend 512 Mo, Redis 256 Mo), recette ≈ 2 Go.

---


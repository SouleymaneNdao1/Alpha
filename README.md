# ALPHA

Application web de workflow décisionnel multi-établissements, vendue en SaaS (FYXOP).
Pile : Django 5.2 LTS + DRF, PostgreSQL 16 (Row Level Security), Celery + Redis, Next.js 15, Mailpit,
le tout dans Docker.

Conception du sprint 1 : [`docs/architecture-sprint1.md`](docs/architecture-sprint1.md).
Dépannage du poste de développement : [`docs/ops/dev.md`](docs/ops/dev.md).
Recette et production (VPS) : [`docs/ops/deploiement.md`](docs/ops/deploiement.md) ; surveillance : [`docs/ops/monitoring.md`](docs/ops/monitoring.md).

---

## 1. Prérequis (poste Windows)

| Outil | Version | Remarque |
|---|---|---|
| Windows | 10 22H2 ou 11 | virtualisation activée dans le BIOS |
| WSL2 + Ubuntu | WSL ≥ 2.1 (`wsl --version`) | le dépôt est cloné **dans** Ubuntu, pas sur `C:\` |
| Docker Desktop | récent, moteur WSL2 | intégration WSL activée pour Ubuntu |
| Git | celui d'Ubuntu (`sudo apt install git`) | `core.autocrlf` désactivé (voir plus bas) |
| PowerShell | 5.1 (fourni avec Windows) ou 7 | pour `scripts\dev.ps1` |
| Mémoire | 16 Go conseillés (8 Go minimum) | réglage WSL : [`docs/ops/dev.md`](docs/ops/dev.md#3-mémoire-wsl2) |

Sous Linux ou macOS, seuls Docker (avec `docker compose` v2) et Git sont nécessaires ; utilisez
`scripts/dev.sh` à la place de `scripts\dev.ps1`.

## 2. Installation pas à pas sous Windows

**1. Installer WSL2 et Ubuntu** (PowerShell **administrateur**), puis redémarrer :

```powershell
wsl --install -d Ubuntu
wsl --update
```

Au premier lancement d'Ubuntu, choisissez un nom d'utilisateur et un mot de passe Linux.

**2. Installer Docker Desktop**, puis dans *Settings* :
- *General* : cocher « Use the WSL 2 based engine » ;
- *Resources > WSL integration* : activer **Ubuntu** ;
- *Apply & restart*.

**3. Cloner le dépôt dans Ubuntu** (terminal Ubuntu) :

```bash
git config --global core.autocrlf input     # jamais de CRLF dans les fichiers extraits
mkdir -p ~/projets && cd ~/projets
git clone <url-du-depot> alpha
cd alpha
```

Pourquoi dans Ubuntu et pas sur `C:\` : les montages de code sont beaucoup plus rapides et la
détection des modifications (rechargement à chaud de Django et Next.js) fonctionne sans scrutation.

**4. Ouvrir PowerShell dans le dépôt** (PowerShell normal, pas administrateur) :

```powershell
cd \\wsl.localhost\Ubuntu\home\<utilisateur-linux>\projets\alpha
```

`scripts\dev.ps1` détecte que le dépôt est dans WSL2 et exécute Docker dans Ubuntu.
Si PowerShell refuse d'exécuter le script (stratégie d'exécution), lancez une fois
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, ou préfixez chaque commande par
`powershell -ExecutionPolicy Bypass -File` (détails dans [`docs/ops/dev.md`](docs/ops/dev.md#4-autres-problèmes-fréquents)).

**5. Créer le fichier `.env`** (secrets aléatoires, jamais commités) :

```powershell
.\scripts\dev.ps1 init
```

**6. Démarrer** :

```powershell
.\scripts\dev.ps1 up
```

Le premier démarrage télécharge les images et construit backend et frontend (plusieurs minutes).
Au premier démarrage de la base, `infra/postgres/init/01-roles.sh` crée les rôles `alpha_owner` et
`alpha_app` et la base `alpha`. Le service `migrate` applique ensuite les migrations, puis
`backend`, `worker`, `beat` et `frontend` démarrent.

> **Tant que les tâches B1 (projet Django) et F1 (projet Next.js) ne sont pas livrées**, les services
> applicatifs ne peuvent pas démarrer (`manage.py` et les pages Next.js n'existent pas encore).
> Démarrez alors seulement l'infrastructure : `.\scripts\dev.ps1 up db redis mailpit`.

**7. Vérifier** : ouvrir les URL ci-dessous, et contrôler que `alpha_app` n'est propriétaire de rien
(résultat attendu : `0`) :

```powershell
.\scripts\dev.ps1 psql postgres -c "select count(*) from pg_shdepend where refobjid = 'alpha_app'::regrole and deptype = 'o'"
```

## 3. URL locales

| Service | URL | Remarque |
|---|---|---|
| Application | <http://localhost:3000> | seule adresse utilisée par le navigateur ; `/api/*` est relayé vers le backend par Next.js |
| API (directe) | <http://localhost:8000/api/v1/> | schéma : `/api/v1/schema/`, documentation : `/api/v1/docs/` |
| Mailpit | <http://localhost:8025> | tous les e-mails envoyés en développement (aucun ne sort du poste) |
| PostgreSQL | `127.0.0.1:5432`, base `alpha` | utilisateurs `alpha_owner` / `alpha_app`, mots de passe dans `.env` |

Tous les ports sont publiés sur `127.0.0.1` uniquement. Pour en changer (port déjà pris), modifiez
`ALPHA_PORT_*` dans `.env`.

## Se connecter en local

La MFA est obligatoire : chaque compte de démonstration reçoit un mot de passe, une application
d'authentification (secret TOTP) et 10 codes de secours. Dans le dépôt, depuis PowerShell :

1. Démarrer l'environnement :

   ```powershell
   .\scripts\dev.ps1 up
   ```

2. Appliquer les migrations :

   ```powershell
   .\scripts\dev.ps1 migrate
   ```

3. Semer le jeu de démonstration (dans le conteneur `backend`, qui doit être démarré) :

   ```powershell
   .\scripts\dev.ps1 seed
   ```

   La commande affiche à la fin les identifiants de chaque compte (**une seule fois**) et les écrit
   dans `backend\demo-acces\` : `ACCES.txt` (compte, rôle, mot de passe, secret, URI `otpauth://`,
   codes de secours) et un QR code `qr-<compte>.svg` par compte. Ce dossier est exclu de git.
   Sous Linux/WSL : `scripts/dev.sh seed`.

4. Ouvrir `backend\demo-acces\ACCES.txt`, puis ajouter chaque compte à utiliser dans Google
   Authenticator ou Microsoft Authenticator : ouvrir le fichier `.svg` du compte dans le navigateur
   et scanner le QR code (ou saisir le secret à la main, type « basé sur l'heure »).

5. Aller sur <http://localhost:3000> : e-mail et mot de passe, puis le code à 6 chiffres de
   l'application. Un code de secours remplace le code à 6 chiffres, une seule fois.

Comptes à essayer en premier (les mots de passe sont dans `ACCES.txt`) :

| Compte | Rôle | Pour voir |
|---|---|---|
| `s.diouf@etablissement-demo.sn` | Administrateur de l'Établissement démo (banque) | utilisateurs, rôles, organisation, journal |
| `a.kane@etablissement-demo.sn` | DAF (en congé, délégation à `o.faye@…`) | « À traiter » : 9 tâches sur les 4 urgences |
| `o.faye@etablissement-demo.sn` | Comptable, suppléant du DAF | tâches « par délégation de Abdou Kane » |
| `a.diop@etablissement-demo.sn` | Analyste crédit | file de dossiers de crédit |
| `i.ndiaye@sahel-distribution.sn` | DG et administrateur de Sahel Distribution (PME) | boîte « À traiter » de la PME |
| `superadmin@fyxop-demo.sn` | Super-administrateur FYXOP | console de la plateforme |

Le jeu contient aussi un compte invité (jamais activé) et un compte suspendu par établissement,
comme dans le prototype. Détails :

- **Idempotent** : relancer `seed` ne crée aucun doublon et ne change aucun identifiant. Pour
  obtenir de nouveaux mots de passe, secrets et codes (les anciens cessent de fonctionner) :
  `.\scripts\dev.ps1 seed --reinitialiser`. Dossier de sortie : `--sortie <dossier>`.
- **Refusé hors développement** : la commande exige `ALPHA_DEMO_AUTORISEE` vrai (par défaut : vrai en
  développement et en test, faux en production et en recette). En recette, l'activer explicitement
  dans `.env.recette` ; le conteneur n'étant pas inscriptible, ajouter `--sortie /tmp/demo-acces`.
- Aucun e-mail n'est envoyé : les comptes sont activés directement (adresses fictives).
- Les échéances des tâches et l'absence du DAF (7 jours) sont calculées au moment du semis et ne sont
  pas recalculées par une relance : pour une démonstration plus tardive, repartir d'une base vide
  (`.\scripts\dev.ps1 reset`, puis `migrate` et `seed`).

## 4. Commandes

Sous Windows `.\scripts\dev.ps1 <commande>`, sous Linux/WSL/CI `scripts/dev.sh <commande>`.
Sans argument, le script affiche l'aide.

| Commande | Effet |
|---|---|
| `init [--force]` | crée `.env` depuis `.env.example` avec des secrets aléatoires |
| `up [service…]` | construit les images et démarre tout (ou les services cités) ; crée `.env` s'il manque |
| `down` | arrête et supprime les conteneurs ; **les données sont conservées** |
| `ps` | état des services |
| `logs [service…]` | suit les journaux (Ctrl+C pour quitter) |
| `migrate [args]` | `manage.py migrate` avec le rôle `alpha_owner` |
| `shell [service]` | shell Django dans `backend` ; `shell frontend` ouvre `sh` dans ce conteneur |
| `psql [owner\|app\|postgres] [args]` | console SQL ; `app` est soumis à la RLS (0 ligne sans contexte) |
| `test [args]` | `pytest` dans le service `tests` (ex. `test -k rls -x`) |
| `seed [--reinitialiser] [--sortie dossier]` | jeu de démonstration dans le conteneur `backend` (`manage.py semer_demo`) : voir « Se connecter en local » |
| `reset [--oui]` | **efface la base et les volumes locaux**, rejoue l'initialisation, redémarre |

## 5. Organisation Docker

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` | services communs : `db`, `redis`, `migrate`, `backend`, `worker`, `beat`, `frontend` |
| `docker-compose.override.yml` | développement (chargé automatiquement) : `mailpit`, ports, code monté, `runserver`, `next dev`, service `tests` |
| `docker-compose.recette.yml`, `docker-compose.prod.yml` | recette et production (projets `alpha-recette`, `alpha-prod`), via `scripts/deploy.sh` |
| `docker-compose.proxy.yml` | Caddy, HTTPS commun aux deux environnements (projet `alpha-proxy`) |
| `docker-compose.veille.yml` | Uptime Kuma, surveillance externe (sur une autre machine que le VPS) |

Rôles PostgreSQL (architecture § 3.1) :
- `alpha_owner` : propriétaire de la base et des tables, `BYPASSRLS` ; utilisé **uniquement** par
  `migrate`, les tests et les commandes d'exploitation ;
- `alpha_app` : utilisé par `backend`, `worker` et `beat` ; propriétaire de rien, soumis à la RLS.
  Le mot de passe d'`alpha_owner` n'est jamais transmis à ces services.

Les mots de passe ne sont lus qu'à la **première** création du volume de la base : après les avoir
changés dans `.env`, lancez `reset`.

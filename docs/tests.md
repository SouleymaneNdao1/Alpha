# Tests backend (montage T1)

Réglages : `backend/config/settings/test.py`. Fixtures communes : `backend/tests/conftest.py`.
Outils : `backend/tests/bd.py` (connexions), `fabriques.py` (factory-boy), `totp.py`,
`mailpit.py`. Le test `tests/test_infrastructure.py` vérifie le montage lui-même.

## 0. Lancer les tests

### Dans Docker (recommandé)

```powershell
.\scripts\dev.ps1 test                 # toute la suite (service compose « tests »)
.\scripts\dev.ps1 test -k rls -x       # arguments transmis tels quels à pytest
.\scripts\dev.ps1 test --create-db     # recrée la base de test (après une nouvelle migration)
```

(`scripts/dev.sh test …` sous Linux/macOS.) Le service `tests` reçoit `DATABASE_URL`
(alpha_app) et `DATABASE_URL_OWNER` (alpha_owner) construits depuis `.env`, ainsi que
Mailpit (`EMAIL_HOST=mailpit`, `ALPHA_MAILPIT_API`). Il faut que `db` et `redis` tournent
(`scripts/dev.ps1 up`) ; alpha_owner doit avoir `CREATEDB` (`ALPHA_OWNER_CREATEDB=true`,
dev/CI uniquement, voir `infra/postgres/init/01-roles.sh`).

### En local (sans Docker, PostgreSQL 16 accessible)

```bash
cd backend
pip install --require-hashes -r requirements-dev.lock   # Python 3.12, venv conseillé
export DATABASE_URL=postgres://alpha_app:<mdp>@127.0.0.1:5432/alpha
export DATABASE_URL_OWNER=postgres://alpha_owner:<mdp>@127.0.0.1:5432/alpha
export DJANGO_SECRET_KEY=… ALPHA_CLES_CHIFFREMENT=… ALPHA_HMAC_POIVRE=…  # cf. .env
pytest                     # DJANGO_SETTINGS_MODULE = config.settings.test (pyproject.toml)
pytest --create-db         # après une nouvelle migration
```

La base de test s'appelle `test_<base>` ; elle est **conservée** entre deux lancements
(pytest-django la réutilise), d'où `--create-db` après une migration. Sans
`DATABASE_URL_OWNER`, les réglages de test refusent de démarrer. Sans Mailpit (local), les
tests qui demandent la fixture `mailpit` sont sautés (motif affiché par `-ra`).

Avant de pousser : `pytest`, `ruff check .`, `ruff format --check .`,
`python manage.py makemigrations --check --dry-run`.

## 1. Quelle connexion ?

| Alias | Rôle PostgreSQL | Usage |
|---|---|---|
| `default` | **alpha_app** (NOBYPASSRLS) | **tout le code testé** : ORM, vues, tâches Celery. La RLS s'applique vraiment. |
| `proprietaire` | alpha_owner (BYPASSRLS, propriétaire des tables) | **réservé** aux contournements volontaires : lire « hors RLS » ce qui est réellement en base, altérer le journal d'audit (trigger désactivé), contrôler les catalogues. |
| `audit` | alpha_app | connexion indépendante du journal d'audit (B4) ; à déclarer seulement si le test l'exerce. |

Déroulé : la base de test est créée et migrée par alpha_owner, puis `default` repasse sous
alpha_app avant le premier test (vérifié au démarrage : la session échoue sinon). Après
chaque test transactionnel, le vidage (TRUNCATE) est fait par alpha_owner, trigger
`evenement_audit_sans_truncate` désactivé **le temps du vidage seulement**.

Règles :

- Par défaut : `@pytest.mark.django_db` (test dans une transaction annulée à la fin).
- Un test qui utilise `proprietaire` (ou `audit`) en plus de `default` est **transactionnel** :
  une connexion ne voit que ce que l'autre a validé.
  `pytestmark = pytest.mark.django_db(transaction=True, databases=BASES_PROPRIETAIRE)`.
- Ne jamais utiliser `proprietaire` pour préparer des données que le code testé lira :
  passer par les fabriques (elles posent le contexte, comme le provisionnement).
- Outils de `tests/bd.py` : `ALIAS_PROPRIETAIRE`, `BASES_PROPRIETAIRE`, `TOUTES_LES_BASES`,
  `role_courant(alias)`, `sql(alias, requete, params)`, `sql_proprietaire(requete, params)`.

## 2. Contexte tenant

Sous alpha_app, toute requête sur un modèle tenant exige un contexte :

```python
from alpha.tenancy.contexte import contexte_tenant

with contexte_tenant(etablissement.id):          # portée « tenant »
    Role.objects.filter(...)
with contexte_tenant(None, scope="platform"):    # super-admin FYXOP
    ...
```

Sans contexte, la RLS renvoie 0 ligne (et refuse les écritures). Les fixtures `contexte_a` /
`contexte_b` exécutent tout le test sous le contexte de A / B (tests non transactionnels).

## 3. Fabriques (`tests/fabriques.py`, factory-boy)

Chaque fabrique crée l'objet **dans son contexte** (établissement : portée « platform » ;
lignes d'un établissement : son contexte). L'objet renvoyé est utilisable hors contexte,
mais toute nouvelle requête ORM sur un modèle tenant exige de reposer le contexte.

```python
banque = BanqueFactory()                              # + ParametresEtablissement
pme = PMEFactory(parametres__inactivite_session_min=30)
EtablissementFactory(parametres=False)                # sans paramètres
BanqueFactory(roles_defaut=True)                      # + catalogue de rôles par défaut
u = UtilisateurFactory(etablissement=banque, password=MOT_DE_PASSE_TEST)  # ACTIF
admin = UtilisateurFactory(super_admin=True)          # super-admin FYXOP
role = RoleFactory(etablissement=banque, permissions=["admin.utilisateurs"])
AffectationRoleFactory(utilisateur=u, role=role, principal=True)  # même établissement
UniteOrganisationnelleFactory(etablissement=banque)
```

Fixtures prêtes à l'emploi (`conftest.py`) : `etab_a` (banque, code `banque-a`), `etab_b`
(SFD, code `sfd-b`), `utilisateur_a`, `utilisateur_b` (ACTIFS, mot de passe
`MOT_DE_PASSE_TEST`), `contexte_a`, `contexte_b`, `client_api` (anonyme) et
`client_connecte(utilisateur)` (session forgée avec sa `session_appareil`, pour les tests
qui ne portent pas sur l'authentification ; la vraie connexion est dans `tests/outils_auth.py`). `creer_etablissement(code, **champs)` (conftest) et
`tests/outils_comptes.py` (B3) restent disponibles ; pour un nouveau test, préférer les fabriques.

## 4. E-mails : mémoire ou Mailpit

- Sans rien demander : backend **en mémoire**, messages dans `django.core.mail.outbox`
  (vidée avant chaque test). Suffit pour vérifier qu'un e-mail part et ce qu'il contient.
- Fixture `mailpit` : vérifie l'acheminement **SMTP réel**. Si Mailpit répond
  (`ALPHA_MAILPIT_API`, défaut `http://127.0.0.1:8025/api/v1` ; SMTP `EMAIL_HOST:EMAIL_PORT`),
  `EMAIL_BACKEND` passe en SMTP et la fixture renvoie un `ClientMailpit` qui relit par l'API ;
  **sinon le test est sauté** (skip) avec le motif.

```python
def test_invitation(mailpit, utilisateur_a):
    ...
    message = mailpit.attendre_message(destinataire=utilisateur_a.email, sujet="Activez")
    assert "Activez votre compte" in message.sujet   # .texte, .html, .destinataires
```

Mailpit est partagé : utiliser des adresses propres au test, `mailpit.supprimer_pour(adresse)`.
Envois via `transaction.on_commit` : dans un test non transactionnel, les déclencher avec la
fixture `django_capture_on_commit_callbacks(execute=True)` (Celery est en mode eager).

## 5. TOTP (`tests/totp.py`)

```python
secret = nouveau_secret()
code_courant(secret); code_suivant(secret); code_precedent(secret)  # fenêtre ±1 acceptée
code_invalide(secret)          # refusé par la fenêtre
compteur()                     # valeur attendue de dernier_pas (anti-rejeu)
```

Les fonctions suivent l'horloge (`freezegun.freeze_time` compris) ; `a=instant` fixe l'instant.

## 6. Où ranger les tests

`backend/tests/` : tests transverses (isolation, RLS, sécurité, audit). Tests unitaires
d'une application : `backend/alpha/<app>/tests/test_*.py`. Le test
`tests/test_infrastructure.py` vérifie ce montage (critère T1 : `pytest` tourne sous alpha_app).

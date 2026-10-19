<!-- Généré depuis docs/architecture-sprint1.md -->
## 8. Découpage en tâches


Identifiants : `D` devops, `B` backend, `F` frontend, `T` tests. Chaque tâche se termine par une PR relue, avec ses tests.

| ID | Agent | Titre | Dépend de | Critère de fin |
|---|---|---|---|---|
| D1 | devops | Squelette du dépôt, docker-compose dev (db, redis, mailpit, migrate, backend, worker, beat, frontend), script d'init des rôles PostgreSQL, `.gitattributes`, `.env.example`, `scripts/dev.ps1` et `dev.sh` | — | `scripts/dev.ps1 up` démarre tout sous Windows/WSL2 ; `alpha_app` n'est propriétaire de rien |
| B1 | backend | Projet Django : settings par environnement, apps vides, DRF, drf-spectacular, format d'erreur, Celery, Argon2, cookies et CSRF, `core.contexte` | D1 | `/api/v1/schema/` répond ; lint OK |
| B2 | backend | `tenancy` : `Etablissement`, `ParametresEtablissement`, fonctions `app_*`, `TenantModel`/`TenantManager`, `TenantContextMiddleware`, `contexte_tenant`, helper `activer_rls`, décorateur `tache_tenant`, droits par défaut (migration 0001) | B1 | RLS active ; requête sans contexte = 0 ligne |
| T1 | tests | Infrastructure de test : pytest-django, bascule de la connexion `default` sur `alpha_app` après migration, alias `proprietaire` (miroir, `alpha_owner`), factories avec contexte tenant, client Mailpit, utilitaire TOTP | B2 | `pytest` tourne sous `alpha_app` |
| B3 | backend | `comptes` (modèles) et `organisation` : `Utilisateur`, unités, `Role`, `AffectationRole`, codes de permission, rôles par défaut par type d'établissement, fonctions `alpha_resoudre_connexion`/`alpha_resoudre_jeton`, RLS | B2 | migrations + RLS + test de couverture RLS vert |
| B4 | backend | `audit` : table, triggers (chaînage, immutabilité), RLS, service `journaliser`, masquage, commande `verifier_chaine_audit`, `ControleIntegriteAudit`, tâches planifiées d'ancrage | B2 | UPDATE/DELETE/TRUNCATE refusés ; altération détectée |
| B5 | backend | Connexion : mot de passe, pré-auth, MFA TOTP (chiffrement MultiFernet, anti-rejeu), codes de secours, verrouillage, limitation de débit, `SessionAppareil`, `SessionActiviteMiddleware`, connexion inhabituelle, déconnexion, step-up | B3, B4 | flux 4.2 complet, audité |
| B6 | backend | Activation par invitation, réenrôlement, mot de passe oublié/réinitialisation, téléphone perdu (signalement + réinitialisation admin), gabarits d'e-mails FR, envoi via Celery + `on_commit` | B5 | flux 4.3 à 4.7 testés avec Mailpit |
| B7 | backend | API d'administration : utilisateurs (invitation, modification, affectations, suspension, déverrouillage, historique), catalogue des rôles, habilitations, unités, paramètres de sécurité, invariant « dernier administrateur » | B3, B4 | section 5.5 hors délégations |
| B8 | backend | `taches` (modèle, services `ouvrir`/`terminer`/`annuler`, visibilité avec délégation, regroupement par urgence, compteurs) et `delegations` (absences, délégations, validation par le responsable, tâches planifiées) | B3, B4 | section 5.4 + `/moi/absences` |
| B9 | backend | API Mon compte : profil, sécurité, changement d'Authenticator, codes, sessions, préférences et notifications in-app | B5, B8 | section 5.3 |
| B10 | backend | `plateforme` : `creer_super_admin`, provisionnement d'établissement, console API, `alpha_stats_etablissements`, double journalisation | B6, B7 | section 5.7 ; super-admin sans accès au contenu |
| B11 | backend | API du journal : liste par curseur, filtres, indicateurs, export Excel, lancement de contrôle | B4, B5 | section 5.6 |
| B12 | backend | Jeu de démonstration (`manage.py semer_demo`) : « Établissement démo » (banque) et « Sahel Distribution » (PME), utilisateurs du prototype, tâches de démonstration, journal initial | B7, B8, B10 | les écrans du prototype sont reproductibles en recette |
| F1 | frontend | Initialisation Next.js : charte (jetons, polices), composants UI (Button, Input, OtpInput, Tabs, Badge, Table, Card, Modal, Drawer, Stepper, Toast), client d'API + CSRF, génération des types OpenAPI | D1, B1 | Storybook facultatif ; page de démo des composants |
| F2 | frontend | Coquille `(app)` : barre latérale par permissions, bandeau, cloche, garde de session, avertissement d'inactivité, tiroir mobile | F1, B9 | menu conforme à `Moi.permissions` |
| F3 | frontend | Connexion + MFA (OTP, code de secours), mot de passe oublié, réinitialisation | F1, B5, B6 | parcours manuel OK sur Mailpit |
| F4 | frontend | Activation (stepper, QR, codes de secours), onglet Téléphone perdu, réenrôlement | F3, B6 | invitation → `/a-traiter` sans intervention |
| F5 | frontend | Écran « À traiter » | F2, B8 | groupes, filtres et compteurs conformes au prototype |
| F6 | frontend | Mon compte (4 onglets) + page de validation d'absence | F2, B9 | |
| F7 | frontend | Administration : utilisateurs (liste, invitation, fiche), catalogue des rôles, habilitations, délégations, organisation, sécurité et signalements | F2, B7, B8 | |
| F8 | frontend | Journal d'audit | F2, B11 | |
| F9 | frontend | Console FYXOP | F3, B10 | |
| T2 | tests | Isolation : RLS au niveau SQL (sans contexte, contexte A, insertion avec l'id de B), matrice API tenant A/B sur chaque endpoint (404 attendu), super-admin refusé sur toutes les routes tenant, test de couverture RLS | T1, B7, B8, B9, B11 | aucun accès croisé possible |
| T3 | tests | Audit : triggers (UPDATE/DELETE/TRUNCATE même en propriétaire), concurrence (100 insertions parallèles → seq contigus), altération d'une colonne / d'un payload / suppression en fin de chaîne (trigger désactivé via l'alias propriétaire) détectées | T1, B4 | |
| T4 | tests | Sécurité de l'authentification : verrouillage et blocage, rejeu TOTP, code de secours à usage unique, expiration d'inactivité et durée max, CSRF obligatoire, politique de mot de passe, réinitialisation sans MFA refusée, téléphone perdu (signature bloquée, sessions révoquées, auto-traitement interdit), absence de secrets dans les logs et dans l'audit | T1, B5, B6 | |
| T5 | tests | E2E Playwright : invitation → e-mail Mailpit → activation (TOTP via otplib) → À traiter ; absence → validation par le responsable → tâche visible chez le délégataire ; téléphone perdu → réinitialisation admin → réenrôlement | F4, F5, F6, F7, B12 | exécuté en CI |
| D2 | devops | CI GitHub Actions : ruff, pytest sur un vrai PostgreSQL 16 (service), build du frontend, vérification que `schema.d.ts` est à jour, E2E sur docker-compose | D1, T1 | CI verte obligatoire pour fusionner |
| D3 | devops | Recette et production sur le VPS : `docker-compose.recette.yml`/`prod.yml`, Caddyfile (TLS, HSTS, CSP, en-têtes), projets compose séparés, secrets, `deploy.sh`, sauvegarde quotidienne chiffrée hors site + test de restauration | D1, B1, F1 | recette accessible en HTTPS ; restauration testée |
| T6 | tests | Relecture sécurité du code (authentification, habilitations, isolation), checklist OWASP ASVS niveau 2 sur le périmètre du sprint | B5 à B11, F3, F4 | rapport de relecture joint à la recette |

Chemin critique : D1 → B1 → B2 → B3 → B5 → B6 → F4 → T5. Les tâches B4, B7, B8 et T1 peuvent démarrer en parallèle dès B2/B3.

---


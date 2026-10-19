# ALPHA : consignes pour les agents

ALPHA est un SaaS de workflow décisionnel pour banques, SFD et PME (éditeur FYXOP). Il est multi-établissements : chaque établissement ne voit que ses données.
Pile : Django 5.2 LTS, DRF, Celery et Redis, PostgreSQL 16 avec RLS, Next.js 15 (App Router, TypeScript, Tailwind) et Docker.
Le code, les commentaires et les textes de l'interface sont en **français**.

## Lire le moins possible

- Ne lis PAS `docs/architecture-sprint1.md` en entier. Lis seulement les fiches de `docs/archi/` utiles à ta tâche. L'index et la taille de chaque fiche sont dans `docs/archi/README.md`.
- La fiche 10 contient les décisions du client. Elles priment sur le reste.
- Ne lis jamais `docs/sources/prototype.html` en entier (2 Mo). Utilise Grep sur le nom de l'écran, puis lis seulement le passage utile.
- Lis le code existant du module que tu touches avant d'écrire. Ne relis pas tout le dépôt.
- Lance les tests ciblés pendant le travail (`pytest tests/test_xxx.py -q`), puis la suite complète **une seule fois** à la fin. Utilise `-q` et `| tail` pour limiter la sortie.

## Règles non négociables

1. **Isolation.** Toute table d'établissement hérite de `TenantModel` et appelle `activer_rls` dans sa migration. Le test de couverture RLS doit rester vert.
2. **Permissions fermées par défaut.** Chaque vue déclare ses permissions : `alpha/core/permissions.py` et `alpha/organisation/permissions.py`. Un super-admin FYXOP n'accède pas aux routes d'établissement.
3. **Audit.** Toute écriture métier passe par `alpha.audit.services.journaliser`. Un modèle audité déclare `AUDIT_CHAMPS`. Aucun secret ne va dans le journal ni dans les logs.
4. **Erreurs d'API** au format `{code, message, details}`. Les vues sensibles **retournent** leurs erreurs (401, 423…) au lieu de les lever.
5. **Pas de commande git** qui modifie le dépôt : la coordination s'en charge. Ne modifie pas `docs/architecture-sprint1.md` ; signale plutôt les incohérences.
6. **Rien n'est déployé** sur un serveur sans l'accord explicite du client.

## Tests (détails dans `docs/tests.md`)

- `@pytest.mark.django_db`. La connexion par défaut est `alpha_app`, donc la RLS s'applique.
- Toute requête sur un modèle tenant exige `with contexte_tenant(etab.id):`. Pour le super-admin : `contexte_tenant(None, scope="platform")`.
- Données : `tests.fabriques` (`BanqueFactory`, `PMEFactory`, `SFDFactory`, `UtilisateurFactory`, `RoleFactory`…).
- Fixtures : `etab_a`, `etab_b`, `utilisateur_a`, `utilisateur_b`, `client_api`, `client_connecte(u)`.
- L'alias `proprietaire` ne sert qu'aux contournements volontaires, dans un test transactionnel avec `databases=BASES_PROPRIETAIRE`.
- Avant de rendre une tâche : `pytest`, `ruff check`, `ruff format --check`, `makemigrations --check` et `spectacular --validate --fail-on-warn`. Côté frontend : `lint`, `tsc --noEmit`, `build` et Playwright.

## Organisation du travail (décision du 18/10/2026)

- Au plus **2 agents en parallèle**. Les petites tâches liées sont regroupées dans un même agent.
- **Modèle plus léger** (Sonnet) pour les écrans frontend, les tests et la documentation. Le modèle le plus fort est réservé au code sensible : authentification, isolation, audit et revue de sécurité.
- Chaque tâche se termine par un rapport court : récap en langage simple, fichiers, vérifications réelles et questions.

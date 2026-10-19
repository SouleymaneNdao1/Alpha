<!-- Généré depuis docs/architecture-sprint1.md -->
## 3. Stratégie multi-tenant


Deux barrières indépendantes : (1) filtrage applicatif automatique par le contexte de requête ; (2) Row Level Security PostgreSQL. Une erreur dans l'une est rattrapée par l'autre ; les tests vérifient chacune séparément.

### 3.1 Rôles PostgreSQL

| Rôle | Attributs | Usage |
|---|---|---|
| `postgres` | superuser | uniquement le script d'init du conteneur |
| `alpha_owner` | `LOGIN NOSUPERUSER NOCREATEROLE BYPASSRLS` (+ `CREATEDB` en dev/CI seulement, pour la base de test) | propriétaire de la base, du schéma et des tables ; **uniquement** le service `migrate` et les commandes d'exploitation |
| `alpha_app` | `LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS` | backend, worker, beat ; **jamais propriétaire** d'aucune table, donc soumis à la RLS |

`infra/postgres/init/01-roles.sh` (lit `ALPHA_OWNER_PASSWORD`, `ALPHA_APP_PASSWORD`) :

```sql
CREATE ROLE alpha_owner LOGIN PASSWORD :'owner_pwd' NOSUPERUSER NOCREATEROLE BYPASSRLS;
CREATE ROLE alpha_app   LOGIN PASSWORD :'app_pwd'   NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS;
CREATE DATABASE alpha OWNER alpha_owner;
```

Les droits (stockés par base, donc à rejouer dans la base de test) sont posés par la **migration `tenancy.0001`**, exécutée par `alpha_owner` :

```sql
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO alpha_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alpha_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO alpha_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;          -- EXECUTE accordé fonction par fonction
```

Le nom du rôle applicatif vient du setting `ALPHA_DB_APP_ROLE` (défaut `alpha_app`) et est injecté dans les `RunSQL`.

### 3.2 Variables de session PostgreSQL et fonctions d'accès

| Variable | Valeurs | Positionnée par |
|---|---|---|
| `app.current_tenant` | uuid ou `''` | middleware, tâches Celery, `contexte_tenant()` |
| `app.scope` | `tenant`, `platform`, `worker`, `anonymous` | idem |
| `app.current_user` | uuid ou `''` | middleware (utilisé par les politiques plateforme) |

Toujours en **local à la transaction** (`set_config(…, true)`) : la valeur disparaît au `COMMIT`/`ROLLBACK`, donc aucune fuite d'un établissement à l'autre via une connexion persistante (`CONN_MAX_AGE=60`).

```sql
CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid $$;
CREATE FUNCTION app_scope() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.scope', true), ''), 'anonymous') $$;
CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_user', true), '')::uuid $$;
GRANT EXECUTE ON FUNCTION app_current_tenant(), app_scope(), app_current_user() TO alpha_app;
```

Sans contexte, `app_current_tenant()` vaut NULL et toute politique `etablissement_id = app_current_tenant()` renvoie **zéro ligne** : le système échoue fermé.

### 3.3 Middleware et contexte applicatif

Ordre dans `MIDDLEWARE` :

```
SecurityMiddleware
SessionMiddleware
alpha.core.middleware.RequestIdMiddleware          # request_id, IP réelle (X-Forwarded-For de Caddy, 1 proxy de confiance)
alpha.tenancy.middleware.TenantContextMiddleware   # ouvre la transaction et pose le contexte
CsrfViewMiddleware
AuthenticationMiddleware
alpha.comptes.middleware.SessionActiviteMiddleware # révocation, inactivité, durée max (section 4.8)
alpha.tenancy.middleware.StatutEtablissementMiddleware  # SUSPENDU → 403, LECTURE_SEULE → 423 sur écriture
```

```python
# alpha/tenancy/middleware.py
class TenantContextMiddleware:
    def __call__(self, request):
        tenant_id = request.session.get("tenant_id")      # posé à la connexion
        scope = request.session.get("scope", "anonymous")  # "tenant" | "platform"
        user_id = request.session.get("_auth_user_id")
        with transaction.atomic():                         # transaction la plus externe de la requête
            appliquer_contexte(tenant_id, scope, user_id)  # SELECT set_config(...,true) x3 + contextvars
            response = self.get_response(request)
            if getattr(response, "streaming", False):
                raise ImproperlyConfigured("pas de réponse streaming sous contexte tenant")
        return response
```

- `ATOMIC_REQUESTS = True` en plus : la vue tourne dans un point de sauvegarde imbriqué ; quand DRF lève une `APIException`, seul ce point de sauvegarde est annulé.
- **Règle** : les vues d'authentification **retournent** des `Response(401/423)` au lieu de lever une exception, sinon l'événement d'audit d'échec serait annulé avec la vue.
- `alpha.core.contexte` expose `tenant_courant()`, `scope_courant()`, `utilisateur_courant()`, `ip()`, `request_id()` (contextvars, compatibles threads gunicorn).
- `contexte_tenant(etablissement_id, scope="tenant")` est un gestionnaire de contexte qui repose `set_config` (et rétablit la valeur précédente à la sortie) ; il sert à la connexion (le tenant n'est connu qu'après résolution de l'e-mail), aux tâches Celery et aux opérations de provisionnement du super-admin.

### 3.4 Modèles et managers

```python
# alpha/tenancy/models.py
class TenantManager(models.Manager):
    def get_queryset(self):
        tid = contexte.tenant_courant()
        if tid is None:
            raise TenantNonDefini()                 # fail closed côté application
        return super().get_queryset().filter(etablissement_id=tid)

class TenantModel(models.Model):
    etablissement = models.ForeignKey("tenancy.Etablissement", on_delete=models.RESTRICT, editable=False)
    objects = TenantManager()
    objets_globaux = models.Manager()               # réservé : migrations de données, commandes d'exploitation
    class Meta:
        abstract = True
    def save(self, *a, **kw):
        tid = contexte.tenant_courant()
        if self.etablissement_id is None:
            self.etablissement_id = tid
        elif self.etablissement_id != tid:
            raise ViolationTenant()
        super().save(*a, **kw)
```

- Toutes les tables tenant héritent de `TenantModel`. `Utilisateur` utilise un manager équivalent qui accepte le cas plateforme.
- `objets_globaux` est interdit dans les vues ; un test (ruff, règle personnalisée ou `grep` en CI) vérifie qu'il n'apparaît que dans `management/`, `migrations/` et `plateforme/services.py`. Même s'il est utilisé à tort, la RLS ne renvoie que les lignes du tenant courant.
- Le `_base_manager` de Django (accès par relation) n'est pas filtré par l'application : c'est la RLS qui couvre ce cas.
- Les vues DRF héritent de `TenantViewSet` (queryset via `objects`, `perform_create` sans `etablissement` dans le corps : le champ n'est jamais accepté en entrée).

### 3.5 Politiques RLS

Helper de migration `alpha.tenancy.rls.activer_rls(table)` → `RunSQL` :

```sql
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
CREATE POLICY isolation_tenant ON {t} FOR ALL TO alpha_app
  USING (etablissement_id = app_current_tenant())
  WITH CHECK (etablissement_id = app_current_tenant());
```

Appliqué à : `parametres_etablissement`, `code_secours`*, `jeton_usage_unique`*, `session_appareil`*, `authenticator_totp`*, `historique_mot_de_passe`*, `signalement_telephone_perdu`, `unite_organisationnelle`, `role`, `affectation_role`, `absence`, `delegation`, `tache`, `preferences_notification`*, `notification`*.

(*) Tables pouvant contenir des lignes de super-admin (`etablissement_id` NULL) : politique « tenant ou plateforme » :

```sql
CREATE POLICY isolation_tenant_ou_plateforme ON {t} FOR ALL TO alpha_app
  USING (etablissement_id = app_current_tenant()
         OR (etablissement_id IS NULL AND app_scope() = 'platform' AND utilisateur_id = app_current_user()))
  WITH CHECK (etablissement_id = app_current_tenant()
         OR (etablissement_id IS NULL AND app_scope() = 'platform' AND utilisateur_id = app_current_user()));
```

`utilisateur` :

```sql
CREATE POLICY isolation_utilisateur ON utilisateur FOR ALL TO alpha_app
  USING (etablissement_id = app_current_tenant()
         OR (etablissement_id IS NULL AND app_scope() = 'platform'))
  WITH CHECK (etablissement_id = app_current_tenant()
         OR (etablissement_id IS NULL AND app_scope() = 'platform'));
```

`etablissement` (ni `DELETE` ni `TRUNCATE` accordés à `alpha_app`) :

```sql
REVOKE DELETE, TRUNCATE ON etablissement FROM alpha_app;
CREATE POLICY lecture_etablissement ON etablissement FOR SELECT TO alpha_app
  USING (id = app_current_tenant() OR app_scope() IN ('platform', 'worker'));
CREATE POLICY ecriture_etablissement ON etablissement FOR INSERT TO alpha_app
  WITH CHECK (app_scope() = 'platform');
CREATE POLICY maj_etablissement ON etablissement FOR UPDATE TO alpha_app
  USING (app_scope() = 'platform') WITH CHECK (app_scope() = 'platform');
```

`evenement_audit` : voir 6.3.

**Fonctions `SECURITY DEFINER`** (propriétaire `alpha_owner`, `SET search_path = public, pg_temp`, `REVOKE ALL FROM PUBLIC`, `GRANT EXECUTE TO alpha_app`) : ce sont les seuls passages contrôlés à travers les établissements, et ils ne renvoient que des identifiants.

```sql
-- connexion : résoudre l'établissement à partir de l'e-mail (avant tout contexte)
CREATE FUNCTION alpha_resoudre_connexion(p_email citext)
RETURNS TABLE(utilisateur_id uuid, etablissement_id uuid, est_super_admin boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT id, etablissement_id, est_super_admin FROM utilisateur WHERE email = p_email $$;

-- liens e-mail : résoudre un jeton (activation, réinitialisation, réenrôlement)
CREATE FUNCTION alpha_resoudre_jeton(p_hash char(64))
RETURNS TABLE(jeton_id uuid, etablissement_id uuid, utilisateur_id uuid, objet varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT id, etablissement_id, utilisateur_id, objet FROM jeton_usage_unique
   WHERE jeton_hash = p_hash AND utilise_le IS NULL AND annule_le IS NULL AND expire_le > now() $$;

-- console FYXOP : agrégats techniques, sans contenu
CREATE FUNCTION alpha_stats_etablissements()
RETURNS TABLE(etablissement_id uuid, nb_utilisateurs_actifs int, nb_invites int,
              derniere_activite timestamptz, nb_evenements_audit_30j bigint, dernier_controle_statut varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$ … $$;
-- garde : la fonction lève une exception si app_scope() <> 'platform'
```

Après résolution, le code applicatif appelle `contexte_tenant(etablissement_id)` puis relit l'utilisateur **par le chemin normal** (manager + RLS).

**Test de couverture** (`tests/test_rls_couverture.py`) : interroge `pg_class`/`pg_policies` et échoue si une table possédant une colonne `etablissement_id` n'a pas `relrowsecurity AND relforcerowsecurity` et au moins une politique. Une table ajoutée au S2 sans RLS fait donc échouer la CI.

### 3.6 Migrations

- Exécutées **uniquement** par le service `migrate`, connecté en `alpha_owner` (`DATABASE_URL_OWNER`). Le backend n'a pas les droits DDL.
- `alpha_owner` a `BYPASSRLS` : les migrations de schéma et les migrations de données traversent les établissements sans poser de contexte. `FORCE ROW LEVEL SECURITY` reste utile : si un jour le propriétaire perd `BYPASSRLS`, il est soumis aux politiques au lieu d'en être exempté silencieusement.
- Chaque migration qui crée une table tenant inclut `activer_rls()` dans la **même** migration.
- Les migrations de données utilisent `objets_globaux` et ne déclenchent pas d'envoi (ni e-mail ni tâche Celery).

### 3.7 Tâches de fond (Celery)

```python
@tache_tenant(queue="defaut")                 # décorateur alpha.tenancy.celery
def envoyer_email_invitation(etablissement_id, jeton_id): ...
# le décorateur : with transaction.atomic(): with contexte_tenant(etablissement_id, scope="tenant"): …
```

- Toute tâche liée à un établissement reçoit `etablissement_id` en **premier argument** ; jamais d'objet ORM sérialisé.
- Les tâches transverses (planifiées) ouvrent `contexte_tenant(None, scope="worker")`, ce qui ne donne accès qu'à la **liste** des établissements (politique `lecture_etablissement`), puis rappellent une tâche par établissement (`verifier_chaine_audit.delay(etab_id)`).
- Les envois d'e-mails sont planifiés par `transaction.on_commit(...)` : aucun e-mail pour une transaction annulée.
- Le worker se connecte en `alpha_app`, comme le backend.

### 3.8 Super-administrateur FYXOP

- Compte `utilisateur` avec `est_super_admin=true`, `etablissement_id NULL`, créé **uniquement** par `manage.py creer_super_admin --email …` (lien d'activation envoyé ; MFA obligatoire, comme tout le monde).
- Session : `scope="platform"`, `tenant_id` absent. Inactivité 10 min (non paramétrable), durée max 8 h.
- Accès aux données : `TenantManager` lève `TenantNonDefini` et la RLS renvoie zéro ligne sur toutes les tables tenant ; les permissions DRF `EstUtilisateurEtablissement` refusent (403) toutes les routes hors `/plateforme/`.
- Les vues plateforme ne lisent que `etablissement`, les utilisateurs plateforme, la chaîne d'audit plateforme et `alpha_stats_etablissements()`.
- Seules opérations écrivant dans un établissement, toutes dans `plateforme/services.py` sous `contexte_tenant(cible)` : `provisionner_etablissement` (paramètres, rôles par défaut, unité racine, invitation du premier administrateur), `inviter_administrateur`, `changer_statut`. Chacune est journalisée **deux fois** : dans la chaîne plateforme et dans la chaîne de l'établissement (`acteur_type=SUPER_ADMIN`, catégorie `SUPER_ADMIN`), comme la ligne « Admin FYXOP · Super-admin » du prototype.

---


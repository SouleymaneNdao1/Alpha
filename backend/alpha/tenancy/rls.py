"""SQL de l'isolation multi-tenant, utilisé par les migrations (architecture § 3.1, § 3.2, § 3.5).

Fonctions à appeler dans les ``operations`` d'une migration (elles renvoient des
``migrations.RunSQL`` réversibles) :

- ``droits_par_defaut()`` : extensions, droits sur le schéma, DEFAULT PRIVILEGES
  et rattrapage des tables techniques de Django déjà créées (migration ``tenancy.0001``) ;
- ``fonctions_contexte()`` : ``app_current_tenant()``, ``app_scope()``, ``app_current_user()`` ;
- ``rls_etablissement()`` : politiques spécifiques de la table ``etablissement`` ;
- ``activer_rls(table)`` : RLS activée ET forcée + politique d'isolation, à
  inclure dans LA MÊME migration que la création de toute table tenant (§ 3.6).
  ``activer_rls(table, plateforme=True)`` pour les tables marquées (*) au § 3.5,
  qui peuvent contenir des lignes du super-admin (``etablissement_id`` NULL).

Le rôle applicatif vient du réglage ``ALPHA_DB_APP_ROLE`` (défaut ``alpha_app``).
"""

from __future__ import annotations

import re

from django.conf import settings
from django.db import migrations

_IDENTIFIANT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _ident(nom: str) -> str:
    """Identifiant SQL contrôlé (aucune injection possible dans les RunSQL)."""
    if not _IDENTIFIANT.match(nom):
        raise ValueError(f"Identifiant SQL invalide : {nom!r}.")
    return f'"{nom}"'


def role_app() -> str:
    """Nom (cité) du rôle applicatif soumis à la RLS."""
    return _ident(settings.ALPHA_DB_APP_ROLE)


# --- tenancy.0001 : droits ---------------------------------------------------------------


def sql_droits_par_defaut() -> tuple[str, str]:
    app = role_app()
    avant = f"""
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Schéma : seul le propriétaire crée des objets ; le rôle applicatif y accède.
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO {app};

-- Objets créés ensuite par alpha_owner (toutes les migrations suivantes).
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app};
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO {app};
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Rattrapage (correctif B1) : les tables techniques de Django (django_content_type,
-- auth_*, django_session) sont créées AVANT cette migration (dépendances
-- explicites ci-dessus dans tenancy.0001), donc hors DEFAULT PRIVILEGES.
-- Elles ne sont pas soumises à la RLS.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app};
-- L'historique des migrations n'est écrit que par alpha_owner ; lecture seule
-- pour l'application (vérification « migrations à jour »).
REVOKE ALL ON TABLE django_migrations FROM {app};
GRANT SELECT ON TABLE django_migrations TO {app};

-- Pas de tables temporaires pour le rôle applicatif (il ne crée aucun objet).
DO $$ BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
END $$;
"""
    arriere = f"""
DO $$ BEGIN
  EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database());
END $$;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {app};
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {app};
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  REVOKE USAGE, SELECT ON SEQUENCES FROM {app};
ALTER DEFAULT PRIVILEGES FOR ROLE alpha_owner IN SCHEMA public
  REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {app};
REVOKE USAGE ON SCHEMA public FROM {app};
GRANT USAGE ON SCHEMA public TO PUBLIC;
"""
    return avant, arriere


def droits_par_defaut() -> migrations.RunSQL:
    avant, arriere = sql_droits_par_defaut()
    return migrations.RunSQL(avant, arriere)


# --- tenancy.0001 : fonctions de contexte -------------------------------------------------


def sql_fonctions_contexte() -> tuple[str, str]:
    app = role_app()
    avant = f"""
CREATE FUNCTION app_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_tenant', true), '')::uuid $$;
CREATE FUNCTION app_scope() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.scope', true), ''), 'anonymous') $$;
CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.current_user', true), '')::uuid $$;
REVOKE ALL ON FUNCTION app_current_tenant(), app_scope(), app_current_user() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_current_tenant(), app_scope(), app_current_user() TO {app};
"""
    arriere = """
DROP FUNCTION IF EXISTS app_current_user();
DROP FUNCTION IF EXISTS app_scope();
DROP FUNCTION IF EXISTS app_current_tenant();
"""
    return avant, arriere


def fonctions_contexte() -> migrations.RunSQL:
    avant, arriere = sql_fonctions_contexte()
    return migrations.RunSQL(avant, arriere)


# --- Politiques RLS ------------------------------------------------------------------------


def sql_rls_etablissement() -> tuple[str, str]:
    app = role_app()
    avant = f"""
ALTER TABLE etablissement ENABLE ROW LEVEL SECURITY;
ALTER TABLE etablissement FORCE ROW LEVEL SECURITY;
REVOKE DELETE, TRUNCATE ON etablissement FROM {app};
CREATE POLICY lecture_etablissement ON etablissement FOR SELECT TO {app}
  USING (id = app_current_tenant() OR app_scope() IN ('platform', 'worker'));
CREATE POLICY ecriture_etablissement ON etablissement FOR INSERT TO {app}
  WITH CHECK (app_scope() = 'platform');
CREATE POLICY maj_etablissement ON etablissement FOR UPDATE TO {app}
  USING (app_scope() = 'platform') WITH CHECK (app_scope() = 'platform');
"""
    arriere = """
DROP POLICY IF EXISTS maj_etablissement ON etablissement;
DROP POLICY IF EXISTS ecriture_etablissement ON etablissement;
DROP POLICY IF EXISTS lecture_etablissement ON etablissement;
ALTER TABLE etablissement NO FORCE ROW LEVEL SECURITY;
ALTER TABLE etablissement DISABLE ROW LEVEL SECURITY;
"""
    return avant, arriere


def rls_etablissement() -> migrations.RunSQL:
    avant, arriere = sql_rls_etablissement()
    return migrations.RunSQL(avant, arriere)


def sql_activer_rls(table: str, *, plateforme: bool = False) -> tuple[str, str]:
    t = _ident(table)
    app = role_app()
    if plateforme:
        nom = "isolation_tenant_ou_plateforme"
        condition = (
            "etablissement_id = app_current_tenant()\n"
            "         OR (etablissement_id IS NULL AND app_scope() = 'platform'"
            " AND utilisateur_id = app_current_user())"
        )
    else:
        nom = "isolation_tenant"
        condition = "etablissement_id = app_current_tenant()"
    avant = f"""
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
CREATE POLICY {nom} ON {t} FOR ALL TO {app}
  USING ({condition})
  WITH CHECK ({condition});
"""
    arriere = f"""
DROP POLICY IF EXISTS {nom} ON {t};
ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;
"""
    return avant, arriere


def activer_rls(table: str, *, plateforme: bool = False) -> migrations.RunSQL:
    """RLS activée et forcée + politique d'isolation sur ``table`` (§ 3.5)."""
    avant, arriere = sql_activer_rls(table, plateforme=plateforme)
    return migrations.RunSQL(avant, arriere)

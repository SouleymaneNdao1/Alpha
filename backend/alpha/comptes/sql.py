"""SQL de la migration ``comptes.0001`` (architecture § 3.5, tâche B3).

- ``rls_utilisateur()`` : RLS activée et forcée sur ``utilisateur`` avec la
  politique ``isolation_utilisateur`` (tenant courant, ou super-admins en portée
  « platform »).
- ``fonctions_resolution()`` : ``alpha_resoudre_connexion(citext)`` et
  ``alpha_resoudre_jeton(char(64))``, fonctions ``SECURITY DEFINER`` appartenant à
  ``alpha_owner`` (qui a ``BYPASSRLS``). Ce sont les seuls passages contrôlés à
  travers les établissements : elles ne renvoient que des identifiants (et
  ``est_super_admin`` / ``objet``), jamais d'autre colonne.

Le rôle applicatif vient du réglage ``ALPHA_DB_APP_ROLE`` (validé par ``_ident``).
"""

from __future__ import annotations

from django.db import migrations

from alpha.tenancy.rls import role_app


def sql_rls_utilisateur() -> tuple[str, str]:
    app = role_app()
    condition = (
        "etablissement_id = app_current_tenant()\n"
        "         OR (etablissement_id IS NULL AND app_scope() = 'platform')"
    )
    avant = f"""
ALTER TABLE utilisateur ENABLE ROW LEVEL SECURITY;
ALTER TABLE utilisateur FORCE ROW LEVEL SECURITY;
CREATE POLICY isolation_utilisateur ON utilisateur FOR ALL TO {app}
  USING ({condition})
  WITH CHECK ({condition});
"""
    arriere = """
DROP POLICY IF EXISTS isolation_utilisateur ON utilisateur;
ALTER TABLE utilisateur NO FORCE ROW LEVEL SECURITY;
ALTER TABLE utilisateur DISABLE ROW LEVEL SECURITY;
"""
    return avant, arriere


def rls_utilisateur() -> migrations.RunSQL:
    avant, arriere = sql_rls_utilisateur()
    return migrations.RunSQL(avant, arriere)


def sql_fonctions_resolution() -> tuple[str, str]:
    app = role_app()
    # Seul élément interpolé : le rôle applicatif, validé par _ident (aucune donnée externe).
    avant = f"""
-- Connexion : résoudre l'établissement à partir de l'e-mail, avant tout contexte (P1).
CREATE FUNCTION alpha_resoudre_connexion(p_email citext)
RETURNS TABLE(utilisateur_id uuid, etablissement_id uuid, est_super_admin boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT u.id, u.etablissement_id, u.est_super_admin FROM utilisateur u
   WHERE u.email = p_email $$;

-- Liens e-mail : résoudre un jeton valide (activation, réinitialisation, réenrôlement).
CREATE FUNCTION alpha_resoudre_jeton(p_hash char(64))
RETURNS TABLE(jeton_id uuid, etablissement_id uuid, utilisateur_id uuid, objet varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS
$$ SELECT j.id, j.etablissement_id, j.utilisateur_id, j.objet FROM jeton_usage_unique j
   WHERE j.jeton_hash = p_hash AND j.utilise_le IS NULL AND j.annule_le IS NULL
     AND j.expire_le > now() $$;

REVOKE ALL ON FUNCTION alpha_resoudre_connexion(citext), alpha_resoudre_jeton(char)
  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION alpha_resoudre_connexion(citext), alpha_resoudre_jeton(char)
  TO {app};
"""  # noqa: S608
    arriere = """
DROP FUNCTION IF EXISTS alpha_resoudre_jeton(char);
DROP FUNCTION IF EXISTS alpha_resoudre_connexion(citext);
"""
    return avant, arriere


def fonctions_resolution() -> migrations.RunSQL:
    avant, arriere = sql_fonctions_resolution()
    return migrations.RunSQL(avant, arriere)

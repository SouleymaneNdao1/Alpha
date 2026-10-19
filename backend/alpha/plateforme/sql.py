"""SQL de la migration ``plateforme.0001`` : ``alpha_stats_etablissements`` (§ 3.5, § 3.8, B10).

Fonction ``SECURITY DEFINER`` (propriétaire ``alpha_owner``, qui a ``BYPASSRLS``) : c'est le
SEUL passage par lequel la console FYXOP voit quelque chose des établissements au-delà de la
table ``etablissement``. Elle ne renvoie que des compteurs et des dates techniques, jamais
de contenu (aucun nom, e-mail, tâche ni événement d'audit).

Garde : elle lève ``insufficient_privilege`` sauf en portée « platform » ET pour un
super-administrateur actif (``app_current_user()``). Une tâche de fond (« worker ») ou un
utilisateur d'établissement ne peuvent donc pas l'appeler.

Colonnes renvoyées (une ligne par établissement, ou seulement ``p_etablissement_id``) :

- ``nb_utilisateurs_actifs`` / ``nb_invites`` : comptes ACTIF / INVITE ;
- ``derniere_activite`` : dernière activité d'une session ou dernière connexion ;
- ``nb_evenements_audit_30j`` : volume de la chaîne d'audit sur 30 jours ;
- ``dernier_controle_statut`` : statut du dernier contrôle d'intégrité terminé.
"""

from __future__ import annotations

from django.db import migrations

from alpha.tenancy.rls import role_app

#: Colonnes de ``alpha_stats_etablissements`` (vérifiées par les tests B10).
COLONNES_STATS = (
    "etablissement_id",
    "nb_utilisateurs_actifs",
    "nb_invites",
    "derniere_activite",
    "nb_evenements_audit_30j",
    "dernier_controle_statut",
)


def sql_stats_etablissements() -> tuple[str, str]:
    app = role_app()
    # Seul élément interpolé : le rôle applicatif, validé par _ident (aucune donnée externe).
    avant = f"""
CREATE FUNCTION alpha_stats_etablissements(p_etablissement_id uuid DEFAULT NULL)
RETURNS TABLE(etablissement_id uuid, nb_utilisateurs_actifs int, nb_invites int,
              derniere_activite timestamptz, nb_evenements_audit_30j bigint,
              dernier_controle_statut varchar)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
#variable_conflict use_column
BEGIN
  IF app_scope() IS DISTINCT FROM 'platform' OR NOT EXISTS (
       SELECT 1 FROM utilisateur s
        WHERE s.id = app_current_user() AND s.est_super_admin
          AND s.etablissement_id IS NULL AND s.statut = 'ACTIF') THEN
    RAISE EXCEPTION 'alpha_stats_etablissements est réservée au super-administrateur FYXOP'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN QUERY
  SELECT e.id,
         (SELECT count(*)::int FROM utilisateur u
           WHERE u.etablissement_id = e.id AND u.statut = 'ACTIF'),
         (SELECT count(*)::int FROM utilisateur u
           WHERE u.etablissement_id = e.id AND u.statut = 'INVITE'),
         GREATEST(
           (SELECT max(sa.derniere_activite) FROM session_appareil sa
             WHERE sa.etablissement_id = e.id),
           (SELECT max(u.derniere_connexion) FROM utilisateur u
             WHERE u.etablissement_id = e.id)),
         (SELECT count(*) FROM evenement_audit a
           WHERE a.etablissement_id = e.id AND a.horodatage >= now() - interval '30 days'),
         (SELECT c.statut::varchar FROM controle_integrite_audit c
           WHERE c.etablissement_id = e.id AND c.statut <> 'EN_COURS'
           ORDER BY c.lance_le DESC LIMIT 1)
    FROM etablissement e
   WHERE p_etablissement_id IS NULL OR e.id = p_etablissement_id
   ORDER BY e.code;
END $$;

REVOKE ALL ON FUNCTION alpha_stats_etablissements(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION alpha_stats_etablissements(uuid) TO {app};
"""  # noqa: S608
    arriere = "DROP FUNCTION IF EXISTS alpha_stats_etablissements(uuid);"
    return avant, arriere


def stats_etablissements() -> migrations.RunSQL:
    avant, arriere = sql_stats_etablissements()
    return migrations.RunSQL(avant, arriere)

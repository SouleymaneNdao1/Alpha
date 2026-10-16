"""Couverture RLS (architecture § 3.5) : toute table tenant doit avoir la RLS activée ET forcée.

Échoue si :
- une table d'un modèle héritant de ``TenantModel`` n'a pas ``relrowsecurity``,
  ``relforcerowsecurity`` et au moins une politique visant le rôle applicatif ;
- une table du schéma ``public`` possédant une colonne ``etablissement_id``
  (même hors ``TenantModel``, ex. ``utilisateur`` au S1) est dans le même cas ;
- ``objets_globaux`` est utilisé hors des emplacements autorisés (§ 3.4).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection

from alpha.tenancy.models import TenantModel

pytestmark = pytest.mark.django_db

RACINE = Path(settings.BASE_DIR)


def _etat_rls(table: str) -> tuple[bool, bool, list[str]]:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = %s",
            [table],
        )
        ligne = curseur.fetchone()
        assert ligne is not None, f"Table {table} introuvable."
        curseur.execute(
            "SELECT policyname FROM pg_policies WHERE schemaname = 'public' AND tablename = %s "
            "AND %s = ANY(roles)",
            [table, settings.ALPHA_DB_APP_ROLE],
        )
        politiques = [p for (p,) in curseur.fetchall()]
    return ligne[0], ligne[1], politiques


def _tables_tenant_modeles() -> list[str]:
    return sorted(
        m._meta.db_table
        for m in apps.get_models()
        if issubclass(m, TenantModel) and not m._meta.proxy and m._meta.managed
    )


def _tables_avec_etablissement_id() -> list[str]:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'public' AND c.column_name = 'etablissement_id' "
            "AND t.table_type = 'BASE TABLE' ORDER BY 1"
        )
        return [t for (t,) in curseur.fetchall()]


def test_les_tables_tenant_connues_sont_detectees():
    # Garde-fou du test lui-même : il ne doit pas passer « à vide ».
    assert {"parametres_etablissement", "note_test"} <= set(_tables_tenant_modeles())
    assert {"parametres_etablissement", "note_test"} <= set(_tables_avec_etablissement_id())


def test_rls_activee_et_forcee_sur_toute_table_tenant():
    tables = sorted({*_tables_tenant_modeles(), *_tables_avec_etablissement_id(), "etablissement"})
    defauts = []
    for table in tables:
        active, forcee, politiques = _etat_rls(table)
        if not (active and forcee and politiques):
            defauts.append(
                f"{table} : RLS activée={active}, forcée={forcee}, "
                f"politiques={politiques or 'aucune'}"
            )
    assert not defauts, (
        "Tables tenant sans RLS complète (ajouter activer_rls() dans la migration qui "
        "crée la table) :\n" + "\n".join(defauts)
    )


def test_aucune_table_n_appartient_au_role_applicatif():
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = %s",
            [settings.ALPHA_DB_APP_ROLE],
        )
        assert curseur.fetchall() == []


# objets_globaux : autorisé seulement dans management/, migrations/, plateforme/services.py
# (et dans sa définition, tenancy/models.py).
_AUTORISE = re.compile(r"(^|/)(management|migrations)/|^alpha/plateforme/services\.py$")
_DEFINITION = "alpha/tenancy/models.py"


def test_objets_globaux_limite_aux_emplacements_autorises():
    fautifs = []
    for fichier in sorted((RACINE / "alpha").rglob("*.py")):
        relatif = fichier.relative_to(RACINE).as_posix()
        if relatif == _DEFINITION or _AUTORISE.search(relatif):
            continue
        if "objets_globaux" in fichier.read_text(encoding="utf-8"):
            fautifs.append(relatif)
    assert not fautifs, f"objets_globaux utilisé hors des emplacements autorisés : {fautifs}"

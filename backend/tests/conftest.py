"""Outils communs aux tests (B2).

Connexions disponibles dans config.settings.test :
- ``default``    : alpha_owner (BYPASSRLS), crée et migre la base de test ;
- ``applicatif`` : alpha_app (soumis à la RLS), miroir de la même base.

Une connexion ne voit que les données VALIDÉES par l'autre : les tests qui
utilisent ``applicatif`` sont donc transactionnels (``transaction=True``).
"""

from __future__ import annotations

import pytest

from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement, ParametresEtablissement

ALIAS_APP = "applicatif"
BASES_APP = ["default", ALIAS_APP]


class RouteurApplicatif:
    """Routeur de test : envoie toutes les requêtes ORM sur la connexion alpha_app."""

    def db_for_read(self, model, **hints):
        return ALIAS_APP

    def db_for_write(self, model, **hints):
        return ALIAS_APP

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return None


def creer_etablissement(code: str, **champs) -> Etablissement:
    """Crée un établissement et ses paramètres (connexion propriétaire)."""
    champs.setdefault("raison_sociale", f"Établissement {code}")
    champs.setdefault("type", "BANQUE")
    etablissement = Etablissement.objects.create(code=code, **champs)
    with contexte_tenant(etablissement.id):
        ParametresEtablissement.objects.create()
    return etablissement


@pytest.fixture
def etab_a(db) -> Etablissement:
    return creer_etablissement("banque-a")


@pytest.fixture
def etab_b(db) -> Etablissement:
    return creer_etablissement("sfd-b", type="SFD")

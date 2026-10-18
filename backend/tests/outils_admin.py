"""Outils des tests de l'API d'administration (tâche B7).

La connexion passe par la fixture ``client_connecte`` de T1 (session forgée,
provisoire jusqu'à B5) : rien d'autre à remplacer ici à la livraison de B5.
"""

from __future__ import annotations

import pytest

from alpha.audit.models import EvenementAudit
from alpha.comptes.models import Utilisateur
from alpha.organisation.models import Role
from alpha.organisation.roles_defaut import CODE_ADMINISTRATEUR
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement

from .fabriques import AffectationRoleFactory, BanqueFactory, SFDFactory, UtilisateurFactory

API = "/api/v1/admin"


def role(etablissement: Etablissement, code: str) -> Role:
    with contexte_tenant(etablissement.id):
        return Role.objects.get(code=code)


def creer_admin(etablissement: Etablissement, **champs) -> Utilisateur:
    """Utilisateur ACTIF titulaire du rôle système « Administrateur ALPHA »."""
    champs.setdefault("prenom", "Abdou")
    champs.setdefault("nom", "Kane")
    utilisateur = UtilisateurFactory(etablissement=etablissement, **champs)
    AffectationRoleFactory(
        utilisateur=utilisateur, role=role(etablissement, CODE_ADMINISTRATEUR), principal=True
    )
    return utilisateur


def avec_permissions(etablissement: Etablissement, *codes: str, **champs) -> Utilisateur:
    """Utilisateur ACTIF dont l'unique rôle porte exactement ``codes``."""
    from .fabriques import RoleFactory

    utilisateur = UtilisateurFactory(etablissement=etablissement, **champs)
    r = RoleFactory(etablissement=etablissement, permissions=list(codes))
    AffectationRoleFactory(utilisateur=utilisateur, role=r, principal=True)
    return utilisateur


def evenements(etablissement: Etablissement, action: str | None = None) -> list[EvenementAudit]:
    """Événements d'audit de la chaîne de l'établissement (ordre de la chaîne)."""
    with contexte_tenant(etablissement.id):
        qs = EvenementAudit.objects.order_by("seq")
        if action:
            qs = qs.filter(action=action)
        return list(qs)


def relire(modele, etablissement: Etablissement, **filtres):
    with contexte_tenant(etablissement.id):
        return modele.objects.get(**filtres)


@pytest.fixture
def banque(db) -> Etablissement:
    return BanqueFactory(roles_defaut=True)


@pytest.fixture
def autre_banque(db) -> Etablissement:
    return SFDFactory(roles_defaut=True)


@pytest.fixture
def admin(banque) -> Utilisateur:
    return creer_admin(banque, email="abdou.kane@banque.test")


@pytest.fixture
def client_admin(client_connecte, admin):
    return client_connecte(admin)

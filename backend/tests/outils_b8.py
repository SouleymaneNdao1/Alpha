"""Données de test des tâches, absences et délégations (tâche B8).

``organisation_b8(etab)`` construit, dans un établissement :

    Direction (racine) ─ Agence Plateau (fille)
    analyste : rôle métier sans permission système
    admin    : rôle portant admin.absences

    mamadou  : responsable d'awa, analyste sur la Direction
    awa      : analyste sur l'Agence Plateau (l'absente des scénarios)
    cheikh   : analyste sur la Direction (pouvoirs ≥ awa : délégataire valable)
    fatou    : sans rôle (pouvoirs insuffisants)
    admin    : administrateur des absences (valideur de secours)

Les affectations commencent en 2020 : elles restent « en cours » quand un test fige
l'horloge dans le futur (freezegun).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from alpha.comptes.models import Utilisateur
from alpha.organisation.models import Role, UniteOrganisationnelle
from alpha.tenancy.models import Etablissement

from .fabriques import (
    MOT_DE_PASSE_TEST,
    AffectationRoleFactory,
    RoleFactory,
    UniteOrganisationnelleFactory,
    UtilisateurFactory,
)

DEBUT_AFFECTATIONS = datetime.date(2020, 1, 1)


@dataclass
class OrganisationB8:
    etab: Etablissement
    direction: UniteOrganisationnelle
    agence: UniteOrganisationnelle
    analyste: Role
    role_admin: Role
    mamadou: Utilisateur
    awa: Utilisateur
    cheikh: Utilisateur
    fatou: Utilisateur
    admin: Utilisateur


def _utilisateur(etab, prenom, nom, **champs) -> Utilisateur:
    return UtilisateurFactory(
        etablissement=etab,
        prenom=prenom,
        nom=nom,
        email=f"{prenom.lower()}.{nom.lower()}@{etab.code}.test",
        password=MOT_DE_PASSE_TEST,
        **champs,
    )


def affecter(utilisateur, role, unite=None, principal=False):
    return AffectationRoleFactory(
        utilisateur=utilisateur,
        role=role,
        unite=unite,
        principal=principal,
        debut=DEBUT_AFFECTATIONS,
    )


def organisation_b8(etab: Etablissement) -> OrganisationB8:
    direction = UniteOrganisationnelleFactory(etablissement=etab, code="dir", libelle="Direction")
    agence = UniteOrganisationnelleFactory(
        etablissement=etab, code="plateau", libelle="Agence Plateau", parent=direction
    )
    analyste = RoleFactory(etablissement=etab, code="analyste", libelle="Analyste crédit")
    role_admin = RoleFactory(
        etablissement=etab,
        code="admin-absences",
        libelle="Administrateur des absences",
        permissions=["admin.absences"],
    )
    mamadou = _utilisateur(etab, "Mamadou", "Sow")
    awa = _utilisateur(etab, "Awa", "Diop", responsable=mamadou)
    cheikh = _utilisateur(etab, "Cheikh", "Badiane")
    fatou = _utilisateur(etab, "Fatou", "Ndiaye")
    admin = _utilisateur(etab, "Aissatou", "Admin")
    affecter(mamadou, analyste, direction, principal=True)
    affecter(awa, analyste, agence, principal=True)
    affecter(cheikh, analyste, direction, principal=True)
    affecter(admin, role_admin, principal=True)
    return OrganisationB8(
        etab, direction, agence, analyste, role_admin, mamadou, awa, cheikh, fatou, admin
    )


def instant(texte: str) -> datetime.datetime:
    """Instant ISO 8601 avec fuseau (ex. « 2030-03-10T08:00:00+00:00 »)."""
    valeur = datetime.datetime.fromisoformat(texte)
    assert valeur.tzinfo is not None
    return valeur

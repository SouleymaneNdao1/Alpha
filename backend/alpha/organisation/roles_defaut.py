"""Catalogue des rôles semé à la création d'un établissement (architecture § 2.3).

- Rôles système, pour tout type : « Administrateur ALPHA » (``est_systeme``,
  tous les ``admin.*``) et « Auditeur interne » (``audit.*``).
- Rôles métier selon le type (``BANQUE`` et ``SFD`` partagent le même
  catalogue ; ``PME`` a le sien), sans permission système : ils serviront de
  responsables d'étapes aux circuits S2.

``semer_roles_par_defaut`` est appelé sous ``contexte_tenant(etablissement.id)``
par le provisionnement (``plateforme/services.py``, B10) et par le jeu de
démonstration (B12). Il est idempotent : un code déjà présent n'est pas recréé
ni modifié (l'établissement a pu personnaliser son catalogue).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from alpha.core import contexte
from alpha.tenancy.exceptions import ViolationTenant
from alpha.tenancy.models import Etablissement, TypeEtablissement

from .codes_permission import PERMISSIONS_ADMIN, PERMISSIONS_AUDIT
from .models import Role


@dataclass(frozen=True)
class RoleDefaut:
    code: str
    libelle: str
    permissions: tuple[str, ...] = field(default=())
    est_systeme: bool = False
    description: str = ""


CODE_ADMINISTRATEUR = "administrateur-alpha"
CODE_AUDITEUR = "auditeur-interne"

ROLES_SYSTEME: tuple[RoleDefaut, ...] = (
    RoleDefaut(
        CODE_ADMINISTRATEUR,
        "Administrateur ALPHA",
        PERMISSIONS_ADMIN,
        est_systeme=True,
        description="Administration de l'établissement : utilisateurs, rôles, organisation, "
        "sécurité, absences.",
    ),
    RoleDefaut(
        CODE_AUDITEUR,
        "Auditeur interne",
        PERMISSIONS_AUDIT,
        description="Consultation et export du journal d'audit.",
    ),
)

_ROLES_BANQUE: tuple[RoleDefaut, ...] = (
    RoleDefaut("agent-saisie", "Agent de saisie"),
    RoleDefaut("analyste-credit", "Analyste crédit"),
    RoleDefaut("responsable-credit", "Responsable crédit"),
    RoleDefaut("membre-comite", "Membre du comité"),
    RoleDefaut("chef-service", "Chef de service"),
    RoleDefaut("controle-gestion", "Contrôle de gestion"),
    RoleDefaut("achats", "Achats"),
    RoleDefaut("comptable", "Comptable"),
    RoleDefaut("responsable-rh", "Responsable RH"),
    RoleDefaut("juriste", "Juriste"),
    RoleDefaut("daf", "DAF"),
    RoleDefaut("directeur-general", "Directeur général"),
    RoleDefaut("secretaire-conseil", "Secrétaire du conseil"),
    RoleDefaut("collaborateur", "Collaborateur"),
)

_ROLES_PME: tuple[RoleDefaut, ...] = (
    RoleDefaut("directeur-general", "Directeur général"),
    RoleDefaut("daf", "DAF"),
    RoleDefaut("controleur-gestion", "Contrôleur de gestion"),
    RoleDefaut("comptable-fournisseurs", "Comptable fournisseurs"),
    RoleDefaut("responsable-achats", "Responsable achats"),
    RoleDefaut("directrice-commerciale", "Directrice commerciale"),
    RoleDefaut("chef-service", "Chef de service"),
    RoleDefaut("responsable-rh", "Responsable RH"),
    RoleDefaut("secretaire-conseil", "Secrétaire du conseil"),
    RoleDefaut("collaborateur", "Collaborateur"),
)

ROLES_METIER_PAR_TYPE: dict[str, tuple[RoleDefaut, ...]] = {
    TypeEtablissement.BANQUE: _ROLES_BANQUE,
    TypeEtablissement.SFD: _ROLES_BANQUE,
    TypeEtablissement.PME: _ROLES_PME,
}


def catalogue_par_defaut(type_etablissement: str) -> tuple[RoleDefaut, ...]:
    """Rôles système puis rôles métier du type, dans l'ordre d'affichage."""
    try:
        metier = ROLES_METIER_PAR_TYPE[type_etablissement]
    except KeyError:
        raise ValueError(f"Type d'établissement inconnu : {type_etablissement!r}.") from None
    return (*ROLES_SYSTEME, *metier)


def semer_roles_par_defaut(etablissement: Etablissement) -> list[Role]:
    """Crée les rôles par défaut manquants de l'établissement courant ; renvoie les rôles créés."""
    if etablissement.id != contexte.tenant_courant():
        raise ViolationTenant("Les rôles par défaut se sèment sous le contexte de l'établissement.")
    existants = set(Role.objects.values_list("code", flat=True))
    nouveaux = [
        Role(
            code=r.code,
            libelle=r.libelle,
            description=r.description,
            permissions=list(r.permissions),
            est_systeme=r.est_systeme,
            ordre=ordre,
        )
        for ordre, r in enumerate(catalogue_par_defaut(etablissement.type), start=1)
        if r.code not in existants
    ]
    return Role.objects.bulk_create(nouveaux)

"""Raccordement du journal d'audit aux comptes (réglages B4 branchés par B5).

- ``resoudre_acteur`` (``ALPHA_AUDIT_RESOLVEUR_ACTEUR``) : libellé figé de
  l'utilisateur courant (« Awa Diop »), lu par le chemin normal (manager + RLS) ;
- ``destinataires_audit_lecture`` (``ALPHA_AUDIT_DESTINATAIRES_AUDIT_LECTURE``) :
  adresses des utilisateurs actifs détenant ``audit.lecture`` dans l'établissement
  courant (alerte de rupture de chaîne, § 6.4).
"""

from __future__ import annotations

import uuid

from alpha.audit.models import TypeActeur
from alpha.audit.services import Acteur
from alpha.core import contexte
from alpha.tenancy.exceptions import TenantNonDefini

from .models import StatutUtilisateur, Utilisateur


def resoudre_acteur(utilisateur_id: uuid.UUID) -> Acteur | None:
    try:
        ligne = (
            Utilisateur.objects.filter(pk=utilisateur_id)
            .values("id", "prenom", "nom", "est_super_admin")
            .first()
        )
    except TenantNonDefini:
        return None
    if ligne is None:
        return None
    type_acteur = TypeActeur.SUPER_ADMIN if ligne["est_super_admin"] else TypeActeur.UTILISATEUR
    libelle = f"{ligne['prenom']} {ligne['nom']}".strip()
    return Acteur(type_acteur, ligne["id"], libelle)


def destinataires_audit_lecture(etablissement_id: uuid.UUID) -> list[str]:
    from alpha.organisation.codes_permission import CodePermission
    from alpha.organisation.models import AffectationRole

    if contexte.tenant_courant() != etablissement_id:
        return []
    utilisateurs = (
        AffectationRole.objects.actives()
        .filter(
            role__actif=True,
            role__permissions__contains=[CodePermission.AUDIT_LECTURE.value],
            utilisateur__statut=StatutUtilisateur.ACTIF,
        )
        .values_list("utilisateur__email", flat=True)
        .distinct()
    )
    return sorted(set(utilisateurs))

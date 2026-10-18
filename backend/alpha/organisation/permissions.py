"""Habilitations d'un utilisateur et permissions DRF des routes d'établissement (§ 5, ajout B7).

- ``permissions_de(utilisateur_id)`` : union des codes de permission système
  (§ 2.3) des rôles ACTIFS dont l'utilisateur a une affectation EN COURS
  (``AffectationRole.objects.en_cours()``), dans l'établissement courant.
- ``EstUtilisateurEtablissement`` (« Session » du § 5) : utilisateur d'établissement
  authentifié, ACTIF, dont la session porte le contexte tenant de SON établissement.
  Un super-administrateur FYXOP (portée « platform ») est refusé (403, § 3.8).
- ``Perm(*codes)`` (« Perm(x) » du § 5) : Session + au moins un des codes.

Raccordement B5 : la session « tenant » n'est posée qu'après le MFA (§ 4.2, étape 11) ;
l'état pré-authentifié n'ouvre aucune session Django. Quand B5 livrera
``SessionActiviteMiddleware`` et la clé ``mfa_le``, ces classes pourront être
déplacées dans ``alpha.core.permissions`` (avec ``StepUpTOTP``) sans changer leur
comportement ; les vues d'administration les importent d'ici.
"""

from __future__ import annotations

import uuid

from rest_framework.permissions import BasePermission

from alpha.comptes.models import StatutUtilisateur
from alpha.core import contexte

from .models import AffectationRole

_ATTRIBUT_CACHE = "_alpha_permissions"


def permissions_de(utilisateur_id: uuid.UUID) -> frozenset[str]:
    """Codes de permission système détenus par l'utilisateur (établissement courant)."""
    codes: set[str] = set()
    for perms in (
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id=utilisateur_id, role__actif=True)
        .values_list("role__permissions", flat=True)
    ):
        codes.update(perms or ())
    return frozenset(codes)


def permissions_requete(request) -> frozenset[str]:
    """Permissions de l'utilisateur de la requête, calculées une fois par requête."""
    django_request = getattr(request, "_request", request)
    cache = getattr(django_request, _ATTRIBUT_CACHE, None)
    if cache is None:
        cache = permissions_de(request.user.pk)
        setattr(django_request, _ATTRIBUT_CACHE, cache)
    return cache


class EstUtilisateurEtablissement(BasePermission):
    """« Session » : utilisateur d'établissement connecté, sous le contexte de son établissement."""

    message = "Cette route est réservée aux utilisateurs d'un établissement."

    def has_permission(self, request, view) -> bool:
        utilisateur = request.user
        if not getattr(utilisateur, "is_authenticated", False):
            return False
        if getattr(utilisateur, "est_super_admin", False):
            return False  # § 3.8 : aucune route tenant pour le super-admin FYXOP
        return (
            contexte.scope_courant() == contexte.SCOPE_TENANT
            and contexte.tenant_courant() is not None
            and contexte.tenant_courant() == utilisateur.etablissement_id
            and utilisateur.statut == StatutUtilisateur.ACTIF
        )


def Perm(*codes: str) -> type[BasePermission]:  # notation « Perm(x) » du contrat d'API (§ 5)
    """Permission DRF : Session + au moins un des ``codes`` (« Perm(x) » du § 5)."""
    if not codes:
        raise ValueError("Perm() exige au moins un code de permission.")
    attendus = frozenset(codes)

    class _Perm(EstUtilisateurEtablissement):
        codes_requis = attendus
        message = "Vous n'avez pas les droits nécessaires pour effectuer cette action."

        def has_permission(self, request, view) -> bool:
            if not super().has_permission(request, view):
                return False
            return bool(permissions_requete(request) & attendus)

    _Perm.__name__ = _Perm.__qualname__ = "Perm_" + "_ou_".join(
        sorted(c.replace(".", "_") for c in attendus)
    )
    return _Perm

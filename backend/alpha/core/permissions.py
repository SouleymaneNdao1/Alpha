"""Permissions de base de l'API (architecture § 5).

Politique « fermé par défaut » : ``RefuserTout`` est la permission par défaut de
DRF. Chaque vue DOIT déclarer explicitement ses ``permission_classes`` ; une vue
qui l'oublie est inaccessible au lieu d'être ouverte.

- ``Anonyme`` : aucune condition (vues publiques de ``/auth/``) ;
- ``EstAuthentifie`` : session ouverte (mot de passe ET MFA), établissement ou plateforme ;
- ``Session`` : utilisateur d'établissement authentifié (portée « tenant ») ;
- ``SuperAdmin`` : session plateforme d'un super-administrateur FYXOP ;
- ``StepUpTOTP`` : code TOTP valide exigé dans le champ ``code`` du corps (§ 4.9).
``Perm(x)`` (codes de permission) est ajoutée avec l'administration (B7).
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny, BasePermission

from alpha.core import contexte

# alpha.core.erreurs importe rest_framework.views, qui importe ce module (réglage
# DEFAULT_PERMISSION_CLASSES) : import tardif dans StepUpTOTP pour éviter le cycle.


class RefuserTout(BasePermission):
    """Refuse toute requête : 401 si non authentifié, 403 sinon."""

    message = "Accès refusé."

    def has_permission(self, request, view) -> bool:
        return False


#: Route publique (les vues d'authentification gèrent elles-mêmes leurs refus).
#: Alias exact d'``AllowAny`` : drf-spectacular marque alors l'authentification facultative.
Anonyme = AllowAny


def _authentifie(request) -> bool:
    return bool(getattr(request.user, "is_authenticated", False))


class EstAuthentifie(BasePermission):
    def has_permission(self, request, view) -> bool:
        return _authentifie(request)


class Session(BasePermission):
    """Utilisateur d'établissement authentifié ; un super-admin est refusé (403, § 3.8)."""

    message = "Cette fonction est réservée aux utilisateurs d'un établissement."

    def has_permission(self, request, view) -> bool:
        return (
            _authentifie(request)
            and not request.user.est_super_admin
            and contexte.scope_courant() == contexte.SCOPE_TENANT
            and contexte.tenant_courant() is not None
        )


class SuperAdmin(BasePermission):
    message = "Cette fonction est réservée à la console FYXOP."

    def has_permission(self, request, view) -> bool:
        return (
            _authentifie(request)
            and request.user.est_super_admin
            and contexte.scope_courant() == contexte.SCOPE_PLATFORM
        )


class StepUpTOTP(BasePermission):
    """Action sensible : code TOTP valide exigé dans le corps (champ ``code``, § 4.9).

    - champ absent → 400 ``VALIDATION`` ;
    - trop d'essais (5/min par utilisateur) → 429 ;
    - code faux, rejoué, ou Authenticator suspendu → 401 ``CODE_INVALIDE``.
    Le pas TOTP est consommé (anti-rejeu) : un code utilisé pour se connecter ne
    peut pas resservir. À combiner avec ``Session`` ou ``SuperAdmin``.
    """

    champ = "code"

    def has_permission(self, request, view) -> bool:
        from alpha.comptes import limitation, mfa
        from alpha.core.erreurs import VALIDATION, ErreurApi

        if not _authentifie(request):
            return False
        code = request.data.get(self.champ) if hasattr(request.data, "get") else None
        if not code:
            raise ErreurApi(
                VALIDATION,
                "Certaines données sont invalides.",
                details={self.champ: ["Le code de l'application d'authentification est requis."]},
            )
        limite, fenetre = limitation.STEP_UP_PAR_UTILISATEUR
        attente = limitation.consommer(
            "stepup", str(request.user.pk), limite=limite, fenetre_s=fenetre
        )
        if attente is not None:
            raise ErreurApi(
                "TROP_DE_REQUETES",
                "Trop de tentatives. Patientez avant de réessayer.",
                statut=status.HTTP_429_TOO_MANY_REQUESTS,
                details={"reessayer_dans_s": attente},
            )
        if not mfa.verifier_totp(request.user, str(code)):
            raise ErreurApi(
                "CODE_INVALIDE",
                "Code de vérification invalide ou expiré.",
                statut=status.HTTP_401_UNAUTHORIZED,
            )
        return True

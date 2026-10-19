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


def _session_mfa_active(request) -> bool:
    """Session ouverte par la connexion complète (§ 4.2, étape 11) et encore active.

    Exige la clé ``mfa_le`` (posée seulement après le MFA) et une ``session_appareil``
    non révoquée, liée à cet utilisateur. ``SessionActiviteMiddleware`` fait déjà ce
    contrôle (et l'inactivité / la durée maximale) ; il est répété ici en défense en
    profondeur, pour qu'aucune session forgée (``force_authenticate``, session sans
    MFA) n'ouvre une route.
    """
    from alpha.comptes import sessions

    utilisateur = getattr(request, "user", None)
    if not getattr(utilisateur, "is_authenticated", False):
        return False
    session = getattr(request, "session", None)
    if session is None or not session.get("mfa_le") or not session.session_key:
        return False
    etat = sessions.etat_session(session.session_key)
    return etat is not None and not etat.revoquee and etat.utilisateur_id == utilisateur.pk


def _authentifie(request) -> bool:
    return _session_mfa_active(request)


class EstAuthentifie(BasePermission):
    """Session MFA active, établissement ou plateforme."""

    def has_permission(self, request, view) -> bool:
        return _authentifie(request)


class Session(BasePermission):
    """« Session » du § 5 : utilisateur d'établissement ACTIF, session MFA active, sous le
    contexte de SON établissement. Un super-admin FYXOP est refusé (403, § 3.8)."""

    message = "Cette route est réservée aux utilisateurs d'un établissement."

    def has_permission(self, request, view) -> bool:
        from alpha.comptes.models import StatutUtilisateur

        if not _authentifie(request):
            return False
        utilisateur = request.user
        if getattr(utilisateur, "est_super_admin", False):
            return False
        return (
            contexte.scope_courant() == contexte.SCOPE_TENANT
            and contexte.tenant_courant() is not None
            and contexte.tenant_courant() == utilisateur.etablissement_id
            and utilisateur.statut == StatutUtilisateur.ACTIF
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
    Implémentation : ``alpha.comptes.mfa.verifier_step_up`` (pas consommé, refus
    journalisés hors transaction). À combiner avec ``Session`` ou ``SuperAdmin``.
    """

    champ = "code"

    def has_permission(self, request, view) -> bool:
        from alpha.comptes import mfa
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
        resultat, attente = mfa.verifier_step_up(request.user, str(code))
        if resultat == mfa.STEP_UP_TROP_DE_REQUETES:
            raise ErreurApi(
                "TROP_DE_REQUETES",
                "Trop de tentatives. Patientez avant de réessayer.",
                statut=status.HTTP_429_TOO_MANY_REQUESTS,
                details={"reessayer_dans_s": attente},
            )
        if resultat != mfa.STEP_UP_OK:
            raise ErreurApi(
                "CODE_INVALIDE",
                "Code de vérification invalide ou expiré.",
                statut=status.HTTP_401_UNAUTHORIZED,
            )
        return True

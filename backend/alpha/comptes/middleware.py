"""``SessionActiviteMiddleware`` (architecture § 3.3, § 4.8).

Placé après ``AuthenticationMiddleware`` et avant ``StatutEtablissementMiddleware``,
il s'exécute DANS la transaction ouverte par ``TenantContextMiddleware`` et sous
le contexte de la session. Pour toute requête authentifiée (MFA faite) :

1. recherche de la ``session_appareil`` par SHA-256 de la clé de session (cache 60 s) ;
2. absente ou révoquée → ``flush()`` et 401 ``SESSION_EXPIREE`` ;
3. inactivité supérieure au réglage de l'établissement (10 min pour le super-admin)
   → révocation ``INACTIVITE``, audit ``auth.session.expiree``, 401 ;
4. durée maximale dépassée → révocation ``EXPIRATION``, audit, 401 ;
5. sinon mise à jour de ``derniere_activite``, au plus une écriture par minute,
   sauf pour les appels de fond (en-tête ``X-Alpha-Fond: 1``), qui ne prolongent pas
   l'inactivité.

La réponse 401 est RETOURNÉE (pas d'exception) : la révocation et l'événement
d'audit sont validés avec la transaction.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.core.erreurs import corps_erreur

from . import sessions
from .connexion import regles_courantes
from .models import MotifFinSession, SessionAppareil

SESSION_EXPIREE = "SESSION_EXPIREE"
MESSAGE_SESSION_EXPIREE = "Votre session a expiré. Reconnectez-vous."
ENTETE_FOND = "X-Alpha-Fond"
INTERVALLE_ECRITURE = datetime.timedelta(minutes=1)


def reponse_session_expiree() -> JsonResponse:
    return JsonResponse(
        corps_erreur(SESSION_EXPIREE, MESSAGE_SESSION_EXPIREE),
        status=401,
        json_dumps_params={"ensure_ascii": False},
    )


class SessionActiviteMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        session = request.session
        if not session.get("_auth_user_id"):
            return self.get_response(request)
        cle = session.session_key
        etat = sessions.etat_session(cle) if cle else None
        if (
            etat is None
            or etat.revoquee
            or str(etat.utilisateur_id) != str(session.get("_auth_user_id"))
        ):
            session.flush()
            return reponse_session_expiree()

        maintenant = timezone.now()
        regles = regles_courantes()
        motif = None
        if maintenant > etat.expire_le:
            motif = MotifFinSession.EXPIRATION
        elif maintenant - etat.derniere_activite > regles.inactivite:
            motif = MotifFinSession.INACTIVITE
        if motif is not None:
            self._expirer(etat.id, motif)
            session.flush()
            return reponse_session_expiree()

        fond = request.headers.get(ENTETE_FOND) == "1"
        if not fond and maintenant - etat.derniere_activite >= INTERVALLE_ECRITURE:
            sessions.noter_activite(cle, etat)
        return self.get_response(request)

    @staticmethod
    def _expirer(session_id, motif: str) -> None:
        appareil = SessionAppareil.objects.select_for_update().filter(id=session_id).first()
        if appareil is None:
            return
        sessions.revoquer_session(appareil, motif)
        journaliser(
            "auth.session.expiree",
            Categorie.CONNEXION,
            objet=appareil,
            objet_libelle=appareil.appareil,
            apres={"motif": motif},
            detail=(
                "Session expirée après inactivité"
                if motif == MotifFinSession.INACTIVITE
                else "Session expirée (durée maximale atteinte)"
            ),
        )

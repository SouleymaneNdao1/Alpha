"""API d'administration des signalements « téléphone perdu » (§ 4.5, § 5.5 ; tâche B6).

``Perm("admin.utilisateurs")`` (le super-admin FYXOP est refusé, § 3.8) ; un signalement
d'un autre établissement donne 404. Les actions exigent le step-up TOTP de
l'administrateur (champ ``code``) et sont interdites sur son propre signalement.
Les refus sont journalisés hors transaction et RETOURNÉS (§ 3.3).
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.audit.models import Categorie
from alpha.audit.services import journaliser
from alpha.core.erreurs import ErreurApi, reponse_erreur
from alpha.core.pagination import PaginationPage
from alpha.core.schema_erreurs import ErreurSerializer, erreurs
from alpha.organisation.codes_permission import CodePermission
from alpha.organisation.permissions import Perm

from . import mfa, telephone
from .models import SignalementTelephonePerdu, StatutSignalement
from .serializers_parcours import (
    AnnulationSignalementSerializer,
    ErreurAutoTraitementSerializer,
    PageSignalementsSerializer,
    ReinitialisationSignalementSerializer,
    SignalementTelephoneSerializer,
)

TAG = "Administration · utilisateurs"
CODE_INVALIDE = "CODE_INVALIDE"


def _depuis(erreur: ErreurApi) -> Response:
    return reponse_erreur(
        erreur.code, erreur.message, statut=erreur.status_code, details=erreur.details
    )


def _introuvable() -> Response:
    return reponse_erreur("INTROUVABLE", statut=status.HTTP_404_NOT_FOUND)


def _signalement(signalement_id) -> SignalementTelephonePerdu | None:
    return (
        SignalementTelephonePerdu.objects.select_related("utilisateur")
        .filter(pk=signalement_id)
        .first()
    )


def _controles(request, signalement: SignalementTelephonePerdu) -> Response | None:
    """Auto-traitement, statut, puis step-up : refus journalisés hors transaction, sans écriture."""
    try:
        telephone.verifier_traitement(signalement, request.user)
    except ErreurApi as erreur:
        if erreur.code == telephone.AUTO_TRAITEMENT_INTERDIT:
            journaliser(
                "telephone.auto_traitement_refuse",
                Categorie.SECURITE,
                objet=signalement,
                objet_libelle=signalement.utilisateur.nom_complet,
                detail="Tentative de traitement de son propre signalement refusée",
                acteur=request.user,
                hors_transaction=True,
            )
        return _depuis(erreur)
    resultat, attente = mfa.verifier_step_up(request.user, str(request.data.get("code", "")))
    if resultat == mfa.STEP_UP_TROP_DE_REQUETES:
        return reponse_erreur(
            "TROP_DE_REQUETES",
            statut=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"reessayer_dans_s": attente},
            entetes={"Retry-After": str(attente)},
        )
    if resultat != mfa.STEP_UP_OK:
        return reponse_erreur(
            CODE_INVALIDE,
            "Code de vérification invalide ou expiré.",
            statut=status.HTTP_401_UNAUTHORIZED,
        )
    return None


ERREURS_ACTION = {
    **erreurs(400, 404, 409, 429, r409="SIGNALEMENT_DEJA_TRAITE."),
    401: OpenApiResponse(ErreurSerializer, description="CODE_INVALIDE (step-up) ou non connecté."),
    403: OpenApiResponse(
        ErreurAutoTraitementSerializer,
        description="AUTO_TRAITEMENT_INTERDIT {recours_fyxop} ou permission refusée.",
    ),
}


class VueSignalements(APIView):
    permission_classes = [Perm(CodePermission.ADMIN_UTILISATEURS)]


class SignalementsVue(VueSignalements):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_signalements_telephone_liste",
        summary="Signalements « téléphone perdu »",
        parameters=[
            OpenApiParameter("statut", OpenApiTypes.STR, enum=StatutSignalement.values),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("taille", OpenApiTypes.INT, description="25 par défaut, 100 au plus."),
        ],
        responses={200: PageSignalementsSerializer, **erreurs(400)},
    )
    def get(self, request):
        qs = SignalementTelephonePerdu.objects.select_related("utilisateur").order_by(
            "-signale_le", "id"
        )
        statut = request.query_params.get("statut")
        if statut:
            if statut not in StatutSignalement.values:
                return reponse_erreur(
                    "VALIDATION", details={"statut": ["Statut inconnu."]}, statut=400
                )
            qs = qs.filter(statut=statut)
        paginateur = PaginationPage()
        page = paginateur.paginate_queryset(qs, request, view=self)
        return paginateur.get_paginated_response([telephone.presenter(s) for s in page])


class ReinitialiserSignalementVue(VueSignalements):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_signalement_telephone_reinitialiser",
        summary="Réinitialiser l'application d'authentification après vérification d'identité",
        description="Par un administrateur AUTRE que l'intéressé, après vérification hors ligne "
        "(`mode_verification`). Effets : Authenticator révoqué, codes de secours invalidés, "
        "sessions révoquées, tâche terminée, lien de réenrôlement (24 h) envoyé par e-mail. La "
        "signature reste bloquée jusqu'au réenrôlement. Step-up : `code` TOTP de "
        "l'administrateur.",
        request=ReinitialisationSignalementSerializer,
        responses={200: SignalementTelephoneSerializer, **ERREURS_ACTION},
    )
    def post(self, request, signalement_id):
        corps = ReinitialisationSignalementSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        signalement = _signalement(signalement_id)
        if signalement is None:
            return _introuvable()
        refus = _controles(request, signalement)
        if refus is not None:
            return refus
        signalement = telephone.reinitialiser(
            signalement,
            par=request.user,
            mode_verification=corps.validated_data["mode_verification"],
            commentaire=corps.validated_data["commentaire"],
        )
        return Response(telephone.presenter(signalement))


class AnnulerSignalementVue(VueSignalements):
    @extend_schema(
        tags=[TAG],
        operation_id="admin_signalement_telephone_annuler",
        summary="Annuler un signalement (téléphone retrouvé)",
        description="Réactive l'application d'authentification suspendue et débloque la "
        "signature. Step-up : `code` TOTP de l'administrateur.",
        request=AnnulationSignalementSerializer,
        responses={200: SignalementTelephoneSerializer, **ERREURS_ACTION},
    )
    def post(self, request, signalement_id):
        corps = AnnulationSignalementSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        signalement = _signalement(signalement_id)
        if signalement is None:
            return _introuvable()
        refus = _controles(request, signalement)
        if refus is not None:
            return refus
        signalement = telephone.annuler(
            signalement, par=request.user, commentaire=corps.validated_data["commentaire"]
        )
        return Response(telephone.presenter(signalement))

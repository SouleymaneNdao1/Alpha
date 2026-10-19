"""API de la console FYXOP : ``/api/v1/plateforme/`` (architecture § 5.7, § 3.8, tâche B10).

Toutes les routes exigent ``SuperAdmin`` (session plateforme d'un super-administrateur, MFA) :
un utilisateur d'établissement reçoit 403. Les écritures exigent en plus un code TOTP de
confirmation (step-up, § 4.9) vérifié par ``alpha.comptes.mfa.verifier_step_up`` APRÈS les
contrôles préalables (un code n'est pas gaspillé sur une requête vouée à l'échec).

Règles :
- aucune lecture de contenu : la console ne voit que la table ``etablissement``, les
  compteurs de ``alpha_stats_etablissements()``, la chaîne d'audit de la plateforme et le
  profil du super-administrateur ;
- les erreurs sont RETOURNÉES (``reponse_erreur``), jamais levées : les refus de step-up
  journalisés et les écritures déjà faites ne sont pas annulés par une exception.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import exceptions, status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.audit import filtres
from alpha.audit.models import EvenementAudit
from alpha.audit.pagination import PaginationCurseurJournal
from alpha.audit.serializers import EvenementAuditSerializer, presenter_evenement
from alpha.comptes import mfa
from alpha.comptes.serializers import MoiSerializer, donnees_moi
from alpha.core.erreurs import (
    TROP_DE_REQUETES,
    VALIDATION,
    ErreurApi,
    reponse_erreur,
)
from alpha.core.permissions import SuperAdmin
from alpha.core.schema_erreurs import ErreurSerializer, erreurs
from alpha.tenancy.models import Etablissement

from . import services
from .serializers import (
    AdministrateurInviteSerializer,
    EtablissementConsoleSerializer,
    EtablissementDetailSerializer,
    FiltresEtablissementsSerializer,
    InvitationAdministrateurSerializer,
    ModificationEtablissementSerializer,
    ProvisionnementReponseSerializer,
    ProvisionnementSerializer,
    ReinitialisationAuthenticatorSerializer,
    ReinitialisationReponseSerializer,
)

TAG = "Console FYXOP"
CODE_INVALIDE = "CODE_INVALIDE"

STATS_VIDES = {
    "nb_utilisateurs_actifs": 0,
    "nb_invites": 0,
    "derniere_activite": None,
    "nb_evenements_audit_30j": 0,
    "dernier_controle_statut": None,
}

R401_STEP_UP = OpenApiResponse(
    ErreurSerializer, description="Non authentifié, ou CODE_INVALIDE (code TOTP refusé)."
)
R429 = OpenApiResponse(
    ErreurSerializer, description="TROP_DE_REQUETES : trop de codes essayés (5 par minute)."
)


# --- Outils -----------------------------------------------------------------------------------


def _texte(valeur: Any) -> Any:
    if isinstance(valeur, dict):
        return {cle: _texte(v) for cle, v in valeur.items()}
    if isinstance(valeur, list):
        return [_texte(v) for v in valeur]
    return str(valeur)


def _validation(detail: Any) -> Response:
    details = _texte(detail) if isinstance(detail, dict) else {"non_field_errors": _texte(detail)}
    return reponse_erreur(VALIDATION, details=details)


def _valider(classe, donnees) -> tuple[dict | None, Response | None]:
    entree = classe(data=donnees)
    if entree.is_valid():
        return dict(entree.validated_data), None
    return None, _validation(entree.errors)


def _erreur(erreur: ErreurApi) -> Response:
    return reponse_erreur(
        erreur.code, erreur.message, statut=erreur.status_code, details=erreur.details
    )


def _step_up(request, code: str) -> Response | None:
    """``None`` si le code TOTP est accepté, sinon la réponse 401 / 429 à RETOURNER."""
    resultat, attente = mfa.verifier_step_up(request.user, code)
    if resultat == mfa.STEP_UP_OK:
        return None
    if resultat == mfa.STEP_UP_TROP_DE_REQUETES:
        return reponse_erreur(
            TROP_DE_REQUETES,
            statut=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"reessayer_dans_s": attente},
        )
    return reponse_erreur(
        CODE_INVALIDE,
        "Code de vérification invalide ou expiré.",
        statut=status.HTTP_401_UNAUTHORIZED,
    )


def presenter(etablissement: Etablissement, stats: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": etablissement.id,
        "code": etablissement.code,
        "raison_sociale": etablissement.raison_sociale,
        "type": etablissement.type,
        "statut": etablissement.statut,
        "cree_le": etablissement.cree_le,
        "stats": {**STATS_VIDES, **(stats or {})},
    }


def presenter_detail(etablissement: Etablissement) -> dict[str, Any]:
    stats = services.statistiques(etablissement.id).get(etablissement.id)
    return {
        **presenter(etablissement, stats),
        "pays": etablissement.pays,
        "fuseau_horaire": etablissement.fuseau_horaire,
        "modifie_le": etablissement.modifie_le,
        "suspension_manuelle_disponible": services.suspension_manuelle_active(),
    }


def _administrateur(utilisateur) -> dict[str, Any]:
    return {
        "id": utilisateur.id,
        "email": utilisateur.email,
        "prenom": utilisateur.prenom,
        "nom": utilisateur.nom,
        "statut": utilisateur.statut,
    }


# --- Établissements ---------------------------------------------------------------------------


class EtablissementsVue(APIView):
    permission_classes = [SuperAdmin]

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_etablissements_liste",
        summary="Établissements (métadonnées et compteurs, sans contenu)",
        parameters=[FiltresEtablissementsSerializer],
        responses={200: EtablissementConsoleSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        criteres, refus = _valider(FiltresEtablissementsSerializer, request.query_params)
        if refus is not None:
            return refus
        qs = Etablissement.objects.all().order_by("code")
        if texte := criteres.get("q"):
            qs = qs.filter(Q(code__icontains=texte) | Q(raison_sociale__icontains=texte))
        if statut := criteres.get("statut"):
            qs = qs.filter(statut=statut)
        stats = services.statistiques()
        return Response([presenter(e, stats.get(e.id)) for e in qs])

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_etablissements_provisionner",
        summary="Provisionner un établissement (code TOTP requis)",
        description="Crée l'établissement, ses paramètres par défaut, son catalogue de rôles et "
        "son unité racine « Direction générale », puis invite son premier administrateur "
        "(rôle « Administrateur ALPHA », e-mail d'activation). Le code TOTP de confirmation "
        "est `code_totp` (`code` est le code de l'établissement). Double journalisation : "
        "chaîne de la plateforme et chaîne de l'établissement.",
        request=ProvisionnementSerializer,
        responses={
            201: ProvisionnementReponseSerializer,
            **erreurs(400, 409, r409="CODE_EXISTE ou EMAIL_EXISTE."),
            401: R401_STEP_UP,
            429: R429,
        },
    )
    def post(self, request):
        donnees, refus = _valider(ProvisionnementSerializer, request.data)
        if refus is not None:
            return refus
        code_totp = donnees.pop("code_totp")
        try:
            services.verifier_disponibilite(
                code=donnees["code"], email=donnees["administrateur"]["email"]
            )
        except ErreurApi as erreur:
            return _erreur(erreur)
        if (refus := _step_up(request, code_totp)) is not None:
            return refus
        try:
            etablissement, admin = services.provisionner_etablissement(par=request.user, **donnees)
        except ErreurApi as erreur:
            return _erreur(erreur)
        return Response(
            {**presenter_detail(etablissement), "administrateur": _administrateur(admin)},
            status=status.HTTP_201_CREATED,
        )


class EtablissementVue(APIView):
    permission_classes = [SuperAdmin]

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_etablissement_lire",
        summary="Établissement (métadonnées et compteurs, aucun contenu)",
        responses={200: EtablissementDetailSerializer, **erreurs(404)},
    )
    def get(self, request, etablissement_id):
        try:
            etablissement = services.etablissement_ou_404(etablissement_id)
        except ErreurApi as erreur:
            return _erreur(erreur)
        return Response(presenter_detail(etablissement))

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_etablissement_modifier",
        summary="Modifier la raison sociale ou le statut (code TOTP requis)",
        description="`statut` (ACTIF, LECTURE_SEULE, SUSPENDU) n'est accepté que si la "
        "suspension manuelle est activée sur la plateforme (décision P6, réglage "
        "`ALPHA_PLATEFORME_SUSPENSION_MANUELLE`, désactivé par défaut), sinon 403 "
        f"`{services.SUSPENSION_DESACTIVEE}` ; `motif` est alors obligatoire. Une suspension "
        "révoque toutes les sessions ouvertes de l'établissement.",
        request=ModificationEtablissementSerializer,
        responses={
            200: EtablissementDetailSerializer,
            **erreurs(
                400,
                404,
                409,
                r403=f"Permission refusée, ou {services.SUSPENSION_DESACTIVEE}.",
                r409="ETABLISSEMENT_ARCHIVE.",
            ),
            401: R401_STEP_UP,
            429: R429,
        },
    )
    def patch(self, request, etablissement_id):
        donnees, refus = _valider(ModificationEtablissementSerializer, request.data)
        if refus is not None:
            return refus
        code_totp = donnees.pop("code")
        if "raison_sociale" not in donnees and "statut" not in donnees:
            return _validation({"non_field_errors": ["Indiquez raison_sociale ou statut."]})
        try:
            etablissement = services.etablissement_ou_404(etablissement_id)
            services.controler_modification(
                etablissement, statut=donnees.get("statut"), motif=donnees.get("motif", "")
            )
        except ErreurApi as erreur:
            return _erreur(erreur)
        if (refus := _step_up(request, code_totp)) is not None:
            return refus
        try:
            etablissement = services.modifier_etablissement(
                etablissement_id, par=request.user, **donnees
            )
        except ErreurApi as erreur:
            return _erreur(erreur)
        return Response(presenter_detail(etablissement))


class AdministrateursVue(APIView):
    permission_classes = [SuperAdmin]

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_etablissement_inviter_administrateur",
        summary="Inviter un administrateur de l'établissement (code TOTP requis)",
        description="Invitation sur le rôle « Administrateur ALPHA » (e-mail d'activation). "
        "Double journalisation `plateforme.administrateur.invite`.",
        request=InvitationAdministrateurSerializer,
        responses={
            201: AdministrateurInviteSerializer,
            **erreurs(400, 404, 409, r409="EMAIL_EXISTE ou ETABLISSEMENT_ARCHIVE."),
            401: R401_STEP_UP,
            429: R429,
        },
    )
    def post(self, request, etablissement_id):
        donnees, refus = _valider(InvitationAdministrateurSerializer, request.data)
        if refus is not None:
            return refus
        code_totp = donnees.pop("code")
        try:
            etablissement = services.etablissement_ou_404(etablissement_id)
            services.verifier_disponibilite(email=donnees["email"])
        except ErreurApi as erreur:
            return _erreur(erreur)
        if (refus := _step_up(request, code_totp)) is not None:
            return refus
        try:
            admin = services.inviter_administrateur(etablissement.id, par=request.user, **donnees)
        except ErreurApi as erreur:
            return _erreur(erreur)
        return Response(_administrateur(admin), status=status.HTTP_201_CREATED)


class ReinitialisationAuthenticatorVue(APIView):
    permission_classes = [SuperAdmin]

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_etablissement_reinitialiser_authenticator",
        summary="Réinitialiser l'Authenticator du dernier administrateur (P4, code TOTP requis)",
        description="Sur demande écrite signée de la direction du client et après appel vidéo "
        "avec pièce d'identité. L'administrateur est désigné par son adresse e-mail. Refusé "
        "(409 AUTRE_ADMINISTRATEUR_DISPONIBLE) si un autre administrateur actif peut traiter "
        "le cas. Lien de réenrôlement envoyé à l'intéressé, autres administrateurs notifiés, "
        "double journalisation.",
        request=ReinitialisationAuthenticatorSerializer,
        responses={
            200: ReinitialisationReponseSerializer,
            **erreurs(
                400,
                404,
                409,
                r400="VALIDATION ou REFERENCE_OBLIGATOIRE.",
                r404="Établissement inconnu, ou adresse étrangère à l'établissement.",
                r409="PAS_ADMINISTRATEUR, AUTRE_ADMINISTRATEUR_DISPONIBLE ou "
                "ETABLISSEMENT_ARCHIVE.",
            ),
            401: R401_STEP_UP,
            429: R429,
        },
    )
    def post(self, request, etablissement_id):
        donnees, refus = _valider(ReinitialisationAuthenticatorSerializer, request.data)
        if refus is not None:
            return refus
        code_totp = donnees.pop("code")
        try:
            services.etablissement_ou_404(etablissement_id)
        except ErreurApi as erreur:
            return _erreur(erreur)
        if (refus := _step_up(request, code_totp)) is not None:
            return refus
        try:
            signalement = services.reinitialiser_authenticator(
                etablissement_id, par=request.user, **donnees
            )
        except ErreurApi as erreur:
            return _erreur(erreur)
        return Response(
            {
                "signalement_id": signalement.id,
                "statut": signalement.statut,
                "traite_le": signalement.traite_le,
            }
        )


# --- Journal de la plateforme et profil -------------------------------------------------------


class AuditPlateformeVue(GenericAPIView):
    permission_classes = [SuperAdmin]
    serializer_class = EvenementAuditSerializer
    pagination_class = PaginationCurseurJournal

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_audit_liste",
        summary="Journal de la plateforme (chaîne FYXOP, plus récent d'abord)",
        description="Mêmes filtres et même pagination par curseur que `/audit/evenements`. "
        "Seule la chaîne de la plateforme est lisible (jamais celle d'un établissement).",
        parameters=[filtres.FiltresJournalSerializer],
        responses={200: EvenementAuditSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        try:
            criteres = filtres.lire_filtres(request.query_params)
            qs = filtres.appliquer_filtres(
                EvenementAudit.objects.filter(etablissement_id__isnull=True), criteres
            )
            page = self.paginate_queryset(qs)
        except exceptions.ValidationError as erreur:
            return _validation(erreur.detail)
        return self.get_paginated_response([presenter_evenement(e) for e in page])


class MoiPlateformeVue(APIView):
    permission_classes = [SuperAdmin]

    @extend_schema(
        tags=[TAG],
        operation_id="plateforme_moi",
        summary="Profil du super-administrateur connecté",
        responses={200: MoiSerializer, **erreurs()},
    )
    def get(self, request):
        return Response(donnees_moi(request.user))

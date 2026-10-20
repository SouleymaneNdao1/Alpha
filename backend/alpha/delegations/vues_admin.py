"""Administration des absences et délégations de l'établissement (§ 5.5, tâche B13).

Routes, montées sous ``/api/v1/admin/`` :

- ``GET  /admin/absences`` : liste filtrable (``admin.absences``) ;
- ``POST /admin/absences`` : déclaration pour le compte d'un utilisateur (``admin.absences``) ;
- ``GET  /admin/absences/candidats`` : absents ou délégataires possibles, avec le contrôle
  P5 par rapport à ``pour`` (``admin.absences``) ;
- ``GET  /admin/delegations`` : liste filtrable (``admin.absences`` ou ``admin.utilisateurs``) ;
- ``POST /admin/delegations/{id}/revoquer`` : révocation motivée (``admin.absences``).

La validation et le refus d'une absence passent par les routes existantes
``POST /absences/{id}/valider|refuser`` (§ 5.4), ouvertes à ``admin.absences`` : une seule
implémentation des règles P5. Toutes les écritures réutilisent ``alpha.delegations.services``
(journalisées). L'isolation tient à la RLS : un objet d'un autre établissement répond 404.
Le super-admin FYXOP est refusé (403) par la permission de session.
"""

from __future__ import annotations

import datetime

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.comptes.models import StatutUtilisateur, Utilisateur
from alpha.core.erreurs import INTROUVABLE, VALIDATION, reponse_erreur
from alpha.core.pagination import PaginationPage
from alpha.core.schema_erreurs import erreurs
from alpha.organisation.permissions import AdminAbsences, AdminDelegationsLecture

from . import services
from .models import Delegation, StatutAbsence, StatutDelegation
from .serializers import (
    AbsenceAdminSerializer,
    AbsenceDetailSerializer,
    CandidatSerializer,
    CreationAbsenceAdminSerializer,
    DelegationAdminSerializer,
    FiltresAbsencesAdminSerializer,
    FiltresDelegationsAdminSerializer,
    RevocationSerializer,
)
from .vues import _absences, _delegations_par_absence, _detail, lister_candidats

TAG = "Administration · absences et délégations"

_PARAMETRES_COMMUNS = [
    OpenApiParameter("du", OpenApiTypes.DATE, description="Période chevauchant ce jour ou après."),
    OpenApiParameter("au", OpenApiTypes.DATE, description="Période chevauchant ce jour ou avant."),
    OpenApiParameter(
        "utilisateur_id",
        OpenApiTypes.UUID,
        description="Absent (absences) ; délégant ou délégataire (délégations).",
    ),
    OpenApiParameter("page", OpenApiTypes.INT),
    OpenApiParameter("taille", OpenApiTypes.INT),
]


def _debut_du_jour(jour: datetime.date) -> datetime.datetime:
    return timezone.make_aware(datetime.datetime.combine(jour, datetime.time.min))


def _filtrer_periode(qs, filtres: dict):
    """Périodes [debut, fin) qui chevauchent les jours [du, au] (fuseau de l'établissement)."""
    if filtres.get("du"):
        qs = qs.filter(fin__gt=_debut_du_jour(filtres["du"]))
    if filtres.get("au"):
        qs = qs.filter(debut__lt=_debut_du_jour(filtres["au"] + datetime.timedelta(days=1)))
    return qs


def _filtres(classe, request):
    """``(filtres, None)`` ou ``(None, réponse 400)``."""
    serializer = classe(data=request.query_params)
    if not serializer.is_valid():
        return None, reponse_erreur(VALIDATION, details=serializer.errors)
    return serializer.validated_data, None


class AbsencesAdminVue(APIView):
    permission_classes = [AdminAbsences]

    @extend_schema(
        tags=[TAG],
        operation_id="admin_absences_liste",
        summary="Absences de l'établissement (avec leur délégation)",
        parameters=[
            OpenApiParameter("statut", OpenApiTypes.STR, enum=StatutAbsence.values),
            *_PARAMETRES_COMMUNS,
        ],
        responses={200: AbsenceAdminSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        filtres, erreur = _filtres(FiltresAbsencesAdminSerializer, request)
        if erreur is not None:
            return erreur
        qs = _filtrer_periode(_absences(), filtres)
        if filtres.get("statut"):
            qs = qs.filter(statut=filtres["statut"])
        if filtres.get("utilisateur_id"):
            qs = qs.filter(utilisateur_id=filtres["utilisateur_id"])
        qs = qs.order_by("-debut", "-cree_le", "id")
        pagination = PaginationPage()
        page = pagination.paginate_queryset(qs, request, view=self)
        contexte = {"delegations": _delegations_par_absence(page), "moi": request.user.pk}
        return pagination.get_paginated_response(
            AbsenceAdminSerializer(page, many=True, context=contexte).data
        )

    @extend_schema(
        tags=[TAG],
        operation_id="admin_absences_creer",
        summary="Déclarer une absence pour le compte d'un utilisateur (validation facultative)",
        request=CreationAbsenceAdminSerializer,
        responses={
            201: AbsenceDetailSerializer,
            **erreurs(
                400,
                409,
                r400="VALIDATION, DELEGATAIRE_INVALIDE, ROLE_NON_DETENU.",
                r403="Permission admin.absences absente.",
                r409="CHEVAUCHEMENT, POUVOIRS_INSUFFISANTS, SOUS_DELEGATION_INTERDITE, "
                "AUCUN_VALIDEUR.",
            ),
        },
    )
    def post(self, request):
        donnees = CreationAbsenceAdminSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        champs = dict(donnees.validated_data)
        absent_id = champs.pop("utilisateur_id")
        valider = champs.pop("valider")
        if absent_id == request.user.pk:
            return reponse_erreur(
                VALIDATION,
                "Déclarez votre propre absence depuis « Mon compte ».",
                details={"utilisateur_id": ["Vous ne pouvez pas être l'absent ici."]},
            )
        absent = Utilisateur.objects.filter(pk=absent_id, statut=StatutUtilisateur.ACTIF).first()
        if absent is None:  # inconnu, autre établissement (RLS) ou inactif
            return reponse_erreur(
                VALIDATION, details={"utilisateur_id": ["Utilisateur actif introuvable."]}
            )
        absence = services.soumettre_absence(absent, acteur=request.user, **champs)
        if valider:
            absence = services.valider_absence(absence, request.user)
        return _detail(absence, request, statut_http=status.HTTP_201_CREATED)


class CandidatsAdminVue(APIView):
    permission_classes = [AdminAbsences]

    @extend_schema(
        tags=[TAG],
        operation_id="admin_absences_candidats",
        summary="Utilisateurs actifs (absent ou délégataire), avec le contrôle P5 pour « pour »",
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR, description="Nom ou e-mail."),
            OpenApiParameter(
                "pour",
                OpenApiTypes.UUID,
                description="Absent : exclu de la liste ; sert au contrôle des pouvoirs.",
            ),
        ],
        responses={200: CandidatSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        pour = request.query_params.get("pour") or None
        if pour is not None:
            try:
                pour = services._uuid(pour)
            except ValueError:
                return reponse_erreur(VALIDATION, details={"pour": ["Identifiant invalide."]})
            if not Utilisateur.objects.filter(pk=pour).exists():
                return reponse_erreur(VALIDATION, details={"pour": ["Utilisateur introuvable."]})
        return Response(lister_candidats(request.query_params.get("q"), pour_id=pour))


class DelegationsAdminVue(APIView):
    permission_classes = [AdminDelegationsLecture]

    @extend_schema(
        tags=[TAG],
        operation_id="admin_delegations_liste",
        summary="Délégations de l'établissement",
        parameters=[
            OpenApiParameter("statut", OpenApiTypes.STR, enum=StatutDelegation.values),
            *_PARAMETRES_COMMUNS,
        ],
        responses={200: DelegationAdminSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        filtres, erreur = _filtres(FiltresDelegationsAdminSerializer, request)
        if erreur is not None:
            return erreur
        qs = _filtrer_periode(
            Delegation.objects.select_related("delegant", "delegataire", "role"), filtres
        )
        if filtres.get("statut"):
            qs = qs.filter(statut=filtres["statut"])
        if filtres.get("utilisateur_id"):
            u = filtres["utilisateur_id"]
            qs = qs.filter(Q(delegant_id=u) | Q(delegataire_id=u))
        qs = qs.order_by("-debut", "-cree_le", "id")
        pagination = PaginationPage()
        page = pagination.paginate_queryset(qs, request, view=self)
        contexte = {"maintenant": timezone.now()}
        return pagination.get_paginated_response(
            DelegationAdminSerializer(page, many=True, context=contexte).data
        )


class RevoquerDelegationAdminVue(APIView):
    permission_classes = [AdminAbsences]

    @extend_schema(
        tags=[TAG],
        operation_id="admin_delegations_revoquer",
        summary="Révoquer une délégation active (motif obligatoire)",
        request=RevocationSerializer,
        responses={
            200: DelegationAdminSerializer,
            **erreurs(
                400,
                404,
                409,
                r403="Permission admin.absences absente, ou délégation qui vous concerne.",
                r409="STATUT_INVALIDE (seule une délégation active se révoque).",
            ),
        },
    )
    def post(self, request, delegation_id):
        delegation = Delegation.objects.filter(pk=delegation_id).first()
        if delegation is None:
            return reponse_erreur(
                INTROUVABLE, "Délégation introuvable.", statut=status.HTTP_404_NOT_FOUND
            )
        donnees = RevocationSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        delegation = services.revoquer_delegation(
            delegation, request.user, donnees.validated_data["motif"]
        )
        delegation = Delegation.objects.select_related("delegant", "delegataire", "role").get(
            pk=delegation.pk
        )
        return Response(
            DelegationAdminSerializer(delegation, context={"maintenant": timezone.now()}).data
        )

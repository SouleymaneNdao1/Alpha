"""API des absences et délégations (§ 5.3 « /moi/absences… », § 5.4 « /absences/… », tâche B8).

Permission de toutes les routes : Session (``EstUtilisateurEtablissement``). Une absence
que l'utilisateur ne peut pas consulter répond 404 (jamais 403 pour un objet d'un
autre établissement ou invisible) ; une décision interdite sur une absence visible
répond 403.
"""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.comptes.models import StatutUtilisateur, Utilisateur
from alpha.core.erreurs import VALIDATION, reponse_erreur
from alpha.core.pagination import PaginationPage
from alpha.core.schema_erreurs import erreurs
from alpha.organisation.models import AffectationRole
from alpha.organisation.permissions import EstUtilisateurEtablissement
from alpha.organisation.pouvoirs import Pouvoirs, parents_des_unites

from . import services
from .models import Absence, Delegation, StatutAbsence, StatutDelegation
from .serializers import (
    AbsenceDetailSerializer,
    AbsenceSerializer,
    CreationAbsenceSerializer,
    DelegatairePossibleSerializer,
    DelegationRecueSerializer,
    RefusSerializer,
)

TAG_MOI = "Mon compte · absences et délégation"
TAG_ABSENCES = "Absences (validation)"
NB_DELEGATAIRES_MAX = 20


def _delegations_par_absence(absences) -> dict:
    ids = [a.pk for a in absences]
    resultat = {}
    for delegation in (
        Delegation.objects.select_related("delegataire", "role")
        .filter(absence_id__in=ids)
        .order_by("cree_le")
    ):
        resultat[delegation.absence_id] = delegation  # la plus récente l'emporte
    return resultat


def _absences():
    return Absence.objects.select_related("utilisateur", "valideur")


def _detail(absence: Absence, request, *, statut_http=status.HTTP_200_OK) -> Response:
    absence = _absences().get(pk=absence.pk)
    contexte = {
        "delegations": _delegations_par_absence([absence]),
        "peut_decider": absence.statut == StatutAbsence.SOUMISE
        and services.autorisation_decision(absence, request.user)[0],
    }
    return Response(AbsenceDetailSerializer(absence, context=contexte).data, status=statut_http)


def lister_candidats(texte, *, pour_id=None) -> list[dict]:
    """Utilisateurs ACTIFS (établissement courant, hors ``pour_id``) filtrés par ``texte``.

    ``pouvoirs_suffisants`` : couvre-t-il les pouvoirs de ``pour_id`` (P5) ? ``None`` sans
    ``pour_id``. Partagé par ``/moi/delegataires-possibles`` et ``/admin/absences/candidats``.
    """
    qs = Utilisateur.objects.filter(statut=StatutUtilisateur.ACTIF)
    if pour_id is not None:
        qs = qs.exclude(pk=pour_id)
    for mot in (texte or "").strip().split()[:5]:
        qs = qs.filter(Q(prenom__icontains=mot) | Q(nom__icontains=mot) | Q(email__icontains=mot))
    candidats = list(qs.order_by("nom", "prenom", "id")[:NB_DELEGATAIRES_MAX])
    ids = [c.pk for c in candidats]
    roles = dict(
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id__in=ids, principal=True)
        .values_list("utilisateur_id", "role__libelle")
    )
    suffisants: dict = {}
    if pour_id is not None:
        requis = Pouvoirs.de(pour_id)
        pouvoirs = services.pouvoirs_de_plusieurs(ids)
        parents = parents_des_unites()
        suffisants = {i: pouvoirs[i].couvre(requis, parents) for i in ids}
    return [
        {
            "id": c.pk,
            "nom": c.nom_complet,
            "role_principal": roles.get(c.pk),
            "pouvoirs_suffisants": suffisants.get(c.pk),
        }
        for c in candidats
    ]


# --- /moi/absences ------------------------------------------------------------------------------


class MesAbsencesVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_MOI],
        operation_id="moi_absences_liste",
        summary="Mes absences (avec leur délégation)",
        parameters=[
            OpenApiParameter("statut", OpenApiTypes.STR, enum=StatutAbsence.values),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("taille", OpenApiTypes.INT),
        ],
        responses={200: AbsenceSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        qs = _absences().filter(utilisateur_id=request.user.pk).order_by("-debut", "-cree_le")
        statut = request.query_params.get("statut")
        if statut:
            if statut not in StatutAbsence.values:
                return reponse_erreur(VALIDATION, details={"statut": ["Statut inconnu."]})
            qs = qs.filter(statut=statut)
        pagination = PaginationPage()
        page = pagination.paginate_queryset(qs, request, view=self)
        contexte = {"delegations": _delegations_par_absence(page)}
        return pagination.get_paginated_response(
            AbsenceSerializer(page, many=True, context=contexte).data
        )

    @extend_schema(
        tags=[TAG_MOI],
        operation_id="moi_absences_creer",
        summary="Déclarer une absence et désigner un délégataire",
        request=CreationAbsenceSerializer,
        responses={
            201: AbsenceDetailSerializer,
            **erreurs(
                400,
                409,
                r400="VALIDATION, DELEGATAIRE_INVALIDE, ROLE_NON_DETENU.",
                r409="CHEVAUCHEMENT, POUVOIRS_INSUFFISANTS, SOUS_DELEGATION_INTERDITE, "
                "AUCUN_VALIDEUR.",
            ),
        },
    )
    def post(self, request):
        donnees = CreationAbsenceSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        absence = services.soumettre_absence(request.user, **donnees.validated_data)
        return _detail(absence, request, statut_http=status.HTTP_201_CREATED)


class AnnulerMonAbsenceVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_MOI],
        operation_id="moi_absences_annuler",
        summary="Annuler mon absence (ou l'écourter si elle a commencé)",
        request=None,
        responses={
            200: AbsenceDetailSerializer,
            **erreurs(404, 409, r409="STATUT_INVALIDE"),
        },
    )
    def post(self, request, absence_id):
        absence = Absence.objects.filter(pk=absence_id, utilisateur_id=request.user.pk).first()
        if absence is None:
            raise NotFound()
        services.annuler_absence(absence, request.user)
        return _detail(absence, request)


class DelegatairesPossiblesVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_MOI],
        operation_id="moi_delegataires_possibles",
        summary="Délégataires possibles (actifs, même établissement, hors soi)",
        parameters=[OpenApiParameter("q", OpenApiTypes.STR, description="Nom ou e-mail.")],
        responses={200: DelegatairePossibleSerializer(many=True), **erreurs()},
    )
    def get(self, request):
        return Response(lister_candidats(request.query_params.get("q"), pour_id=request.user.pk))


class DelegationsRecuesVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_MOI],
        operation_id="moi_delegations_recues",
        summary="Délégations reçues (en attente, actives et terminées récemment)",
        responses={200: DelegationRecueSerializer(many=True), **erreurs()},
    )
    def get(self, request):
        qs = (
            Delegation.objects.select_related("delegant", "role")
            .filter(
                delegataire_id=request.user.pk,
                statut__in=(
                    StatutDelegation.EN_ATTENTE,
                    StatutDelegation.ACTIVE,
                    StatutDelegation.TERMINEE,
                ),
            )
            .order_by("-debut", "-cree_le")[:50]
        )
        contexte = {"maintenant": timezone.now()}
        return Response(DelegationRecueSerializer(qs, many=True, context=contexte).data)


# --- /absences/{id} -------------------------------------------------------------------------------


def _absence_visible(request, absence_id) -> Absence:
    absence = _absences().filter(pk=absence_id).first()
    if absence is None or not services.peut_consulter(absence, request.user):
        raise NotFound()
    return absence


class AbsenceVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_ABSENCES],
        operation_id="absences_detail",
        summary="Une absence (demandeur, valideur, admin.absences ou délégataire du valideur)",
        responses={200: AbsenceDetailSerializer, **erreurs(404)},
    )
    def get(self, request, absence_id):
        return _detail(_absence_visible(request, absence_id), request)


class ValiderAbsenceVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_ABSENCES],
        operation_id="absences_valider",
        summary="Valider une absence : la délégation devient active",
        request=None,
        responses={
            200: AbsenceDetailSerializer,
            **erreurs(
                404,
                409,
                r403="Ni valideur désigné, ni admin.absences (ou l'absent lui-même).",
                r409="STATUT_INVALIDE, ABSENCE_EXPIREE, POUVOIRS_INSUFFISANTS, "
                "SOUS_DELEGATION_INTERDITE.",
            ),
        },
    )
    def post(self, request, absence_id):
        absence = services.valider_absence(_absence_visible(request, absence_id), request.user)
        return _detail(absence, request)


class RefuserAbsenceVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG_ABSENCES],
        operation_id="absences_refuser",
        summary="Refuser une absence (motif obligatoire)",
        request=RefusSerializer,
        responses={
            200: AbsenceDetailSerializer,
            **erreurs(400, 404, 409, r409="STATUT_INVALIDE"),
        },
    )
    def post(self, request, absence_id):
        absence = _absence_visible(request, absence_id)
        donnees = RefusSerializer(data=request.data)
        donnees.is_valid(raise_exception=True)
        absence = services.refuser_absence(absence, request.user, donnees.validated_data["motif"])
        return _detail(absence, request)

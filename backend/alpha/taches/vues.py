"""API « À traiter » : ``/api/v1/taches/`` (§ 5.4, tâche B8). Permission : Session."""

from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.core.erreurs import VALIDATION, reponse_erreur
from alpha.core.pagination import PaginationPage
from alpha.core.schema_erreurs import erreurs
from alpha.organisation.permissions import EstUtilisateurEtablissement

from .models import Groupe, Module
from .serializers import CompteursSerializer, TacheSerializer
from .visibilite import (
    ORDRE_GROUPES,
    annoter_urgence,
    bornes_urgence,
    delegations_effectives_vers,
    visibles_pour,
)

TAG = "À traiter"


def _contexte_vue(request):
    """(queryset annoté et trié, contexte du sérialiseur) à l'instant de la requête."""
    maintenant = timezone.now()
    bornes = bornes_urgence(maintenant)
    qs = annoter_urgence(visibles_pour(request.user, maintenant), bornes)
    delegants = {
        d.delegant_id: d.delegant_nom for d in delegations_effectives_vers(request.user.pk, maintenant)
    }
    return qs, {"bornes": bornes, "delegants": delegants, "request": request}


class TachesVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG],
        operation_id="taches_liste",
        summary="Tâches à traiter (triées par urgence)",
        parameters=[
            OpenApiParameter("module", OpenApiTypes.STR, enum=Module.values),
            OpenApiParameter("groupe", OpenApiTypes.STR, enum=Groupe.values),
            OpenApiParameter("q", OpenApiTypes.STR, description="Référence, titre ou sous-titre."),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("taille", OpenApiTypes.INT, description="25 par défaut, 100 au plus."),
        ],
        responses={200: TacheSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        qs, contexte = _contexte_vue(request)
        module = request.query_params.get("module")
        if module:
            if module not in Module.values:
                return reponse_erreur(VALIDATION, details={"module": ["Module inconnu."]})
            qs = qs.filter(module=module)
        groupe = request.query_params.get("groupe")
        if groupe:
            if groupe not in Groupe.values:
                return reponse_erreur(VALIDATION, details={"groupe": ["Groupe inconnu."]})
            qs = qs.filter(groupe_ordre=ORDRE_GROUPES.index(groupe))
        texte = (request.query_params.get("q") or "").strip()
        if texte:
            qs = qs.filter(
                Q(reference__icontains=texte)
                | Q(titre__icontains=texte)
                | Q(sous_titre__icontains=texte)
            )
        pagination = PaginationPage()
        page = pagination.paginate_queryset(qs, request, view=self)
        return pagination.get_paginated_response(
            TacheSerializer(page, many=True, context=contexte).data
        )


class TachesCompteursVue(APIView):
    """Compteurs du menu (« À traiter ») et des tuiles, appelés en fond toutes les 60 s."""

    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG],
        operation_id="taches_compteurs",
        summary="Compteurs par groupe d'urgence et par module",
        responses={200: CompteursSerializer, **erreurs()},
    )
    def get(self, request):
        qs, _ = _contexte_vue(request)
        qs = qs.order_by()
        agregats = qs.aggregate(
            total=Count("id"),
            **{
                groupe: Count("id", filter=Q(groupe_ordre=i))
                for i, groupe in enumerate(ORDRE_GROUPES)
            },
        )
        par_module = {
            ligne["module"]: ligne["n"]
            for ligne in qs.values("module").annotate(n=Count("id")).order_by("module")
        }
        return Response(
            {
                "total": agregats["total"],
                "par_groupe": {groupe: agregats[groupe] for groupe in ORDRE_GROUPES},
                "par_module": par_module,
            }
        )


class TacheVue(APIView):
    permission_classes = [EstUtilisateurEtablissement]

    @extend_schema(
        tags=[TAG],
        operation_id="taches_detail",
        summary="Une tâche visible",
        responses={200: TacheSerializer, **erreurs(404, r404="Inexistante ou non visible.")},
    )
    def get(self, request, tache_id):
        qs, contexte = _contexte_vue(request)
        tache = qs.filter(pk=tache_id).first()
        if tache is None:
            raise NotFound()
        return Response(TacheSerializer(tache, context=contexte).data)

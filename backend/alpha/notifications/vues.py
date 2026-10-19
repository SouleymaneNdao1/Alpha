"""Vues ``/moi/preferences-notification`` et ``/moi/notifications`` (§ 5.3, tâche B9).

Permission « Session » : utilisateur d'établissement connecté ; chacun ne voit et ne
modifie que SES préférences et SES notifications (une notification d'un autre
utilisateur ou d'un autre établissement donne 404).
"""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.core.erreurs import INTROUVABLE, reponse_erreur
from alpha.core.pagination import PaginationPage
from alpha.core.permissions import Session
from alpha.core.schema_erreurs import erreurs

from . import services
from .models import Notification
from .serializers import (
    NotificationSerializer,
    PageNotificationsSerializer,
    PreferencesNotificationSerializer,
)

TAG = "Mon compte"


class PreferencesNotificationVue(APIView):
    permission_classes = [Session]

    @extend_schema(
        tags=[TAG],
        operation_id="moi_preferences_notification_lire",
        summary="Mes préférences de notification",
        responses={200: PreferencesNotificationSerializer, **erreurs()},
    )
    def get(self, request):
        preferences = services.preferences_de(request.user)
        return Response(PreferencesNotificationSerializer(preferences).data)

    @extend_schema(
        tags=[TAG],
        operation_id="moi_preferences_notification_modifier",
        summary="Enregistrer mes préférences de notification",
        description="Tous les champs sont attendus. SMS et notification mobile sont "
        "enregistrés ; leur envoi arrive au sprint 4.",
        request=PreferencesNotificationSerializer,
        responses={200: PreferencesNotificationSerializer, **erreurs(400)},
    )
    def put(self, request):
        corps = PreferencesNotificationSerializer(data=request.data)
        corps.is_valid(raise_exception=True)
        preferences = services.modifier_preferences(request.user, **corps.validated_data)
        return Response(PreferencesNotificationSerializer(preferences).data)


class PaginationNotifications(PaginationPage):
    """Page standard, plus le nombre total de non lues (compteur de la cloche)."""

    non_lues = 0

    def get_paginated_response(self, data):
        reponse = super().get_paginated_response(data)
        reponse.data["non_lues"] = self.non_lues
        return reponse


class NotificationsVue(APIView):
    permission_classes = [Session]

    @extend_schema(
        tags=[TAG],
        operation_id="moi_notifications_liste",
        summary="Mes notifications (cloche du bandeau)",
        description="Les plus récentes d'abord. Appel de fond : envoyer l'en-tête "
        "X-Alpha-Fond: 1 (ne prolonge pas l'inactivité).",
        parameters=[
            OpenApiParameter("non_lues", OpenApiTypes.INT, enum=[0, 1]),
            OpenApiParameter("page", OpenApiTypes.INT),
            OpenApiParameter("taille", OpenApiTypes.INT, description="25 par défaut, 100 au plus."),
        ],
        responses={200: PageNotificationsSerializer, **erreurs()},
    )
    def get(self, request):
        qs = Notification.objects.filter(utilisateur_id=request.user.pk).order_by("-cree_le", "-id")
        if request.query_params.get("non_lues") in ("1", "true"):
            qs = qs.filter(lue_le__isnull=True)
        paginateur = PaginationNotifications()
        paginateur.non_lues = services.non_lues(request.user)
        page = paginateur.paginate_queryset(qs, request, view=self)
        return paginateur.get_paginated_response(NotificationSerializer(page, many=True).data)


class NotificationLueVue(APIView):
    permission_classes = [Session]

    @extend_schema(
        tags=[TAG],
        operation_id="moi_notification_lue",
        summary="Marquer une notification comme lue",
        request=None,
        responses={204: OpenApiResponse(description="Lue."), **erreurs(404)},
    )
    def post(self, request, notification_id):
        if not services.marquer_lue(request.user, notification_id):
            return reponse_erreur(INTROUVABLE, statut=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationsToutLuVue(APIView):
    permission_classes = [Session]

    @extend_schema(
        tags=[TAG],
        operation_id="moi_notifications_tout_lu",
        summary="Marquer toutes mes notifications comme lues",
        request=None,
        responses={204: OpenApiResponse(description="Toutes lues."), **erreurs()},
    )
    def post(self, request):
        services.tout_lire(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

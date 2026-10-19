"""URL de test B5 : routes réelles de l'API + une action protégée par step-up TOTP."""

from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from alpha.comptes.authentification import SessionCsrfObligatoire
from alpha.core.permissions import Session, StepUpTOTP
from config.urls import urlpatterns as urls_api


class VueActionSensible(APIView):
    authentication_classes = [SessionCsrfObligatoire]
    permission_classes = [Session, StepUpTOTP]

    def post(self, request):
        return Response({"ok": True})


urlpatterns = [*urls_api, path("test/action-sensible", VueActionSensible.as_view())]

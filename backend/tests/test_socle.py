"""Tests du socle (tâche B1) : schéma OpenAPI, format d'erreur, X-Request-ID, réglages."""

import json
import re

import pytest
from django.conf import settings
from django.test import RequestFactory
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from alpha.core import contexte
from alpha.core.erreurs import ErreurApi
from alpha.core.middleware import RequestIdMiddleware, ip_client
from config.celery import app as application_celery

CLES_ERREUR = {"code", "message", "details"}

# ATOMIC_REQUESTS : toute vue DRF ouvre une transaction, donc une connexion.
pytestmark = pytest.mark.django_db


def _verifier_format_erreur(reponse, code: str, statut: int) -> dict:
    assert reponse.status_code == statut
    assert reponse["Content-Type"].startswith("application/json")
    corps = json.loads(reponse.content)
    assert set(corps) == CLES_ERREUR
    assert corps["code"] == code
    assert isinstance(corps["message"], str) and corps["message"]
    assert isinstance(corps["details"], dict)
    return corps


# --- Schéma et documentation --------------------------------------------------------


def test_schema_openapi_repond(client):
    reponse = client.get("/api/v1/schema/")
    assert reponse.status_code == 200
    assert b"openapi: 3" in reponse.content


def test_schema_openapi_json(client):
    reponse = client.get("/api/v1/schema/?format=json")
    assert reponse.status_code == 200
    assert reponse.json()["info"]["title"] == "ALPHA — API"


def test_documentation_interactive(client):
    reponse = client.get("/api/v1/docs/")
    assert reponse.status_code == 200
    assert b"swagger" in reponse.content.lower()


# --- Format d'erreur ---------------------------------------------------------------


def test_404_hors_drf_au_format_alpha(client):
    reponse = client.get("/api/v1/route-inexistante/")
    _verifier_format_erreur(reponse, "INTROUVABLE", 404)


def test_405_au_format_alpha(client):
    # Le client d'API du frontend envoie toujours Accept: application/json.
    reponse = client.post(
        "/api/v1/schema/", data={}, content_type="application/json", HTTP_ACCEPT="application/json"
    )
    _verifier_format_erreur(reponse, "METHODE_NON_AUTORISEE", 405)


class _Serialiseur(serializers.Serializer):
    email = serializers.EmailField()


class _VueValidation(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        _Serialiseur(data=request.data).is_valid(raise_exception=True)
        return Response(status=204)


class _VueMetier(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        raise ErreurApi(
            "ETAPE_INVALIDE", "Cette étape est déjà franchie.", statut=409, details={"etape": 2}
        )


class _VueSansPermission(APIView):
    """Aucune permission déclarée : la politique par défaut (fermée) s'applique."""

    def get(self, request):  # pragma: no cover - ne doit jamais être atteinte
        return Response({"ok": True})


def _rendre(reponse):
    reponse.render()
    return reponse


def test_validation_400_avec_details_par_champ():
    requete = APIRequestFactory().post("/x", {"email": "pas-un-email"}, format="json")
    reponse = _rendre(_VueValidation.as_view()(requete))
    corps = _verifier_format_erreur(reponse, "VALIDATION", 400)
    assert list(corps["details"]) == ["email"]
    assert isinstance(corps["details"]["email"], list)


def test_erreur_metier():
    reponse = _rendre(_VueMetier.as_view()(APIRequestFactory().get("/x")))
    corps = _verifier_format_erreur(reponse, "ETAPE_INVALIDE", 409)
    assert corps["details"] == {"etape": 2}


def test_permissions_fermees_par_defaut_401_si_anonyme():
    reponse = _rendre(_VueSansPermission.as_view()(APIRequestFactory().get("/x")))
    _verifier_format_erreur(reponse, "NON_AUTHENTIFIE", 401)


# --- X-Request-ID et contexte --------------------------------------------------------


def test_x_request_id_genere(client):
    reponse = client.get("/api/v1/schema/")
    assert re.fullmatch(r"[0-9a-f]{32}", reponse["X-Request-ID"])


def test_x_request_id_present_sur_une_erreur(client):
    reponse = client.get("/api/v1/route-inexistante/")
    assert reponse["X-Request-ID"]


def test_x_request_id_entrant_repris(client):
    reponse = client.get("/api/v1/schema/", headers={"X-Request-ID": "caddy-1234abcd"})
    assert reponse["X-Request-ID"] == "caddy-1234abcd"


def test_x_request_id_entrant_invalide_remplace(client):
    reponse = client.get("/api/v1/schema/", headers={"X-Request-ID": "<script>\nalert(1)"})
    assert re.fullmatch(r"[0-9a-f]{32}", reponse["X-Request-ID"])


def test_contexte_pose_pendant_la_requete_puis_retabli():
    vu = {}

    def vue(request):
        vu.update(contexte.instantane())
        from django.http import HttpResponse

        return HttpResponse("ok")

    requete = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5")
    reponse = RequestIdMiddleware(vue)(requete)

    assert vu["request_id"] == reponse["X-Request-ID"]
    assert vu["ip"] == "10.0.0.5"
    assert vu["scope"] == contexte.SCOPE_ANONYMOUS
    assert contexte.request_id() is None
    assert contexte.ip() is None


@pytest.mark.parametrize(
    ("transmis", "nb_proxies", "attendu"),
    [
        ("", 1, "172.18.0.9"),  # pas de proxy : adresse de la connexion
        ("203.0.113.7", 1, "203.0.113.7"),  # ajoutée par Caddy
        ("6.6.6.6, 203.0.113.7", 1, "203.0.113.7"),  # valeur de gauche falsifiée ignorée
        ("203.0.113.7", 0, "172.18.0.9"),  # aucun proxy de confiance
        ("pas-une-ip", 1, "172.18.0.9"),
    ],
)
def test_ip_client(transmis, nb_proxies, attendu):
    requete = RequestFactory().get("/", REMOTE_ADDR="172.18.0.9", HTTP_X_FORWARDED_FOR=transmis)
    assert ip_client(requete, nb_proxies) == attendu


def test_contexte_gestionnaire_et_validation():
    with contexte.contexte(
        tenant="7d1f6f4e-1d2b-4c1e-9d55-3f1f4f1c2a10", scope=contexte.SCOPE_TENANT
    ):
        assert str(contexte.tenant_courant()) == "7d1f6f4e-1d2b-4c1e-9d55-3f1f4f1c2a10"
        assert contexte.scope_courant() == "tenant"
    assert contexte.tenant_courant() is None
    assert contexte.scope_courant() == "anonymous"
    with pytest.raises(ValueError):
        contexte.definir(scope="inconnue")


# --- Réglages de sécurité et Celery ------------------------------------------------------


def test_reglages_de_securite():
    assert settings.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    assert settings.SESSION_COOKIE_NAME == "alpha_sid"
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.cached_db"
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
    assert settings.CSRF_COOKIE_NAME == "alpha_csrf"
    assert settings.CSRF_COOKIE_HTTPONLY is False
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
    assert "django.contrib.admin" not in settings.INSTALLED_APPS


def test_celery_files_defaut_et_celery():
    files = {file.name for file in application_celery.conf.task_queues}
    assert files == {"defaut", "celery"}
    assert application_celery.conf.task_default_queue == "celery"
    assert application_celery.conf.timezone == "Africa/Dakar"

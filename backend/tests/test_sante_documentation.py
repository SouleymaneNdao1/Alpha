"""Sonde de santé /api/v1/sante/ et routage du schéma OpenAPI selon l'environnement (B8)."""

from __future__ import annotations

from unittest import mock

import pytest
from django.test import override_settings

from alpha.audit.models import EvenementAudit
from alpha.core.documentation_api import routes_documentation

pytestmark = pytest.mark.django_db


# --- Santé ---------------------------------------------------------------------------------------


def test_sante_ok(client_api):
    reponse = client_api.get("/api/v1/sante/")
    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok"}
    assert "no-cache" in reponse["Cache-Control"] or "max-age=0" in reponse["Cache-Control"]


@pytest.mark.parametrize("panne", ["base_disponible", "redis_disponible"])
def test_sante_503_sans_detail(client_api, panne):
    with mock.patch(f"alpha.core.sante.{panne}", return_value=False):
        reponse = client_api.get("/api/v1/sante/")
    assert reponse.status_code == 503
    assert reponse.json() == {"statut": "indisponible"}


def test_sante_base_en_panne_reelle(client_api):
    """Une erreur de la base (connexion) donne 503, jamais 500, et le détail reste interne."""
    with mock.patch(
        "django.db.backends.utils.CursorWrapper.execute", side_effect=OSError("secret interne")
    ):
        reponse = client_api.get("/api/v1/sante/")
    assert reponse.status_code == 503
    assert b"secret" not in reponse.content


def test_sante_redis_en_panne_reelle(client_api):
    with mock.patch("django_redis.get_redis_connection", side_effect=ConnectionError("x")):
        assert client_api.get("/api/v1/sante/").status_code == 503


def test_sante_lecture_seule_et_sans_audit(client_api, etab_a):
    assert client_api.post("/api/v1/sante/").status_code == 405
    client_api.get("/api/v1/sante/")
    from alpha.tenancy.contexte import contexte_tenant

    with contexte_tenant(etab_a.id):
        assert not EvenementAudit.objects.exists()


# --- Schéma OpenAPI et documentation --------------------------------------------------------------


def test_production_sans_schema_ni_documentation():
    assert routes_documentation(active=False, reservee_connectes=True) == []


@override_settings(ROOT_URLCONF="tests.urls_documentation_production")
def test_production_404(client_api):
    assert client_api.get("/api/v1/schema/").status_code == 404
    assert client_api.get("/api/v1/docs/").status_code == 404
    assert client_api.get("/api/v1/sante/").status_code == 200


@override_settings(ROOT_URLCONF="tests.urls_documentation_recette")
def test_recette_reservee_aux_utilisateurs_connectes(client_api, client_connecte, utilisateur_a):
    assert client_api.get("/api/v1/schema/").status_code == 401
    reponse = client_api.get("/api/v1/schema/?format=json")
    assert reponse.status_code == 401
    assert reponse.json()["code"] == "NON_AUTHENTIFIE"
    assert client_api.get("/api/v1/docs/").status_code == 401
    client = client_connecte(utilisateur_a)
    assert client.get("/api/v1/schema/").status_code == 200
    assert client.get("/api/v1/docs/").status_code == 200


def test_reglages_par_environnement():
    """Lecture des modules de réglages sans les importer (variables d'environnement de prod)."""
    from pathlib import Path

    from django.conf import settings

    dossier = Path(settings.BASE_DIR) / "config" / "settings"
    prod = (dossier / "prod.py").read_text(encoding="utf-8")
    recette = (dossier / "recette.py").read_text(encoding="utf-8")
    assert "ALPHA_DOC_API_ACTIVE = False" in prod
    assert "ALPHA_DOC_API_ACTIVE = True" in recette
    assert "ALPHA_DOC_API_RESERVEE_CONNECTES = True" in recette

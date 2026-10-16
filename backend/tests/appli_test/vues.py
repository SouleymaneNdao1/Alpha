"""Vues de test : exposent le contexte vu par l'application et par PostgreSQL."""

from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.urls import path

from alpha.core import contexte


def vue_contexte(request: HttpRequest) -> JsonResponse:
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT current_setting('app.current_tenant', true), "
            "current_setting('app.scope', true), pg_backend_pid()"
        )
        tenant_sql, scope_sql, pid = curseur.fetchone()
    return JsonResponse(
        {
            "tenant": str(contexte.tenant_courant() or ""),
            "scope": contexte.scope_courant(),
            "tenant_sql": tenant_sql or "",
            "scope_sql": scope_sql or "",
            "pid": pid,
        }
    )


def vue_ecriture(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


urlpatterns = [
    path("contexte/", vue_contexte),
    path("ecriture/", vue_ecriture),
    path("api/v1/auth/deconnexion", vue_ecriture),
]


# --- B4 : règle des vues d'authentification (§ 3.3, § 6.1) ---------------------------------


def vue_echec_retourne_401(request: HttpRequest) -> JsonResponse:
    """Écrit l'événement puis RETOURNE une erreur : l'événement est conservé."""
    from alpha.audit.models import Categorie
    from alpha.audit.services import journaliser

    journaliser("auth.connexion.echec", Categorie.CONNEXION, objet_libelle="retour@test")
    return JsonResponse({"code": "IDENTIFIANTS_INVALIDES"}, status=401)


def vue_echec_leve_exception(request: HttpRequest) -> JsonResponse:
    """Écrit l'événement puis LÈVE : le point de sauvegarde de la vue annule l'événement."""
    from django.core.exceptions import PermissionDenied

    from alpha.audit.models import Categorie
    from alpha.audit.services import journaliser

    journaliser("auth.connexion.echec", Categorie.CONNEXION, objet_libelle="exception@test")
    raise PermissionDenied


def vue_echec_hors_transaction(request: HttpRequest) -> JsonResponse:
    """Lève, mais l'événement est écrit par la connexion indépendante : il est conservé."""
    from django.core.exceptions import PermissionDenied

    from alpha.audit.models import Categorie
    from alpha.audit.services import journaliser

    journaliser(
        "auth.connexion.echec",
        Categorie.CONNEXION,
        objet_libelle="independant@test",
        hors_transaction=True,
    )
    raise PermissionDenied


urlpatterns += [
    path("audit/echec-401/", vue_echec_retourne_401),
    path("audit/echec-exception/", vue_echec_leve_exception),
    path("audit/echec-independant/", vue_echec_hors_transaction),
]

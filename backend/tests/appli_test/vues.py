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

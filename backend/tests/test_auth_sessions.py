"""Sessions d'appareil (§ 4.6, § 4.8).

Inactivité, durée maximale, déconnexion, révocation et step-up TOTP.
"""

from __future__ import annotations

import datetime

from django.test import override_settings
from freezegun import freeze_time

from alpha.comptes import sessions
from alpha.comptes.models import MotifFinSession, SessionAppareil
from alpha.tenancy.contexte import contexte_tenant
from tests.outils_auth import (
    URL_DECONNEXION,
    URL_SESSION,
    contexte_de,
    creer_compte,
    evenements,
    poster,
    regler,
    se_connecter,
    transactionnel,
)

# Fixtures client_csrf et vider_limites (autouse).
pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel


def _dans(minutes: float):
    return freeze_time(datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=minutes))


def _appareil(compte) -> SessionAppareil:
    with contexte_de(compte.utilisateur):
        return SessionAppareil.objects.get(utilisateur=compte.utilisateur)


def test_expiration_d_inactivite_reglee_par_l_etablissement(client_csrf, etab_a):
    regler(etab_a, inactivite_session_min=5)
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte)
    with _dans(4):
        assert client_csrf.get(URL_SESSION).status_code == 200  # activité notée
    with _dans(8):
        assert client_csrf.get(URL_SESSION).status_code == 200  # 4 min depuis la dernière
    with _dans(14):
        r = client_csrf.get(URL_SESSION)
    assert r.status_code == 401
    assert r.json()["code"] == "SESSION_EXPIREE"
    appareil = _appareil(compte)
    assert appareil.motif_fin == MotifFinSession.INACTIVITE and appareil.revoque_le
    (expiree,) = evenements(etab_a.id, "auth.session.expiree")
    assert expiree.apres == {"motif": "INACTIVITE"}
    assert expiree.acteur_libelle == "Awa Diop"
    # Session Django vidée : la requête suivante est simplement anonyme.
    assert client_csrf.get(URL_SESSION).json()["code"] == "NON_AUTHENTIFIE"


def test_appels_de_fond_ne_prolongent_pas_l_inactivite(client_csrf, etab_a):
    regler(etab_a, inactivite_session_min=5)
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte)
    with _dans(4):
        assert client_csrf.get(URL_SESSION, HTTP_X_ALPHA_FOND="1").status_code == 200
    with _dans(6):
        assert client_csrf.get(URL_SESSION, HTTP_X_ALPHA_FOND="1").status_code == 401


def test_duree_maximale_de_session(client_csrf, etab_a):
    regler(etab_a, inactivite_session_min=60, duree_max_session_h=1)
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte)
    with _dans(50):
        assert client_csrf.get(URL_SESSION).status_code == 200
    with _dans(61):
        r = client_csrf.get(URL_SESSION)
    assert r.status_code == 401 and r.json()["code"] == "SESSION_EXPIREE"
    assert _appareil(compte).motif_fin == MotifFinSession.EXPIRATION
    assert evenements(etab_a.id, "auth.session.expiree")[0].apres == {"motif": "EXPIRATION"}


def test_deconnexion(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte)
    r = poster(client_csrf, URL_DECONNEXION)
    assert r.status_code == 204
    appareil = _appareil(compte)
    assert appareil.motif_fin == MotifFinSession.DECONNEXION and appareil.revoque_le
    assert client_csrf.get(URL_SESSION).status_code == 401
    (evt,) = evenements(etab_a.id, "auth.deconnexion")
    assert evt.acteur_id == compte.utilisateur.id
    # Déconnexion sans session : 401.
    assert poster(client_csrf, URL_DECONNEXION).status_code == 401


def test_revocation_d_une_session_d_appareil(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte)
    assert client_csrf.get(URL_SESSION).status_code == 200  # état mis en cache
    with contexte_tenant(etab_a.id):
        assert sessions.revoquer_sessions(compte.utilisateur, MotifFinSession.REVOCATION_ADMIN) == 1
    r = client_csrf.get(URL_SESSION)
    assert r.status_code == 401 and r.json()["code"] == "SESSION_EXPIREE"
    assert _appareil(compte).motif_fin == MotifFinSession.REVOCATION_ADMIN


def test_session_appareil_absente_refusee(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte)
    with contexte_tenant(etab_a.id):
        SessionAppareil.objects.all().delete()
    sessions.oublier(sessions.empreinte_cle_session(client_csrf.session.session_key))
    assert client_csrf.get(URL_SESSION).status_code == 401


@override_settings(ROOT_URLCONF="tests.appli_test.vues_auth")
def test_step_up_totp(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    code_connexion = compte.totp()
    se_connecter(client_csrf, compte, code=code_connexion)
    url = "/test/action-sensible"
    r = poster(client_csrf, url, {})
    assert r.status_code == 400 and r.json()["details"] == {
        "code": ["Le code de l'application d'authentification est requis."]
    }
    # Le code déjà utilisé pour se connecter ne resservira pas (anti-rejeu).
    r = poster(client_csrf, url, {"code": code_connexion})
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert poster(client_csrf, url, {"code": "000000"}).status_code == 401
    r = poster(client_csrf, url, {"code": compte.totp(+1)})
    assert r.status_code == 200 and r.json() == {"ok": True}
    # Limite : 5 essais par minute et par utilisateur.
    for _ in range(2):
        poster(client_csrf, url, {"code": "000000"})
    assert poster(client_csrf, url, {"code": "000000"}).status_code == 429


@override_settings(ROOT_URLCONF="tests.appli_test.vues_auth")
def test_step_up_exige_une_session(client_csrf, etab_a):
    r = poster(client_csrf, "/test/action-sensible", {"code": "123456"})
    assert r.status_code == 401


def test_client_connecte_de_conftest_passe_le_middleware(client_connecte, utilisateur_a):
    """La session forgée de ``client_connecte`` (tests hors authentification) est acceptée."""
    from tests.fabriques import UtilisateurFactory

    r = client_connecte(utilisateur_a).get(URL_SESSION)
    assert r.status_code == 200 and r.json()["email"] == utilisateur_a.email
    admin = UtilisateurFactory(super_admin=True)
    assert client_connecte(admin).get(URL_SESSION).json()["est_super_admin"] is True


def test_permissions_exigent_session_mfa_et_appareil_actif(client_connecte, utilisateur_a):
    """``Session`` / ``Perm`` (organisation) : sans ``mfa_le`` ou sans session d'appareil
    active, la route d'établissement est refusée, même si Django voit un utilisateur."""
    from rest_framework.test import APIClient

    from alpha.core.permissions import Session
    from alpha.organisation.permissions import EstUtilisateurEtablissement

    assert EstUtilisateurEtablissement is Session  # une seule implémentation
    url = "/api/v1/admin/utilisateurs"
    sans_mfa = APIClient()
    sans_mfa.force_login(utilisateur_a, backend="django.contrib.auth.backends.ModelBackend")
    session = sans_mfa.session
    session["scope"], session["tenant_id"] = "tenant", str(utilisateur_a.etablissement_id)
    session.save()
    # Ni mfa_le ni session d'appareil : refusé (le middleware répond 401 SESSION_EXPIREE).
    assert sans_mfa.get(url).status_code == 401

    client = client_connecte(utilisateur_a)
    session = client.session
    del session["mfa_le"]
    session.save()
    assert client.get(url).status_code in (401, 403)

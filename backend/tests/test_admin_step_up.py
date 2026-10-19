"""Step-up TOTP réel sur PATCH /admin/parametres-securite (raccordement B5 → B7, § 4.9)."""

from __future__ import annotations

import pytest

from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import ParametresEtablissement
from tests.fabriques import BanqueFactory
from tests.outils_admin import creer_admin
from tests.outils_auth import equiper, evenements, jeton_csrf, se_connecter, transactionnel

# Fixtures client_csrf et vider_limites (autouse).
pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel

URL = "/api/v1/admin/parametres-securite"


def _patch(client, donnees):
    return client.patch(
        URL, donnees, content_type="application/json", HTTP_X_CSRFTOKEN=jeton_csrf(client)
    )


@pytest.fixture
def connecte(client_csrf):
    banque = BanqueFactory(roles_defaut=True)
    compte = equiper(creer_admin(banque, email="abdou.kane@banque.test"))
    code_connexion = compte.totp()
    se_connecter(client_csrf, compte, code=code_connexion)
    return client_csrf, banque, compte, code_connexion


def _tentatives(banque) -> int:
    with contexte_tenant(banque.id):
        return ParametresEtablissement.objects.get().tentatives_max


def test_patch_avec_un_vrai_code_totp(connecte):
    client, banque, compte, _ = connecte
    r = _patch(client, {"code": compte.totp(+1), "tentatives_max": 4})
    assert r.status_code == 200, r.content
    assert r.json()["tentatives_max"] == 4 and _tentatives(banque) == 4
    (evt,) = evenements(banque.id, "parametres.securite.modifies")
    assert evt.apres == {"tentatives_max": 4}
    assert compte.totp(+1) not in evt.payload_canonique
    # Le même code ne resservira pas : pas consommé.
    r = _patch(client, {"code": compte.totp(+1), "tentatives_max": 3})
    assert r.status_code == 401 and _tentatives(banque) == 4


def test_patch_avec_un_code_rejoue_refuse(connecte):
    client, banque, compte, code_connexion = connecte
    # Code déjà utilisé pour se connecter (même pas) : rejeu refusé.
    r = _patch(client, {"code": code_connexion, "tentatives_max": 4})
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert _tentatives(banque) == 5
    assert evenements(banque.id, "parametres.securite.modifies") == []
    (refus,) = evenements(banque.id, "auth.step_up.echec")  # journalisé, non annulé
    assert refus.apres == {"motif": "CODE_INVALIDE"}
    assert refus.acteur_id == compte.utilisateur.id


def test_patch_limite_de_debit(connecte):
    client, banque, compte, _ = connecte
    for _ in range(5):
        assert _patch(client, {"code": "000000", "tentatives_max": 4}).status_code == 401
    # Au-delà de 5 essais/min, même un bon code est refusé.
    assert _patch(client, {"code": compte.totp(+1), "tentatives_max": 4}).status_code == 401
    assert _tentatives(banque) == 5
    motifs = [e.apres["motif"] for e in evenements(banque.id, "auth.step_up.echec")]
    assert motifs == ["CODE_INVALIDE"] * 5 + ["TROP_DE_REQUETES"]


def test_revocation_admin_et_statut_authenticator_reels(connecte, client_connecte):
    """Raccordements réels : revoquer_sessions, sessions_actives, statuts_authenticator."""
    from tests.outils_auth import creer_compte

    client, banque, _, _ = connecte
    awa = creer_compte(banque, "awa.diop@banque.test")
    client_awa = client_connecte(awa.utilisateur)
    assert client_awa.get("/api/v1/auth/session").status_code == 200
    liste = client.get("/api/v1/admin/utilisateurs").json()["results"]
    assert {u["email"]: u["authenticator"] for u in liste}["awa.diop@banque.test"] == "ACTIVE"
    fiche = client.get(f"/api/v1/admin/utilisateurs/{awa.utilisateur.id}").json()
    assert len(fiche["sessions_actives"]) == 1
    r = client.post(
        f"/api/v1/admin/utilisateurs/{awa.utilisateur.id}/sessions/revoquer",
        content_type="application/json",
        HTTP_X_CSRFTOKEN=jeton_csrf(client),
    )
    assert r.status_code == 200 and r.json() == {"revoquees": 1}
    assert client_awa.get("/api/v1/auth/session").json()["code"] == "SESSION_EXPIREE"
    fiche = client.get(f"/api/v1/admin/utilisateurs/{awa.utilisateur.id}").json()
    assert fiche["sessions_actives"] == []

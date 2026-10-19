"""Mon compte (§ 5.3, tâche B9) : profil, mot de passe, sécurité, Authenticator, codes,
téléphone perdu, sessions ; expiration du mot de passe (P3).

Tests transactionnels avec la vraie connexion (step-up TOTP réel, refus journalisés
hors transaction par la connexion « audit »).
"""

from __future__ import annotations

import datetime
import re

import pyotp
import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from alpha.comptes.models import (
    AuthenticatorTOTP,
    SessionAppareil,
    SignalementTelephonePerdu,
    StatutAuthenticator,
)
from tests.fabriques import BanqueFactory
from tests.outils_auth import (
    MDP,
    UA_FIREFOX_LINUX,
    contexte_de,
    creer_compte,
    evenements,
    jeton_csrf,
    poster,
    recharger,
    regler,
    se_connecter,
    transactionnel,
)

pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel

NOUVEAU = "Baobab-Sahel#42x"


@pytest.fixture
def banque():
    return BanqueFactory(roles_defaut=True)


@pytest.fixture
def compte(banque):
    return creer_compte(banque, email="awa.diop@banque.test", prenom="Awa", nom="Diop")


@pytest.fixture
def client(client_csrf, compte):
    se_connecter(client_csrf, compte, code=compte.totp())
    return client_csrf


def liberer(compte) -> None:
    """Oublie le dernier pas TOTP consommé : le code courant resservira (step-ups successifs
    dans un même test, sans attendre 30 s)."""
    with contexte_de(compte.utilisateur):
        AuthenticatorTOTP.objects.filter(statut=StatutAuthenticator.ACTIF).update(dernier_pas=None)


def _patch(client, url, donnees):
    return client.patch(
        url, donnees, content_type="application/json", HTTP_X_CSRFTOKEN=jeton_csrf(client)
    )


def _delete(client, url):
    return client.delete(url, HTTP_X_CSRFTOKEN=jeton_csrf(client))


# --- Profil -----------------------------------------------------------------------------------


def test_profil_lecture_et_modification(client, compte, banque):
    r = client.get("/api/v1/moi")
    assert r.status_code == 200 and r.json()["email"] == "awa.diop@banque.test"
    r = _patch(client, "/api/v1/moi", {"prenom": " Awa ", "telephone_mobile": "+221770000001"})
    assert r.status_code == 200, r.content
    assert r.json()["telephone_mobile"] == "+221770000001"
    (evt,) = evenements(banque.id, "utilisateur.modifie")
    assert evt.apres == {"telephone_mobile": "+221770000001"}
    assert evt.acteur_id == compte.utilisateur.id
    r = _patch(client, "/api/v1/moi", {"email": "autre@banque.test"})
    assert r.status_code == 400 and "email" in r.json()["details"]
    assert _patch(client, "/api/v1/moi", {"telephone_mobile": "77 000"}).status_code == 400
    assert recharger(compte.utilisateur).email == "awa.diop@banque.test"


def test_super_admin_refuse_et_anonyme_401(client_csrf):
    from tests.outils_auth import creer_compte_super_admin

    assert Client().get("/api/v1/moi").status_code in (401, 403)
    sa = creer_compte_super_admin()
    se_connecter(client_csrf, sa, code=sa.totp())
    assert client_csrf.get("/api/v1/moi").status_code == 403
    assert client_csrf.get("/api/v1/moi/sessions").status_code == 403


# --- Mot de passe ------------------------------------------------------------------------------


def _changer(client, compte, **champs):
    liberer(compte)
    corps = {"actuel": MDP, "nouveau": NOUVEAU, "confirmation": NOUVEAU, "code": compte.totp()}
    corps.update(champs)
    return poster(client, "/api/v1/moi/mot-de-passe", corps)


def test_changement_mot_de_passe_revoque_les_autres_sessions(client, compte, banque):
    autre = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_FIREFOX_LINUX)
    liberer(compte)
    se_connecter(autre, compte)
    r = _changer(client, compte, code=compte.totp())
    assert r.status_code == 204, r.content
    u = recharger(compte.utilisateur)
    assert u.check_password(NOUVEAU)
    # Session courante conservée, l'autre révoquée.
    assert client.get("/api/v1/moi").status_code == 200
    assert autre.get("/api/v1/moi").status_code == 401
    (evt,) = evenements(banque.id, "auth.mdp.modifie")
    assert evt.apres == {"sessions_revoquees": 1}
    assert NOUVEAU not in evt.payload_canonique and MDP not in evt.payload_canonique
    assert any("modifié" in m.subject for m in mail.outbox)
    assert "autres sessions" in mail.outbox[-1].body


def test_mot_de_passe_actuel_faux_compte_un_echec(client, compte, banque):
    r = _changer(client, compte, actuel="Mauvais-mdp#123")
    assert r.status_code == 401 and r.json()["code"] == "MOT_DE_PASSE_INCORRECT"
    assert r.json()["details"]["tentatives_restantes"] == 4
    assert recharger(compte.utilisateur).echecs_connexion == 1  # non annulé
    (evt,) = evenements(banque.id, "auth.connexion.echec")
    assert evt.apres == {"motif": "MON_COMPTE_MOT_DE_PASSE"}


def test_politique_et_historique_avant_le_step_up(client, compte, banque):
    liberer(compte)
    code = compte.totp()
    r = _changer(client, compte, nouveau="court", confirmation="court", code=code)
    assert r.status_code == 400 and "nouveau" in r.json()["details"]
    r = _changer(client, compte, nouveau=MDP, confirmation=MDP, code=code)
    assert r.status_code == 400
    r = _changer(client, compte, confirmation="Autre-chose#99x", code=code)
    assert r.status_code == 400 and "confirmation" in r.json()["details"]
    assert _changer(client, compte, code=code).status_code == 204
    # Historique (5 derniers) : retour à un mot de passe déjà utilisé refusé.
    suivant = "Fromager-Dakar#77y"
    r = _changer(client, compte, actuel=NOUVEAU, nouveau=suivant, confirmation=suivant)
    assert r.status_code == 204
    r = _changer(client, compte, actuel=suivant, nouveau=NOUVEAU, confirmation=NOUVEAU)
    assert r.status_code == 400 and "nouveau" in r.json()["details"]


def test_step_up_non_consomme_si_politique_refusee(client, compte):
    liberer(compte)
    code = compte.totp()
    corps = {"actuel": MDP, "nouveau": "court", "confirmation": "court", "code": code}
    assert poster(client, "/api/v1/moi/mot-de-passe", corps).status_code == 400
    corps.update(nouveau=NOUVEAU, confirmation=NOUVEAU)
    assert poster(client, "/api/v1/moi/mot-de-passe", corps).status_code == 204


def test_step_up_refuse_journalise(client, compte, banque):
    r = _changer(client, compte, code="000000")
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert recharger(compte.utilisateur).check_password(MDP)
    assert len(evenements(banque.id, "auth.step_up.echec")) == 1


def test_mot_de_passe_expire_impose_le_changement(client, compte, banque):
    regler(banque, mdp_expiration_jours=90)
    with contexte_de(compte.utilisateur):
        type(compte.utilisateur).objects.filter(pk=compte.utilisateur.pk).update(
            mdp_modifie_le=timezone.now() - datetime.timedelta(days=91)
        )
    assert client.get("/api/v1/moi").json()["mot_de_passe_expire"] is True
    assert client.get("/api/v1/moi/securite").status_code == 200
    r = client.get("/api/v1/moi/sessions")
    assert r.status_code == 403 and r.json()["code"] == "MOT_DE_PASSE_EXPIRE"
    assert client.get("/api/v1/taches/").status_code == 403
    assert _changer(client, compte).status_code == 204
    assert client.get("/api/v1/moi").json()["mot_de_passe_expire"] is False
    assert client.get("/api/v1/moi/sessions").status_code == 200


# --- Sécurité, Authenticator, codes --------------------------------------------------------------


def test_securite(client, compte):
    r = client.get("/api/v1/moi/securite")
    assert r.status_code == 200
    corps = r.json()
    assert corps["authenticator"]["statut"] == "ACTIVE"
    assert corps["codes_secours_restants"] == 10
    assert corps["signalement"] is None and corps["signature_bloquee"] is False
    assert "codes_secours" not in corps


def test_changement_d_authenticator(client, compte, banque):
    liberer(compte)
    r = poster(client, "/api/v1/moi/authenticator/changement", {"code_actuel": compte.totp()})
    assert r.status_code == 200, r.content
    secret = r.json()["secret_affichable"].replace(" ", "")
    assert r.json()["qr_svg"].startswith("<svg")
    # L'ancien reste actif tant que la confirmation n'est pas faite.
    with contexte_de(compte.utilisateur):
        assert AuthenticatorTOTP.objects.filter(statut=StatutAuthenticator.ACTIF).count() == 1
    r = poster(client, "/api/v1/moi/authenticator/changement/confirmer", {"code_nouveau": "000000"})
    assert r.status_code == 401 and r.json()["details"]["tentatives_restantes"] == 4
    r = poster(
        client,
        "/api/v1/moi/authenticator/changement/confirmer",
        {"code_nouveau": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 204, r.content
    with contexte_de(compte.utilisateur):
        actif = AuthenticatorTOTP.objects.get(statut=StatutAuthenticator.ACTIF)
    assert actif.confirme_le is not None
    # Codes de secours conservés, ancien code refusé, alerte et audit sans secret.
    assert client.get("/api/v1/moi/securite").json()["codes_secours_restants"] == 10
    (evt,) = evenements(banque.id, "mfa.change")
    assert secret not in evt.payload_canonique
    assert any("remplacée" in m.subject for m in mail.outbox)
    r = poster(client, "/api/v1/moi/authenticator/changement/confirmer", {"code_nouveau": "123456"})
    assert r.status_code == 409 and r.json()["code"] == "AUCUN_CHANGEMENT_EN_COURS"


def test_changement_authenticator_exige_le_step_up(client, compte):
    r = poster(client, "/api/v1/moi/authenticator/changement", {"code_actuel": "000000"})
    assert r.status_code == 401
    r = poster(client, "/api/v1/moi/authenticator/changement/confirmer", {"code_nouveau": "000000"})
    assert r.status_code == 409


def test_regeneration_des_codes(client, compte, banque):
    assert poster(client, "/api/v1/moi/codes-secours", {"code": "000000"}).status_code == 401
    liberer(compte)
    r = poster(client, "/api/v1/moi/codes-secours", {"code": compte.totp()})
    assert r.status_code == 200
    codes = r.json()["codes_secours"]
    assert len(codes) == 10 and all(re.fullmatch(r"[0-9A-Z]{4}-[0-9A-Z]{4}", c) for c in codes)
    (evt,) = evenements(banque.id, "mfa.codes_regeneres")
    assert all(c not in evt.payload_canonique for c in codes)
    assert compte.codes[0] not in str(client.get("/api/v1/moi/securite").content)


# --- Téléphone perdu --------------------------------------------------------------------------


def test_telephone_perdu_depuis_mon_compte(client, compte, banque):
    r = poster(client, "/api/v1/moi/telephone-perdu", {})
    assert r.status_code == 202
    assert client.get("/api/v1/moi").status_code in (401, 403)
    u = recharger(compte.utilisateur)
    assert u.signature_bloquee
    with contexte_de(u):
        assert SignalementTelephonePerdu.objects.get().canal == "MON_COMPTE"
        assert not SessionAppareil.objects.filter(revoque_le__isnull=True).exists()


# --- Sessions ----------------------------------------------------------------------------------


def test_sessions_liste_revocation_et_isolation(client, compte, banque):
    autre = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_FIREFOX_LINUX)
    liberer(compte)
    se_connecter(autre, compte)
    lignes = client.get("/api/v1/moi/sessions").json()
    assert len(lignes) == 2 and sum(s["courante"] for s in lignes) == 1
    courante = next(s for s in lignes if s["courante"])
    distante = next(s for s in lignes if not s["courante"])
    r = _delete(client, f"/api/v1/moi/sessions/{courante['id']}")
    assert r.status_code == 409 and r.json()["code"] == "SESSION_COURANTE"
    assert _delete(client, f"/api/v1/moi/sessions/{distante['id']}").status_code == 204
    assert autre.get("/api/v1/moi").status_code == 401
    assert _delete(client, f"/api/v1/moi/sessions/{distante['id']}").status_code == 404
    assert evenements(banque.id, "auth.session.revoquee")[0].apres["sessions_revoquees"] == 1

    # La session d'un autre utilisateur (même établissement) : 404.
    voisin = creer_compte(banque, email="cheikh@banque.test")
    tiers = Client(enforce_csrf_checks=True)
    se_connecter(tiers, voisin, code=voisin.totp())
    with contexte_de(voisin.utilisateur):
        sa_session = SessionAppareil.objects.get(
            utilisateur_id=voisin.utilisateur.pk, revoque_le__isnull=True
        )
    assert _delete(client, f"/api/v1/moi/sessions/{sa_session.id}").status_code == 404
    assert tiers.get("/api/v1/moi").status_code == 200


def test_revoquer_les_autres_sessions(client, compte):
    for _ in range(2):
        autre = Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_FIREFOX_LINUX)
        liberer(compte)
        se_connecter(autre, compte)
    r = poster(client, "/api/v1/moi/sessions/revoquer-autres")
    assert r.status_code == 200 and r.json() == {"revoquees": 2}
    assert len(client.get("/api/v1/moi/sessions").json()) == 1

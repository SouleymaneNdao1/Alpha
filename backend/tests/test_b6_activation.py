"""Activation par invitation (§ 4.3, tâche B6) : e-mail après commit, étapes, session ouverte."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.test import Client

from alpha.comptes import jetons
from alpha.comptes.models import (
    AuthenticatorTOTP,
    JetonUsageUnique,
    ObjetJeton,
    StatutAuthenticator,
    StatutUtilisateur,
    Utilisateur,
)
from alpha.tenancy.contexte import contexte_tenant
from tests.fabriques import UtilisateurFactory
from tests.outils_admin import role
from tests.outils_auth import UA_CHROME_WIN, evenements, poster, recharger, regler, transactionnel
from tests.outils_b6 import (
    API_ADMIN,
    API_AUTH,
    code_faux,
    code_precedent,
    lien_de,
    messages_pour,
    secret_de,
)

pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel

MDP_NOUVEAU = "Baobab-Lumineux-77!"


@pytest.fixture
def client() -> Client:
    return Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)


def _inviter(client_admin, banque, email="c.badiane@banque.test") -> str:
    """Invitation par l'API d'administration ; renvoie le jeton lu dans l'e-mail."""
    mail.outbox.clear()
    reponse = client_admin.post(
        f"{API_ADMIN}/utilisateurs",
        {
            "email": email,
            "prenom": "Cheikh",
            "nom": "Badiane",
            "role_id": str(role(banque, "analyste-credit").id),
        },
        format="json",
    )
    assert reponse.status_code == 201, reponse.json()
    (message,) = messages_pour(email, "Activez votre compte")
    return lien_de(message, "/activation?jeton=")


def _jusqu_au_qr(client, jeton) -> str:
    url = f"{API_AUTH}/activation/{jeton}"
    r = poster(
        client, f"{url}/mot-de-passe", {"mot_de_passe": MDP_NOUVEAU, "confirmation": MDP_NOUVEAU}
    )
    assert r.status_code == 204, r.content
    r = poster(client, f"{url}/authenticator")
    assert r.status_code == 200, r.content
    return secret_de(r)


def test_parcours_complet_invitation_jusqu_a_la_session(client, client_admin, banque):
    jeton = _inviter(client_admin, banque)
    (message,) = messages_pour("c.badiane@banque.test")
    assert "Établissement" in message.body or banque.raison_sociale in message.body
    assert message.alternatives and "text/html" in message.alternatives[0][1]
    url = f"{API_AUTH}/activation/{jeton}"

    r = client.get(url)
    assert r.status_code == 200
    assert r.json() == {
        "prenom": "Cheikh",
        "etablissement": banque.raison_sociale,
        "role": "Analyste crédit",
        "etape": "CREE",
    }

    # Étape « Mot de passe » : politique appliquée, confirmation vérifiée.
    r = poster(client, f"{url}/mot-de-passe", {"mot_de_passe": "court", "confirmation": "court"})
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION"
    assert "mot_de_passe" in r.json()["details"]
    r = poster(
        client, f"{url}/mot-de-passe", {"mot_de_passe": MDP_NOUVEAU, "confirmation": "autre"}
    )
    assert r.status_code == 400 and "confirmation" in r.json()["details"]
    r = poster(
        client, f"{url}/mot-de-passe", {"mot_de_passe": MDP_NOUVEAU, "confirmation": MDP_NOUVEAU}
    )
    assert r.status_code == 204

    # Étape « Téléphone » : QR SVG + secret affichable.
    r = poster(client, f"{url}/authenticator")
    assert r.status_code == 200
    corps = r.json()
    assert corps["qr_svg"].startswith("<svg") and corps["compte"] == "c.badiane@banque.test"
    assert corps["emetteur"] == f"ALPHA ({banque.raison_sociale})"
    secret = secret_de(r)

    # Étape « Vérification » : code faux puis bon code → 10 codes de secours.
    r = poster(client, f"{url}/authenticator/confirmer", {"code": code_faux(secret)})
    assert r.status_code == 401
    assert r.json()["code"] == "CODE_INVALIDE"
    assert r.json()["details"] == {"tentatives_restantes": 4}
    r = poster(client, f"{url}/authenticator/confirmer", {"code": code_precedent(secret)})
    assert r.status_code == 200
    codes = r.json()["codes_secours"]
    assert len(codes) == 10 and all(len(c) == 9 and c[4] == "-" for c in codes)

    # Fin : compte ACTIF, session ouverte.
    r = poster(client, f"{url}/terminer", {"codes_conserves": False})
    assert r.status_code == 400
    r = poster(client, f"{url}/terminer", {"codes_conserves": True})
    assert r.status_code == 200, r.content
    assert r.json()["email"] == "c.badiane@banque.test"
    assert client.get(f"{API_AUTH}/session").status_code == 200

    with contexte_tenant(banque.id):
        u = Utilisateur.objects.get(email="c.badiane@banque.test")
        assert u.statut == StatutUtilisateur.ACTIF and u.active_le is not None
        assert u.check_password(MDP_NOUVEAU)
        assert AuthenticatorTOTP.objects.get(utilisateur=u, statut="ACTIF")
        jeton_ligne = JetonUsageUnique.objects.get(utilisateur=u, objet=ObjetJeton.INVITATION)
        assert jeton_ligne.utilise_le is not None and jeton_ligne.etape == "TOTP_OK"

    actions = [e.action for e in evenements(banque.id)]
    for attendu in (
        "utilisateur.invite",
        "utilisateur.active",
        "mfa.active",
        "auth.connexion.succes",
        "mfa.verification.echec",
    ):
        assert attendu in actions, actions
    # Aucun secret ni jeton dans le journal.
    for e in evenements(banque.id):
        assert secret not in e.payload_canonique and jeton not in e.payload_canonique
        assert not any(c in e.payload_canonique for c in codes)

    # Lien consommé : 410.
    assert client.get(url).status_code == 410
    assert poster(Client(), f"{url}/terminer", {"codes_conserves": True}).status_code == 410


def test_etapes_dans_l_ordre(client, client_admin, banque):
    jeton = _inviter(client_admin, banque)
    url = f"{API_AUTH}/activation/{jeton}"
    r = poster(client, f"{url}/authenticator")
    assert r.status_code == 409 and r.json()["code"] == "ETAPE_INVALIDE"
    assert poster(client, f"{url}/authenticator/confirmer", {"code": "123456"}).status_code == 409
    assert poster(client, f"{url}/terminer", {"codes_conserves": True}).status_code == 409
    secret = _jusqu_au_qr(client, jeton)
    # Rappeler « authenticator » régénère le secret : l'ancien en attente est révoqué.
    r = poster(client, f"{url}/authenticator")
    assert secret_de(r) != secret
    with contexte_tenant(banque.id):
        statuts = sorted(AuthenticatorTOTP.objects.values_list("statut", flat=True))
    assert statuts.count(StatutAuthenticator.EN_ATTENTE) == 1
    assert poster(client, f"{url}/terminer", {"codes_conserves": True}).status_code == 409


def test_cinq_codes_faux_annulent_le_lien(client, client_admin, banque):
    jeton = _inviter(client_admin, banque)
    url = f"{API_AUTH}/activation/{jeton}"
    secret = _jusqu_au_qr(client, jeton)
    for restants in (4, 3, 2, 1):
        r = poster(client, f"{url}/authenticator/confirmer", {"code": code_faux(secret)})
        assert r.json()["details"]["tentatives_restantes"] == restants
    r = poster(client, f"{url}/authenticator/confirmer", {"code": code_faux(secret)})
    assert r.status_code == 410
    assert r.json() | {"message": ""} == {
        "code": "JETON_INVALIDE",
        "message": "",
        "details": {"motif": "TROP_D_ESSAIS"},
    }
    # Même un bon code ne passe plus : nouvelle invitation nécessaire.
    r = poster(client, f"{url}/authenticator/confirmer", {"code": code_precedent(secret)})
    assert r.status_code == 410
    echecs = evenements(banque.id, "mfa.verification.echec")
    assert len(echecs) == 5 and echecs[-1].apres["motif"] == "TROP_D_ESSAIS"


def test_lien_expire_ou_d_un_autre_objet(client, banque):
    regler(banque, validite_invitation_h=1)
    invite = UtilisateurFactory(etablissement=banque, statut=StatutUtilisateur.INVITE)
    with contexte_tenant(banque.id):
        ligne, clair = jetons.emettre(invite, ObjetJeton.INVITATION, datetime.timedelta(hours=1))
        _, clair_reinit = jetons.emettre(
            invite, ObjetJeton.REINIT_MDP, datetime.timedelta(minutes=30)
        )
    assert client.get(f"{API_AUTH}/activation/{clair}").status_code == 200
    # Un jeton de réinitialisation n'ouvre pas l'activation (et inversement).
    assert client.get(f"{API_AUTH}/activation/{clair_reinit}").status_code == 410
    assert client.get(f"{API_AUTH}/mot-de-passe/reinitialisation/{clair}").status_code == 410
    assert client.get(f"{API_AUTH}/activation/inconnu").status_code == 410
    with contexte_tenant(banque.id):
        JetonUsageUnique.objects.filter(pk=ligne.pk).update(
            expire_le=ligne.cree_le - datetime.timedelta(seconds=1)
        )
    r = client.get(f"{API_AUTH}/activation/{clair}")
    assert r.status_code == 410 and r.json()["code"] == "JETON_INVALIDE"


def test_compte_deja_actif_refuse(client, banque):
    actif = UtilisateurFactory(etablissement=banque)
    with contexte_tenant(banque.id):
        _, clair = jetons.emettre(actif, ObjetJeton.INVITATION, datetime.timedelta(hours=1))
    assert client.get(f"{API_AUTH}/activation/{clair}").status_code == 410
    assert recharger(actif).statut == StatutUtilisateur.ACTIF


def test_invitation_annulee_si_transaction_annulee(client_admin, banque):
    """Pas d'e-mail sans commit : un e-mail déjà utilisé (409) n'envoie rien."""
    UtilisateurFactory(etablissement=banque, email="deja@banque.test")
    mail.outbox.clear()
    r = client_admin.post(
        f"{API_ADMIN}/utilisateurs",
        {
            "email": "deja@banque.test",
            "prenom": "A",
            "nom": "B",
            "role_id": str(role(banque, "analyste-credit").id),
        },
        format="json",
    )
    assert r.status_code == 409
    assert mail.outbox == []


def test_invitation_acheminee_par_smtp_mailpit(mailpit, client_admin, banque):
    """Acheminement SMTP réel (Mailpit) ; sauté si Mailpit ne répond pas."""
    adresse = "mailpit.b6@banque.test"
    mailpit.supprimer_pour(adresse)
    r = client_admin.post(
        f"{API_ADMIN}/utilisateurs",
        {
            "email": adresse,
            "prenom": "Cheikh",
            "nom": "Badiane",
            "role_id": str(role(banque, "analyste-credit").id),
        },
        format="json",
    )
    assert r.status_code == 201
    message = mailpit.attendre_message(destinataire=adresse, sujet="Activez")
    assert "Activez votre compte ALPHA" in message.sujet
    assert "/activation?jeton=" in message.texte

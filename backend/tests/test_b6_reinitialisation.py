"""Mot de passe oublié et réinitialisation (§ 4.7, tâche B6) : pas d'énumération, preuve MFA."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from alpha.comptes.models import (
    HistoriqueMotDePasse,
    JetonUsageUnique,
    ObjetJeton,
    SessionAppareil,
)
from alpha.tenancy.contexte import contexte_tenant
from tests.outils_auth import (
    MDP,
    UA_CHROME_WIN,
    URL_CONNEXION,
    creer_compte,
    evenements,
    poster,
    recharger,
    regler,
    se_connecter,
    transactionnel,
)
from tests.outils_b6 import API_AUTH, code_faux, lien_de, messages_pour

pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel

URL_OUBLI = f"{API_AUTH}/mot-de-passe/oubli"
NOUVEAU = "Fromager-Solide-93!"


@pytest.fixture
def client() -> Client:
    return Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)


@pytest.fixture
def compte(etab_a):
    return creer_compte(etab_a, email="m.sow@banque-a.sn")


def _demander(client, email) -> str | None:
    mail.outbox.clear()
    r = poster(client, URL_OUBLI, {"email": email})
    assert r.status_code == 202, r.content
    messages = messages_pour(email, "Réinitialisation")
    return lien_de(messages[0], "/reinitialisation/") if messages else None


def test_meme_reponse_que_le_compte_existe_ou_non(client, compte, etab_a):
    r_inconnu = poster(client, URL_OUBLI, {"email": "personne@banque-a.sn"})
    r_connu = poster(client, URL_OUBLI, {"email": compte.email})
    assert r_inconnu.status_code == r_connu.status_code == 202
    assert r_inconnu.json() == r_connu.json()
    assert [m.to for m in mail.outbox] == [[compte.email]]
    (demande,) = evenements(etab_a.id, "auth.mdp.oubli_demande")
    assert demande.acteur_type == "ANONYME"


def test_compte_non_actif_ne_recoit_rien(client, compte):
    from alpha.comptes.models import StatutUtilisateur

    with contexte_tenant(compte.utilisateur.etablissement_id):
        compte.utilisateur.statut = StatutUtilisateur.SUSPENDU
        compte.utilisateur.save()
    assert _demander(client, compte.email) is None


def test_duree_parametree_et_jeton_precedent_annule(client, compte, etab_a):
    regler(etab_a, validite_reinit_mdp_min=10)
    premier = _demander(client, compte.email)
    second = _demander(client, compte.email)
    assert premier != second
    with contexte_tenant(etab_a.id):
        lignes = list(
            JetonUsageUnique.objects.filter(objet=ObjetJeton.REINIT_MDP).order_by("cree_le")
        )
    assert lignes[0].annule_le is not None and lignes[1].annule_le is None
    duree = lignes[1].expire_le - lignes[1].cree_le
    assert datetime.timedelta(minutes=9) < duree <= datetime.timedelta(minutes=10, seconds=1)
    assert client.get(f"{API_AUTH}/mot-de-passe/reinitialisation/{premier}").status_code == 410


def test_limite_trois_par_heure_et_par_email(client, compte):
    for _ in range(3):
        assert poster(client, URL_OUBLI, {"email": compte.email}).status_code == 202
    r = poster(client, URL_OUBLI, {"email": compte.email})
    assert r.status_code == 429 and r.json()["code"] == "TROP_DE_REQUETES"


def test_reinitialisation_avec_totp(client, compte, etab_a):
    autre = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
    se_connecter(autre, compte)  # session ouverte ailleurs : révoquée à la fin
    jeton = _demander(client, compte.email)
    url = f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}"

    r = client.get(url)
    assert r.status_code == 200
    assert r.json() == {"email_masque": "m.sow@…", "methodes": ["TOTP", "CODE_SECOURS"]}

    # Sans preuve MFA : refusé (l'accès à la boîte e-mail ne suffit pas).
    r = poster(client, url, {"mot_de_passe": NOUVEAU, "confirmation": NOUVEAU})
    assert r.status_code == 400
    # Politique contrôlée AVANT la preuve MFA (le code n'est pas consommé).
    r = poster(client, url, {"mot_de_passe": "faible", "confirmation": "faible", "code": "123456"})
    assert r.status_code == 400 and "mot_de_passe" in r.json()["details"]
    assert recharger(compte.utilisateur).echecs_connexion == 0
    # Mot de passe déjà utilisé (historique).
    r = poster(client, url, {"mot_de_passe": MDP, "confirmation": MDP, "code": "123456"})
    assert r.status_code == 400
    # Code faux : 401 et échec compté, journalisé hors transaction.
    r = poster(
        client,
        url,
        {"mot_de_passe": NOUVEAU, "confirmation": NOUVEAU, "code": code_faux(compte.secret)},
    )
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert r.json()["details"]["tentatives_restantes"] == 4
    assert recharger(compte.utilisateur).echecs_connexion == 1
    assert evenements(etab_a.id, "mfa.verification.echec")

    mail.outbox.clear()
    r = poster(
        client, url, {"mot_de_passe": NOUVEAU, "confirmation": NOUVEAU, "code": compte.totp(1)}
    )
    assert r.status_code == 204, r.content
    utilisateur = recharger(compte.utilisateur)
    assert utilisateur.check_password(NOUVEAU) and utilisateur.echecs_connexion == 0
    with contexte_tenant(etab_a.id):
        assert not SessionAppareil.objects.filter(
            utilisateur_id=utilisateur.pk, revoque_le__isnull=True
        ).exists()
        assert SessionAppareil.objects.filter(motif_fin="MDP_CHANGE").exists()
        assert HistoriqueMotDePasse.objects.filter(utilisateur_id=utilisateur.pk).count() >= 1
    assert autre.get(f"{API_AUTH}/session").status_code == 401
    assert messages_pour(compte.email, "a été modifié")
    (evt,) = evenements(etab_a.id, "auth.mdp.reinitialise")
    assert evt.apres["methode_mfa"] == "TOTP" and NOUVEAU not in evt.payload_canonique

    # Lien consommé ; connexion avec le nouveau mot de passe.
    assert client.get(url).status_code == 410
    r = poster(Client(), URL_CONNEXION, {"email": compte.email, "mot_de_passe": NOUVEAU})
    assert r.status_code == 200 and r.json()["etape"] == "MFA_REQUIS"


def test_reinitialisation_avec_code_de_secours(client, compte, etab_a):
    jeton = _demander(client, compte.email)
    url = f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}"
    code = compte.codes[0]
    r = poster(
        client, url, {"mot_de_passe": NOUVEAU, "confirmation": NOUVEAU, "code_secours": code}
    )
    assert r.status_code == 204
    assert evenements(etab_a.id, "mfa.code_secours_utilise")
    # Code à usage unique.
    jeton = _demander(client, compte.email)
    r = poster(
        client,
        f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}",
        {
            "mot_de_passe": "Autre-Secret-Long-48!",
            "confirmation": "Autre-Secret-Long-48!",
            "code_secours": code,
        },
    )
    assert r.status_code == 401


def test_verrouillage_apres_cinq_codes_faux(client, compte, etab_a):
    jeton = _demander(client, compte.email)
    url = f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}"
    corps = {"mot_de_passe": NOUVEAU, "confirmation": NOUVEAU, "code": code_faux(compte.secret)}
    for _ in range(4):
        assert poster(client, url, corps).status_code == 401
    r = poster(client, url, corps)
    assert r.status_code == 423 and r.json()["code"] == "COMPTE_VERROUILLE"
    assert recharger(compte.utilisateur).verrouille_jusqua > timezone.now()
    # Verrouillé : même un bon code est refusé.
    r = poster(client, url, {**corps, "code": compte.totp()})
    assert r.status_code == 423
    assert evenements(etab_a.id, "auth.verrouillage")

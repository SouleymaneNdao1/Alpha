"""Téléphone perdu (§ 4.5, décision P4, tâche B6) : signalement, réinitialisation, réenrôlement."""

from __future__ import annotations

import pytest
from django.core import mail
from django.test import Client
from rest_framework.test import APIClient

from alpha.comptes import raccordements, telephone
from alpha.comptes.models import (
    AuthenticatorTOTP,
    CodeSecours,
    SignalementTelephonePerdu,
    StatutAuthenticator,
    StatutSignalement,
)
from alpha.core.erreurs import ErreurApi
from alpha.taches.models import StatutTache, Tache
from alpha.tenancy.contexte import contexte_tenant
from tests.fabriques import UtilisateurFactory
from tests.outils_admin import creer_admin
from tests.outils_auth import (
    MDP,
    UA_CHROME_WIN,
    URL_CONNEXION,
    URL_MFA,
    URL_SESSION,
    equiper,
    evenements,
    poster,
    recharger,
    se_connecter,
    transactionnel,
)
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

URL_SIGNALER = f"{API_AUTH}/telephone-perdu"


@pytest.fixture
def client() -> Client:
    return Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)


@pytest.fixture
def victime(banque):
    """Utilisateur équipé (TOTP + codes) qui va perdre son téléphone."""
    return equiper(UtilisateurFactory(etablissement=banque, email="a.diop@banque.test"))


@pytest.fixture
def admin_equipe(admin):
    return equiper(admin)


@pytest.fixture
def client_admin_equipe(client_connecte, admin_equipe):
    return client_connecte(admin_equipe.utilisateur)


def _signaler(client, victime, mot_de_passe=MDP):
    r = poster(client, URL_SIGNALER, {"email": victime.email, "mot_de_passe": mot_de_passe})
    assert r.status_code == 202, r.content
    return r


def _signalement(banque) -> SignalementTelephonePerdu:
    with contexte_tenant(banque.id):
        return SignalementTelephonePerdu.objects.select_related("utilisateur").get()


def test_signalement_bloque_signature_et_revoque_les_sessions(client, banque, victime, admin):
    connecte = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
    se_connecter(connecte, victime)
    assert connecte.get(URL_SESSION).status_code == 200
    mail.outbox.clear()

    r = _signaler(client, victime)
    inconnu = poster(client, URL_SIGNALER, {"email": "x@banque.test", "mot_de_passe": MDP})
    assert inconnu.json() == r.json()  # aucune information sur l'existence du compte

    u = recharger(victime.utilisateur)
    assert u.signature_bloquee and not u.peut_signer
    assert connecte.get(URL_SESSION).status_code == 401
    signalement = _signalement(banque)
    assert signalement.statut == StatutSignalement.OUVERT and signalement.canal == "PAGE_PUBLIQUE"
    with contexte_tenant(banque.id):
        assert AuthenticatorTOTP.objects.get(utilisateur_id=u.pk).statut == "SUSPENDU"
        tache = Tache.objects.get(source_id=signalement.id)
    assert tache.module == "ADMINISTRATION" and tache.action == "TRAITER"
    assert tache.titre == f"Téléphone perdu · {u.nom_complet}" and tache.assigne_role_id
    assert tache.echeance.weekday() < 5
    (evt,) = evenements(banque.id, "telephone.signale")
    assert evt.categorie == "SECURITE" and evt.apres["signature_bloquee"] is True
    assert messages_pour(victime.email, "téléphone perdu")
    assert messages_pour(admin.email, "Téléphone perdu ·")
    with contexte_tenant(banque.id):
        en_cours = raccordements.signalement_en_cours(u.pk)
    assert en_cours["id"] == signalement.id and en_cours["statut"] == "OUVERT"

    # Connexion encore possible par code de secours ; plus par TOTP.
    nouveau = Client(HTTP_USER_AGENT=UA_CHROME_WIN)
    r = poster(nouveau, URL_CONNEXION, {"email": victime.email, "mot_de_passe": MDP})
    assert r.json()["methodes"] == ["CODE_SECOURS"]
    assert poster(nouveau, URL_MFA, {"code": victime.totp()}).status_code == 401
    r = poster(nouveau, URL_MFA, {"code_secours": victime.codes[0]})
    assert r.status_code == 200 and r.json()["utilisateur"]["signature_bloquee"] is True


def test_mot_de_passe_faux_ne_fait_que_compter_un_echec(client, banque, victime):
    _signaler(client, victime, mot_de_passe="mauvais-mot-de-passe")
    u = recharger(victime.utilisateur)
    assert not u.signature_bloquee and u.echecs_connexion == 1
    with contexte_tenant(banque.id):
        assert not SignalementTelephonePerdu.objects.exists()
    assert [e.apres["motif"] for e in evenements(banque.id, "auth.connexion.echec")] == [
        "TELEPHONE_PERDU_MOT_DE_PASSE"
    ]
    assert not evenements(banque.id, "telephone.signale")


def test_limite_trois_par_heure_et_par_ip(client, victime):
    for _ in range(3):
        _signaler(client, victime, mot_de_passe="faux")
    r = poster(client, URL_SIGNALER, {"email": victime.email, "mot_de_passe": MDP})
    assert r.status_code == 429


def test_auto_traitement_interdit(client, banque, admin_equipe, client_connecte):
    _signaler(client, admin_equipe)  # l'unique administrateur signale son propre téléphone
    signalement = _signalement(banque)
    api = client_connecte(admin_equipe.utilisateur)
    r = api.post(
        f"{API_ADMIN}/signalements-telephone/{signalement.id}/reinitialiser",
        {"mode_verification": "VISIO", "commentaire": "", "code": admin_equipe.totp()},
        format="json",
    )
    # Sessions révoquées par le signalement : le client forgé n'est plus admis.
    assert r.status_code in (401, 403)
    with contexte_tenant(banque.id), pytest.raises(ErreurApi) as erreur:
        telephone.verifier_traitement(signalement, admin_equipe.utilisateur)
    assert erreur.value.code == "AUTO_TRAITEMENT_INTERDIT"
    assert erreur.value.details == {"recours_fyxop": True}


def test_auto_traitement_refuse_par_l_api(banque, client_connecte):
    """Admin avec signalement ouvert mais encore connecté (signalement fait par FYXOP, P4)."""
    a1 = equiper(creer_admin(banque, email="a1@banque.test"))
    with contexte_tenant(banque.id):
        signalement = telephone.signaler(a1.utilisateur, canal="ADMIN")
    api = client_connecte(recharger(a1.utilisateur))
    r = api.post(
        f"{API_ADMIN}/signalements-telephone/{signalement.id}/reinitialiser",
        {"mode_verification": "VISIO", "code": "123456"},
        format="json",
    )
    assert r.status_code == 403
    assert r.json()["code"] == "AUTO_TRAITEMENT_INTERDIT"
    assert evenements(banque.id, "telephone.auto_traitement_refuse")


def test_reinitialisation_par_un_autre_admin_puis_reenrolement(
    client, banque, victime, admin_equipe, client_admin_equipe
):
    _signaler(client, victime)
    signalement = _signalement(banque)
    url = f"{API_ADMIN}/signalements-telephone/{signalement.id}/reinitialiser"

    r = client_admin_equipe.get(f"{API_ADMIN}/signalements-telephone?statut=OUVERT")
    assert r.status_code == 200 and r.json()["count"] == 1
    assert r.json()["results"][0]["utilisateur"]["email"] == victime.email

    # Step-up faux : 401, rien n'est changé, refus journalisé.
    r = client_admin_equipe.post(
        url,
        {"mode_verification": "PRESENTIEL_PIECE", "code": code_faux(admin_equipe.secret)},
        format="json",
    )
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert _signalement(banque).statut == "OUVERT"
    assert evenements(banque.id, "auth.step_up.echec")

    mail.outbox.clear()
    r = client_admin_equipe.post(
        url,
        {
            "mode_verification": "PRESENTIEL_PIECE",
            "commentaire": "CNI vérifiée au guichet",
            "code": admin_equipe.totp(),
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.json()["statut"] == "REINITIALISE"
    assert r.json()["traite_par"]["id"] == str(admin_equipe.utilisateur.id)
    u = recharger(victime.utilisateur)
    assert u.mfa_a_reconfigurer and u.signature_bloquee
    with contexte_tenant(banque.id):
        assert set(
            AuthenticatorTOTP.objects.filter(utilisateur_id=u.pk).values_list("statut", flat=True)
        ) == {StatutAuthenticator.REVOQUE}
        assert not CodeSecours.objects.filter(
            utilisateur_id=u.pk, invalide_le__isnull=True, utilise_le__isnull=True
        ).exists()
        assert Tache.objects.get(source_id=signalement.id).statut == StatutTache.TERMINEE
    (evt,) = evenements(banque.id, "telephone.reinitialise")
    assert evt.apres["mode_verification"] == "PRESENTIEL_PIECE"
    # Deuxième traitement : 409.
    r = client_admin_equipe.post(
        url, {"mode_verification": "VISIO", "code": admin_equipe.totp(1)}, format="json"
    )
    assert r.status_code == 409 and r.json()["code"] == "SIGNALEMENT_DEJA_TRAITE"

    # --- Réenrôlement par l'utilisateur ---
    (message,) = messages_pour(victime.email, "nouvelle application")
    jeton = lien_de(message, "/reenrolement/")
    r = poster(client, URL_CONNEXION, {"email": victime.email, "mot_de_passe": MDP})
    assert r.json()["etape"] == "REENROLEMENT_REQUIS"

    base = f"{API_AUTH}/reenrolement/{jeton}"
    r = client.get(base)
    assert r.status_code == 200 and r.json()["etape"] == "CREE"
    assert poster(client, f"{base}/authenticator").status_code == 409
    r = poster(client, f"{base}/mot-de-passe", {"mot_de_passe": "pas-le-bon"})
    assert r.status_code == 401 and r.json()["code"] == "MOT_DE_PASSE_INCORRECT"
    assert recharger(victime.utilisateur).echecs_connexion == 1
    assert poster(client, f"{base}/mot-de-passe", {"mot_de_passe": MDP}).status_code == 204
    r = poster(client, f"{base}/authenticator")
    secret = secret_de(r)
    r = poster(client, f"{base}/authenticator/confirmer", {"code": code_precedent(secret)})
    assert r.status_code == 200 and len(r.json()["codes_secours"]) == 10
    r = poster(client, f"{base}/terminer", {"codes_conserves": True})
    assert r.status_code == 200, r.content
    assert r.json()["signature_bloquee"] is False
    u = recharger(victime.utilisateur)
    assert not u.mfa_a_reconfigurer and not u.signature_bloquee and u.peut_signer
    assert evenements(banque.id, "mfa.reenrole")
    assert client.get(URL_SESSION).status_code == 200
    assert client.get(base).status_code == 410


def test_annulation_telephone_retrouve(client, banque, victime, client_admin_equipe, admin_equipe):
    _signaler(client, victime)
    signalement = _signalement(banque)
    r = client_admin_equipe.post(
        f"{API_ADMIN}/signalements-telephone/{signalement.id}/annuler",
        {"commentaire": "Retrouvé", "code": admin_equipe.totp()},
        format="json",
    )
    assert r.status_code == 200 and r.json()["statut"] == "ANNULE"
    u = recharger(victime.utilisateur)
    assert not u.signature_bloquee
    with contexte_tenant(banque.id):
        assert AuthenticatorTOTP.objects.get(utilisateur_id=u.pk).statut == "ACTIF"
    assert evenements(banque.id, "telephone.annule")


def test_signalement_d_un_autre_etablissement_introuvable(
    client, banque, autre_banque, victime, client_connecte
):
    _signaler(client, victime)
    signalement = _signalement(banque)
    autre_admin = equiper(creer_admin(autre_banque, email="admin@autre.test"))
    api = client_connecte(autre_admin.utilisateur)
    r = api.post(
        f"{API_ADMIN}/signalements-telephone/{signalement.id}/reinitialiser",
        {"mode_verification": "VISIO", "code": autre_admin.totp()},
        format="json",
    )
    assert r.status_code == 404
    assert api.get(f"{API_ADMIN}/signalements-telephone").json()["count"] == 0


def test_sans_permission_refuse(client, banque, victime, client_connecte):
    _signaler(client, victime)
    simple = equiper(UtilisateurFactory(etablissement=banque, email="simple@banque.test"))
    api = client_connecte(simple.utilisateur)
    assert api.get(f"{API_ADMIN}/signalements-telephone").status_code == 403
    assert APIClient().get(f"{API_ADMIN}/signalements-telephone").status_code in (401, 403)


# --- Décision P4 ---------------------------------------------------------------------------


def test_reinitialisation_du_dernier_admin_par_fyxop(banque, client_connecte):
    seul = equiper(creer_admin(banque, email="seul@banque.test"))
    collegue = creer_admin(banque, email="collegue@banque.test")  # admin sans téléphone actif
    fyxop = UtilisateurFactory(super_admin=True, email="ops@fyxop.test")
    mail.outbox.clear()

    with pytest.raises(ErreurApi) as erreur:
        telephone.reinitialiser_par_fyxop(
            banque.id, seul.utilisateur.id, par=fyxop, reference_demande="  "
        )
    assert erreur.value.code == "REFERENCE_OBLIGATOIRE"
    with pytest.raises(ErreurApi):
        telephone.reinitialiser_par_fyxop(
            banque.id, seul.utilisateur.id, par=seul.utilisateur, reference_demande="X"
        )

    signalement = telephone.reinitialiser_par_fyxop(
        banque.id,
        seul.utilisateur.id,
        par=fyxop,
        reference_demande="DG/2026/114 du 18/10/2026",
        commentaire="Appel vidéo avec CNI",
    )
    assert signalement.statut == "REINITIALISE" and signalement.mode_verification == "VISIO"
    assert signalement.canal == "ADMIN" and signalement.traite_par_id == fyxop.id
    assert recharger(seul.utilisateur).mfa_a_reconfigurer
    (evt,) = evenements(banque.id, "telephone.reinitialise")
    assert evt.apres["reference_demande"] == "DG/2026/114 du 18/10/2026"
    (evt_p,) = evenements(None, "plateforme.telephone.reinitialise")
    assert evt_p.categorie == "SUPER_ADMIN"
    assert messages_pour(collegue.email, "Réinitialisation par FYXOP")
    assert messages_pour(seul.email, "nouvelle application")

    # La fiche administrateur affiche « FYXOP » comme auteur du traitement.
    with contexte_tenant(banque.id):
        assert telephone.presenter(signalement)["traite_par"]["nom"] == "FYXOP"


def test_fyxop_refuse_si_un_autre_admin_est_disponible(banque):
    seul = equiper(creer_admin(banque, email="seul@banque.test"))
    equiper(creer_admin(banque, email="dispo@banque.test"))
    fyxop = UtilisateurFactory(super_admin=True, email="ops@fyxop.test")
    with pytest.raises(ErreurApi) as erreur:
        telephone.reinitialiser_par_fyxop(
            banque.id, seul.utilisateur.id, par=fyxop, reference_demande="REF"
        )
    assert erreur.value.code == "AUTRE_ADMINISTRATEUR_DISPONIBLE"

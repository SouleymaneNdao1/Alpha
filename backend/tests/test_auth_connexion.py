"""Connexion mot de passe → MFA → session (architecture § 4.2, § 5.2 ; tâche B5)."""

from __future__ import annotations

import datetime

import pytest
from django.core import mail
from freezegun import freeze_time

from alpha.comptes import mfa
from alpha.comptes.models import (
    AuthenticatorTOTP,
    CodeSecours,
    MethodeMfa,
    SessionAppareil,
    StatutAuthenticator,
)
from alpha.organisation.models import AffectationRole, Role
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement
from tests.fabriques import UtilisateurFactory
from tests.outils_auth import (
    MDP,
    UA_FIREFOX_LINUX,
    URL_CONNEXION,
    URL_MFA,
    URL_SESSION,
    contexte_de,
    creer_compte,
    creer_compte_super_admin,
    equiper,
    evenements,
    poster,
    recharger,
    se_connecter,
    transactionnel,
)

# Fixtures client_csrf et vider_limites (autouse).
pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel


def test_flux_complet_mot_de_passe_mfa_session(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    with contexte_tenant(etab_a.id):
        role = Role.objects.create(code="daf", libelle="DAF", permissions=["audit.lecture"])
        AffectationRole.objects.create(utilisateur=compte.utilisateur, role=role, principal=True)

    # Étape 1 : mot de passe → pré-authentification, sans session ouverte.
    r = poster(client_csrf, URL_CONNEXION, {"email": "A.DIOP@banque-a.sn", "mot_de_passe": MDP})
    assert r.status_code == 200
    assert r.json() == {"etape": "MFA_REQUIS", "methodes": ["TOTP", "CODE_SECOURS"]}
    assert client_csrf.get(URL_SESSION).status_code == 401
    cle_preauth = client_csrf.session.session_key

    # Étape 2 : TOTP → session.
    r = poster(client_csrf, URL_MFA, {"code": compte.totp()})
    assert r.status_code == 200, r.content
    corps = r.json()
    assert corps["codes_secours_restants"] == 10
    moi = corps["utilisateur"]
    assert moi["email"] == "a.diop@banque-a.sn"
    assert moi["initiales"] == "AD"
    assert moi["etablissement"]["raison_sociale"] == etab_a.raison_sociale
    assert moi["role_principal"] == {"id": str(role.id), "libelle": "DAF", "unite": None}
    assert moi["permissions"] == ["audit.lecture"]
    assert moi["modules"] == ["COMPTE", "AUDIT"]
    assert moi["inactivite_session_min"] == 15
    assert moi["est_super_admin"] is False

    # Anti-fixation : nouvelle clé de session ; contexte de session posé.
    session = client_csrf.session
    assert session.session_key != cle_preauth
    assert session["tenant_id"] == str(etab_a.id)
    assert session["scope"] == "tenant"
    assert "mfa_le" in session and "preauth" not in session

    with contexte_tenant(etab_a.id):
        appareil = SessionAppareil.objects.get(utilisateur=compte.utilisateur)
    assert appareil.methode_mfa == MethodeMfa.TOTP
    assert appareil.appareil.startswith("Chrome · Windows")
    assert appareil.revoque_le is None
    assert appareil.expire_le - appareil.cree_le == datetime.timedelta(hours=12)

    utilisateur = recharger(compte.utilisateur)
    assert utilisateur.derniere_connexion is not None
    assert utilisateur.echecs_connexion == 0

    r = client_csrf.get(URL_SESSION)
    assert r.status_code == 200 and r.json()["id"] == str(compte.utilisateur.id)

    succes = evenements(etab_a.id, "auth.connexion.succes")
    assert len(succes) == 1
    assert succes[0].acteur_libelle == "Awa Diop"  # résolveur d'acteur raccordé à Utilisateur
    assert succes[0].acteur_id == compte.utilisateur.id
    assert succes[0].detail == "Connexion réussie · double authentification OK"
    # Première session du compte : pas d'alerte « connexion inhabituelle ».
    assert not evenements(etab_a.id, "securite.connexion_inhabituelle")


def test_email_inconnu_meme_reponse_et_audit_plateforme(client_csrf, etab_a):
    creer_compte(etab_a)
    r = poster(client_csrf, URL_CONNEXION, {"email": "m.sow@inconnu.sn", "mot_de_passe": MDP})
    assert r.status_code == 401
    assert r.json()["code"] == "IDENTIFIANTS_INVALIDES"
    faux_mdp = poster(
        client_csrf, URL_CONNEXION, {"email": "a.diop@banque-a.sn", "mot_de_passe": "x" * 12}
    )
    assert faux_mdp.status_code == 401 and faux_mdp.json() == r.json()

    (echec,) = evenements(None, "auth.connexion.echec")
    assert (echec.acteur_type, echec.objet_libelle) == ("ANONYME", "m.sow@…")
    assert echec.apres == {"motif": "EMAIL_INCONNU"}
    (echec_etab,) = evenements(etab_a.id, "auth.connexion.echec")
    assert echec_etab.apres == {"motif": "MOT_DE_PASSE"}
    assert echec_etab.objet_libelle == "a.diop@…"


@pytest.mark.parametrize("champ", ["statut", "bloque"])
def test_compte_inactif_ou_bloque_refuse(client_csrf, etab_a, champ):
    compte = creer_compte(etab_a)
    with contexte_de(compte.utilisateur):
        if champ == "statut":
            compte.utilisateur.statut = "SUSPENDU"
        else:
            compte.utilisateur.bloque_par_admin = True
        compte.utilisateur.save()
    r = poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    assert r.status_code == 401 and r.json()["code"] == "IDENTIFIANTS_INVALIDES"


def test_etablissement_suspendu_403_seulement_avec_bon_mot_de_passe(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    with contexte_tenant(None, scope="platform"):
        Etablissement.objects.filter(pk=etab_a.pk).update(statut="SUSPENDU")
    r = poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": "mauvais-mdp"})
    assert r.status_code == 401
    r = poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    assert r.status_code == 403 and r.json()["code"] == "ETABLISSEMENT_SUSPENDU"


def test_mfa_sans_preauth_ou_preauth_expiree(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    r = poster(client_csrf, URL_MFA, {"code": "123456"})
    assert r.status_code == 401 and r.json()["code"] == "PREAUTH_EXPIREE"
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    with freeze_time(datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=6)):
        r = poster(client_csrf, URL_MFA, {"code": compte.totp()})
    assert r.status_code == 401 and r.json()["code"] == "PREAUTH_EXPIREE"


def test_corps_mfa_invalide(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    for corps in ({}, {"code": "123456", "code_secours": "ABCD-EFGH"}, {"code": "12a456"}):
        r = poster(client_csrf, URL_MFA, corps)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION"


def test_rejeu_totp_refuse(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    code = compte.totp()
    se_connecter(client_csrf, compte, code=code)
    poster(client_csrf, "/api/v1/auth/deconnexion")
    # Même code, même pas : refusé (anti-rejeu), et compté comme échec.
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    r = poster(client_csrf, URL_MFA, {"code": code})
    assert r.status_code == 401
    assert r.json() == {
        "code": "CODE_INVALIDE",
        "message": "Code de vérification invalide ou expiré.",
        "details": {"tentatives_restantes": 4},
    }
    # Le pas suivant (fenêtre +1) est accepté.
    r = poster(client_csrf, URL_MFA, {"code": compte.totp(+1)})
    assert r.status_code == 200
    # Un code plus ancien que le dernier accepté est refusé, même dans la fenêtre.
    with contexte_de(compte.utilisateur):
        assert not mfa.verifier_totp(compte.utilisateur, compte.totp(0))


def test_code_secours_usage_unique(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    code = compte.codes[0]
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    # Saisie tolérante : minuscules, espaces, sans tiret.
    r = poster(client_csrf, URL_MFA, {"code_secours": f" {code.replace('-', ' ').lower()} "})
    assert r.status_code == 200, r.content
    assert r.json()["codes_secours_restants"] == 9
    with contexte_tenant(etab_a.id):
        appareil = SessionAppareil.objects.get(utilisateur=compte.utilisateur)
        assert appareil.methode_mfa == MethodeMfa.CODE_SECOURS
        assert CodeSecours.objects.filter(utilise_le__isnull=False).count() == 1
    (utilise,) = evenements(etab_a.id, "mfa.code_secours_utilise")
    assert utilise.apres == {"restants": 9}
    assert any("code de secours a été utilisé" in m.body for m in mail.outbox)

    poster(client_csrf, "/api/v1/auth/deconnexion")
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    r = poster(client_csrf, URL_MFA, {"code_secours": code})
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"


def test_codes_secours_stockes_haches_et_regeneration_invalide_le_lot(etab_a):
    compte = creer_compte(etab_a)
    with contexte_tenant(etab_a.id):
        stockes = list(CodeSecours.objects.values_list("code_hmac", flat=True))
        assert len(stockes) == 10
        for code in compte.codes:
            assert code not in stockes and code.replace("-", "") not in "".join(stockes)
        assert {len(h) for h in stockes} == {64}
        nouveaux = mfa.generer_codes_secours(compte.utilisateur)
        assert len(set(nouveaux)) == 10
        assert mfa.codes_secours_restants(compte.utilisateur) == 10
        assert not mfa.consommer_code_secours(compte.utilisateur, compte.codes[1])
        assert mfa.consommer_code_secours(compte.utilisateur, nouveaux[0])


def test_telephone_perdu_totp_suspendu_codes_secours_seuls(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    with contexte_de(compte.utilisateur):
        AuthenticatorTOTP.objects.filter(utilisateur=compte.utilisateur).update(
            statut=StatutAuthenticator.SUSPENDU
        )
        compte.utilisateur.signature_bloquee = True
        compte.utilisateur.save()
    r = poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    assert r.json() == {"etape": "MFA_REQUIS", "methodes": ["CODE_SECOURS"]}
    assert poster(client_csrf, URL_MFA, {"code": compte.totp()}).status_code == 401
    r = poster(client_csrf, URL_MFA, {"code_secours": compte.codes[0]})
    assert r.status_code == 200
    assert r.json()["utilisateur"]["signature_bloquee"] is True
    utilisateur = recharger(compte.utilisateur)
    assert utilisateur.peut_signer is False
    with pytest.raises(mfa.ErreurApi) as erreur:
        mfa.verifier_signature_autorisee(utilisateur)
    assert erreur.value.code == "SIGNATURE_BLOQUEE" and erreur.value.status_code == 403


def test_mfa_a_reconfigurer_ou_sans_mfa_reenrolement_requis(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    with contexte_de(compte.utilisateur):
        compte.utilisateur.mfa_a_reconfigurer = True
        compte.utilisateur.save()
    r = poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    assert r.json() == {"etape": "REENROLEMENT_REQUIS", "methodes": []}
    assert poster(client_csrf, URL_MFA, {"code": compte.totp()}).json()["code"] == (
        "PREAUTH_EXPIREE"
    )
    sans_mfa = equiper(
        UtilisateurFactory(etablissement=etab_a, email="b.ba@banque-a.sn"), totp=False, codes=False
    )
    r = poster(client_csrf, URL_CONNEXION, {"email": sans_mfa.email, "mot_de_passe": MDP})
    assert r.json()["etape"] == "REENROLEMENT_REQUIS"


def test_super_admin_mfa_obligatoire_et_portee_plateforme(client_csrf, db):
    sans_mfa = equiper(
        UtilisateurFactory(super_admin=True, email="nu@fyxop.test"), totp=False, codes=False
    )
    r = poster(client_csrf, URL_CONNEXION, {"email": sans_mfa.email, "mot_de_passe": MDP})
    assert r.json()["etape"] == "REENROLEMENT_REQUIS"

    compte = creer_compte_super_admin()
    r = se_connecter(client_csrf, compte)
    moi = r.json()["utilisateur"]
    assert moi["est_super_admin"] is True and moi["etablissement"] is None
    assert moi["modules"] == ["CONSOLE"] and moi["inactivite_session_min"] == 10
    session = client_csrf.session
    assert session["scope"] == "platform" and "tenant_id" not in session
    with contexte_de(compte.utilisateur):
        appareil = SessionAppareil.objects.get(utilisateur=compte.utilisateur)
    assert appareil.etablissement_id is None
    assert appareil.expire_le - appareil.cree_le == datetime.timedelta(hours=8)
    assert client_csrf.get(URL_SESSION).json()["est_super_admin"] is True
    (succes,) = evenements(None, "auth.connexion.succes")
    assert (succes.acteur_type, succes.acteur_libelle) == ("SUPER_ADMIN", "Admin FYXOP")


def test_connexion_inhabituelle_alerte_et_audit(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    se_connecter(client_csrf, compte, REMOTE_ADDR="196.207.10.1")
    poster(client_csrf, "/api/v1/auth/deconnexion")
    # Même navigateur, même /16 : habituelle.
    se_connecter(client_csrf, compte, code=compte.totp(+1), REMOTE_ADDR="196.207.99.8")
    poster(client_csrf, "/api/v1/auth/deconnexion")
    assert not evenements(etab_a.id, "securite.connexion_inhabituelle")
    mail.outbox.clear()
    # Autre navigateur et autre réseau : inhabituelle.
    autre = type(client_csrf)(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_FIREFOX_LINUX)
    with contexte_de(compte.utilisateur):
        # Pas TOTP suivant déjà consommé : on repart d'un compteur antérieur.
        AuthenticatorTOTP.objects.filter(utilisateur=compte.utilisateur).update(dernier_pas=0)
    se_connecter(autre, compte, REMOTE_ADDR="41.82.3.4")
    (alerte,) = evenements(etab_a.id, "securite.connexion_inhabituelle")
    assert alerte.categorie == "SECURITE"
    assert alerte.apres["ip"] == "41.82.3.4"
    (message,) = [m for m in mail.outbox if "Nouvelle connexion" in m.subject]
    assert message.to == [compte.email]
    assert "/activation?onglet=telephone-perdu" in message.body
    assert "Firefox" in message.body


def test_nouvelle_connexion_depuis_une_session_ouverte(client_csrf, etab_a):
    """Session ouverte puis échec de connexion dans le même établissement : pas de blocage
    sur le verrou de la chaîne d'audit (déconnexion et échec écrits hors transaction)."""
    compte = creer_compte(etab_a)
    autre = creer_compte(etab_a, "k.sarr@banque-a.sn")
    se_connecter(client_csrf, compte)
    r = poster(client_csrf, URL_CONNEXION, {"email": autre.email, "mot_de_passe": "faux-faux-faux"})
    assert r.status_code == 401
    assert client_csrf.get(URL_SESSION).status_code == 401  # ancienne session fermée
    actions = [e.action for e in evenements(etab_a.id)]
    assert actions[-2:] == ["auth.deconnexion", "auth.connexion.echec"]
    r = poster(client_csrf, URL_CONNEXION, {"email": "x@inconnu.sn", "mot_de_passe": MDP})
    assert r.status_code == 401
    assert evenements(None, "auth.connexion.echec")[0].objet_libelle == "x@…"

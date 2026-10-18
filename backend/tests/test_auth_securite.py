"""Sécurité de l'authentification B5 (§ 4.1, § 4.9).

CSRF, secrets, chiffrement, RLS des nouvelles tables, politique de mot de passe.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections, transaction
from django.test import Client, override_settings

from alpha.audit.models import EvenementAudit
from alpha.comptes import chiffrement, mfa
from alpha.comptes.models import AuthenticatorTOTP, HistoriqueMotDePasse
from alpha.comptes.mots_de_passe import definir_mot_de_passe
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from tests.conftest import creer_etablissement
from tests.outils_auth import (
    MDP,
    URL_CONNEXION,
    URL_DECONNEXION,
    URL_MFA,
    contexte_de,
    creer_compte,
    creer_compte_super_admin,
    jeton_csrf,
    poster,
    se_connecter,
    transactionnel,
)
from tests.outils_comptes import creer_utilisateur

# Fixtures client_csrf et vider_limites (autouse).
pytest_plugins = ["tests.fixtures_auth"]

TABLES_B5 = ("authenticator_totp", "code_secours", "historique_mot_de_passe", "session_appareil")


# --- CSRF obligatoire (§ 4.1) ----------------------------------------------------------------


@transactionnel
@pytest.mark.parametrize("url", [URL_CONNEXION, URL_MFA, URL_DECONNEXION])
def test_csrf_obligatoire_sur_les_post_anonymes(client_csrf, url):
    r = client_csrf.post(url, {}, content_type="application/json")
    assert r.status_code == 403 and r.json()["code"] == "CSRF_INVALIDE"
    jeton_csrf(client_csrf)
    r = client_csrf.post(url, {}, content_type="application/json", HTTP_X_CSRFTOKEN="faux" * 8)
    assert r.status_code == 403 and r.json()["code"] == "CSRF_INVALIDE"


@transactionnel
def test_csrf_obligatoire_une_fois_connecte_et_jeton_tourne(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    avant = jeton_csrf(client_csrf)
    se_connecter(client_csrf, compte)
    assert client_csrf.cookies["alpha_csrf"].value != avant  # rotate_token() à la connexion
    r = client_csrf.post(URL_DECONNEXION, content_type="application/json")
    assert r.status_code == 403 and r.json()["code"] == "CSRF_INVALIDE"
    assert poster(client_csrf, URL_DECONNEXION).status_code == 204


@transactionnel
def test_get_csrf_pose_le_cookie():
    client = Client(enforce_csrf_checks=True)
    r = client.get("/api/v1/auth/csrf")
    assert r.status_code == 204
    cookie = client.cookies["alpha_csrf"]
    assert cookie.value and not cookie["httponly"] and cookie["samesite"] == "Lax"


# --- Aucun secret dans les journaux ni dans l'audit -------------------------------------------


@transactionnel
def test_aucun_secret_dans_les_journaux_ni_dans_l_audit(client_csrf, etab_a, caplog):
    caplog.set_level(logging.DEBUG)
    compte = creer_compte(etab_a)
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": "Faux-Mdp-Test-77"})
    poster(client_csrf, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    poster(client_csrf, URL_MFA, {"code": "000000"})
    poster(client_csrf, URL_MFA, {"code_secours": compte.codes[0]})
    cle_session = client_csrf.session.session_key
    poster(client_csrf, URL_DECONNEXION)
    se_connecter(client_csrf, compte, code=compte.totp(+1))

    with contexte_tenant(etab_a.id):
        authenticator = AuthenticatorTOTP.objects.get(utilisateur=compte.utilisateur)
        hachage = compte.utilisateur.__class__.objects.get(pk=compte.utilisateur.pk).password
        codes_hmac = [mfa.hmac_code_secours(mfa.normaliser_code_secours(c)) for c in compte.codes]
    secrets = [
        MDP,
        "Faux-Mdp-Test-77",
        compte.secret,
        hachage,
        cle_session,
        *compte.codes,
        *(c.replace("-", "") for c in compte.codes),
        *codes_hmac,
        *settings.ALPHA_CLES_CHIFFREMENT,
        settings.ALPHA_HMAC_POIVRE,
        bytes(authenticator.secret_chiffre).decode("ascii"),
    ]
    with contexte_tenant(etab_a.id):
        textes = [
            " ".join(
                str(v) for v in (e.payload_canonique, e.avant, e.apres, e.detail, e.objet_libelle)
            )
            for e in EvenementAudit.objects.all()
        ]
    assert len(textes) >= 5
    journal = caplog.text
    for secret in secrets:
        assert secret not in journal
        assert all(secret not in texte for texte in textes)


def test_secret_totp_chiffre_au_repos_et_rotation_des_cles(etab_a):
    utilisateur = creer_utilisateur(etab_a, "c.badiane@banque-a.sn")
    with contexte_tenant(etab_a.id):
        authenticator, secret = mfa.creer_authenticator_en_attente(utilisateur)
        brut = bytes(AuthenticatorTOTP.objects.get(pk=authenticator.pk).secret_chiffre)
    assert secret.encode() not in brut and len(secret) == 32
    assert chiffrement.dechiffrer(brut) == secret
    assert authenticator.cle_version == 1
    ancienne = settings.ALPHA_CLES_CHIFFREMENT[0]
    nouvelle = Fernet.generate_key().decode()
    with override_settings(
        ALPHA_CLES_CHIFFREMENT=[nouvelle, ancienne], ALPHA_CLES_CHIFFREMENT_VERSION=2
    ):
        assert chiffrement.dechiffrer(brut) == secret  # l'ancienne clé déchiffre encore
        tourne = chiffrement.rechiffrer(brut)
        with override_settings(ALPHA_CLES_CHIFFREMENT=[nouvelle]):
            assert chiffrement.dechiffrer(tourne) == secret


def test_confirmation_et_un_seul_authenticator_actif(etab_a):
    import pyotp

    utilisateur = creer_utilisateur(etab_a, "d.faye@banque-a.sn")
    with contexte_tenant(etab_a.id):
        premier, s1 = mfa.creer_authenticator_en_attente(utilisateur)
        assert not mfa.confirmer_authenticator(premier, "000000")
        assert mfa.confirmer_authenticator(premier, pyotp.TOTP(s1).now())
        second, s2 = mfa.creer_authenticator_en_attente(utilisateur)
        assert mfa.confirmer_authenticator(second, pyotp.TOTP(s2).now())
        statuts = dict(AuthenticatorTOTP.objects.values_list("id", "statut"))
    assert statuts == {premier.id: "REVOQUE", second.id: "ACTIF"}


# --- RLS des nouvelles tables (§ 3.5, politique « tenant ou plateforme ») -----------------------


def _alias_app() -> str:
    return "applicatif" if "applicatif" in settings.DATABASES else "default"


@pytest.mark.django_db(transaction=True, databases=["default", "audit", "applicatif"])
def test_rls_tenant_ou_plateforme_des_tables_b5():
    etab_a = creer_etablissement("rls-a")
    etab_b = creer_etablissement("rls-b")
    a = creer_compte(etab_a, "a@rls.sn")
    b = creer_compte(etab_b, "b@rls.sn")
    s = creer_compte_super_admin("s@rls.test")
    for compte in (a, b, s):
        with contexte_de(compte.utilisateur):
            definir_mot_de_passe(compte.utilisateur, "Autre-Phrase-Secrete-77")
    alias = _alias_app()
    connexion = connections[alias]
    with connexion.cursor() as c:
        c.execute("SELECT current_user")
        assert c.fetchone()[0] == settings.ALPHA_DB_APP_ROLE

    def compter(table: str) -> set:
        with connexion.cursor() as c:
            c.execute(f"SELECT DISTINCT utilisateur_id FROM {table}")  # noqa: S608
            return {u for (u,) in c.fetchall()}

    for table in ("authenticator_totp", "code_secours", "historique_mot_de_passe"):
        with transaction.atomic(using=alias):
            assert compter(table) == set()  # sans contexte : rien
        with contexte_tenant(etab_a.id, using=alias):
            assert compter(table) == {a.utilisateur.id}
        with contexte_tenant(
            None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=s.utilisateur.id, using=alias
        ):
            assert compter(table) == {s.utilisateur.id}
        with contexte_tenant(
            None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=uuid.uuid4(), using=alias
        ):
            assert compter(table) == set()

    # Écriture croisée refusée (WITH CHECK).
    with (
        pytest.raises(DatabaseError),
        contexte_tenant(etab_a.id, using=alias),
        connexion.cursor() as c,
    ):
        c.execute(
            "INSERT INTO historique_mot_de_passe (id, etablissement_id, utilisateur_id, "
            "password, cree_le) VALUES (%s, %s, %s, 'x', now())",
            [str(uuid.uuid4()), str(etab_b.id), str(b.utilisateur.id)],
        )


@pytest.mark.django_db
def test_politique_tenant_ou_plateforme_posee_sur_les_tables_b5():
    with connections["default"].cursor() as c:
        c.execute(
            "SELECT tablename, policyname FROM pg_policies WHERE tablename = ANY(%s)",
            [list(TABLES_B5)],
        )
        politiques = set(c.fetchall())
    assert politiques == {(t, "isolation_tenant_ou_plateforme") for t in TABLES_B5}


# --- Politique de mot de passe (§ 4.9, P3) -----------------------------------------------------


@pytest.mark.django_db
def test_politique_et_historique_des_mots_de_passe(etab_a):
    utilisateur = creer_utilisateur(etab_a, "e.ndiaye@banque-a.sn", prenom="Ena", nom="Ndiaye")
    with contexte_tenant(etab_a.id):
        for refuse in (
            "court-A1!",
            "toutenminuscules",
            "Soleil-Dakar-1987",
            "E.Ndiaye@banque-a.sn",
        ):
            with pytest.raises(ValidationError):
                definir_mot_de_passe(utilisateur, refuse)
        definir_mot_de_passe(utilisateur, "Baobab-Pirogue-Teranga!")
        assert utilisateur.mdp_modifie_le is not None
        definir_mot_de_passe(utilisateur, "Second-Baobab-Pirogue!")
        with pytest.raises(ValidationError, match="déjà été utilisé"):
            definir_mot_de_passe(utilisateur, "Baobab-Pirogue-Teranga!")
        assert HistoriqueMotDePasse.objects.filter(utilisateur=utilisateur).count() == 2
        assert all(
            h.startswith("argon2")
            for h in HistoriqueMotDePasse.objects.values_list("password", flat=True)
        )


@transactionnel
def test_expiration_optionnelle_du_mot_de_passe(client_csrf, etab_a):
    import datetime

    from django.utils import timezone

    from tests.outils_auth import regler

    compte = creer_compte(etab_a)
    r = se_connecter(client_csrf, compte)
    assert r.json()["utilisateur"]["mot_de_passe_expire"] is False  # désactivée par défaut
    regler(etab_a, mdp_expiration_jours=90)
    with contexte_de(compte.utilisateur):
        compte.utilisateur.mdp_modifie_le = timezone.now() - datetime.timedelta(days=91)
        compte.utilisateur.save()
    assert client_csrf.get("/api/v1/auth/session").json()["mot_de_passe_expire"] is True

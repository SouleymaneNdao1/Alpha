"""T4 · Sécurité de l'authentification : compléments aux tests B5/B6/B9.

Déjà couverts ailleurs (voir ``test_auth_*``, ``test_b6_*``, ``test_b9_moi``) : verrouillage,
limites
de débit, rejeu TOTP à la connexion et au step-up, codes de secours à usage unique, CSRF des vues
d'authentification, changement de mot de passe. Ici :

- énumération de comptes : réponses strictement identiques ET temps comparables ;
- parité des limites de débit entre comptes connus et inconnus, en-tête X-Forwarded-For forgé ;
- anti-rejeu étendu (monotonie du pas, autres parcours, course entre deux sessions) ;
- fixation de session, rejeu d'un cookie après déconnexion ;
- CSRF exigé sur TOUTES les routes d'écriture (générées depuis le routeur), contrôle d'Origin ;
- attributs des cookies (httpOnly, SameSite, Secure) dans la configuration de production ;
- expiration du mot de passe (P3) : bornes, réglage par établissement, TOUTES les routes ;
- invalidation des sessions après réinitialisation MFA (administrateur, console FYXOP).
"""

from __future__ import annotations

import datetime
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pyotp
import pytest
from django.conf import settings as django_settings
from django.db import connections
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from alpha.comptes import mfa
from alpha.comptes.models import AuthenticatorTOTP, StatutAuthenticator, StatutUtilisateur
from tests.conftest import ouvrir_session
from tests.fabriques import BanqueFactory, UtilisateurFactory
from tests.outils_admin import creer_admin
from tests.outils_auth import (
    MDP,
    UA_CHROME_WIN,
    URL_CONNEXION,
    URL_CSRF,
    URL_DECONNEXION,
    URL_MFA,
    URL_SESSION,
    contexte_de,
    creer_compte,
    equiper,
    evenements,
    jeton_csrf,
    poster,
    recharger,
    regler,
    se_connecter,
)
from tests.outils_b6 import API_AUTH, lien_de, messages_pour

pytest_plugins = ["tests.fixtures_auth"]
# Les échecs d'authentification sont journalisés par la connexion indépendante « audit ».
pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "audit"])

IDENTIFIANTS_INVALIDES = "IDENTIFIANTS_INVALIDES"


def _client(**extra) -> Client:
    return Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN, **extra)


def _libere(compte) -> None:
    """Oublie le dernier pas TOTP consommé (plusieurs step-ups dans un même test)."""
    with contexte_de(compte.utilisateur):
        AuthenticatorTOTP.objects.filter(statut=StatutAuthenticator.ACTIF).update(dernier_pas=None)


# --- Énumération de comptes -------------------------------------------------------------------


def _tenter(email: str, mot_de_passe: str, ip: str):
    client = _client()
    return poster(
        client, URL_CONNEXION, {"email": email, "mot_de_passe": mot_de_passe}, REMOTE_ADDR=ip
    )


def _empreinte_reponse(r) -> tuple:
    """Tout ce que voit un attaquant : statut, corps, en-têtes (hors valeurs par requête)."""
    variables = {"date", "x-request-id", "set-cookie", "content-length"}
    entetes = tuple(
        sorted((k.lower(), v) for k, v in r.headers.items() if k.lower() not in variables)
    )
    cookies = tuple(sorted(r.cookies.keys()))
    return r.status_code, r.json(), entetes, cookies


@pytest.fixture
def population(etab_a):
    """Un compte de chaque sorte : actif, suspendu, invité (sans mot de passe), verrouillé."""
    regler(etab_a, tentatives_max=100)
    actif = creer_compte(etab_a, email="actif@banque-a.sn")
    suspendu = creer_compte(etab_a, email="suspendu@banque-a.sn")
    with contexte_de(suspendu.utilisateur):
        type(suspendu.utilisateur).objects.filter(pk=suspendu.utilisateur.pk).update(
            statut=StatutUtilisateur.SUSPENDU
        )
    invite = UtilisateurFactory(
        etablissement=etab_a, email="invite@banque-a.sn", statut=StatutUtilisateur.INVITE
    )
    verrouille = creer_compte(etab_a, email="verrouille@banque-a.sn")
    with contexte_de(verrouille.utilisateur):
        type(verrouille.utilisateur).objects.filter(pk=verrouille.utilisateur.pk).update(
            verrouille_jusqua=timezone.now() + datetime.timedelta(hours=1)
        )
    return {"actif": actif, "suspendu": suspendu, "invite": invite, "verrouille": verrouille}


def test_connexion_meme_reponse_pour_tous_les_echecs(etab_a, population):
    """E-mail inconnu, mauvais mot de passe, compte suspendu/invité/verrouillé (même avec le BON
    mot de passe) : réponses indiscernables (statut, corps, en-têtes, cookies posés)."""
    cas = {
        "inconnu": ("personne@banque-a.sn", MDP),
        "inconnu_autre_casse": ("PERSONNE@banque-a.sn", MDP),
        "mot_de_passe_faux": (population["actif"].email, "Faux-Mdp-0123456!"),
        "suspendu_bon_mdp": (population["suspendu"].email, MDP),
        "suspendu_mauvais_mdp": (population["suspendu"].email, "Faux-Mdp-0123456!"),
        "invite": (population["invite"].email, MDP),
        "verrouille_bon_mdp": (population["verrouille"].email, MDP),
        "verrouille_mauvais_mdp": (population["verrouille"].email, "Faux-Mdp-0123456!"),
    }
    vus = {}
    for i, (nom, (email, mdp)) in enumerate(cas.items()):
        r = _tenter(email, mdp, f"10.20.0.{i + 1}")
        vus[nom] = _empreinte_reponse(r)
        assert r.status_code == 401 and r.json()["code"] == IDENTIFIANTS_INVALIDES, (nom, r.content)
        assert "alpha_sid" not in r.cookies or not r.cookies["alpha_sid"].value, nom
    reference = vus["inconnu"]
    differents = [nom for nom, v in vus.items() if v != reference]
    assert not differents, f"Réponses distinguables de « e-mail inconnu » : {differents}"


def test_connexion_temps_de_reponse_comparable_inconnu_ou_connu(etab_a, population):
    """Un e-mail inconnu coûte autant (hachage factice) qu'un mot de passe faux : écart < 50 %."""
    inconnu, faux, suspendu = [], [], []
    for i in range(10):
        ip = f"10.30.{i}.1"
        t0 = time.perf_counter()
        _tenter(f"absent{i}@banque-a.sn", "Faux-Mdp-0123456!", ip)
        inconnu.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        _tenter(population["actif"].email, "Faux-Mdp-0123456!", ip)
        faux.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        _tenter(population["suspendu"].email, MDP, ip)
        suspendu.append(time.perf_counter() - t0)
    m_inconnu, m_faux, m_suspendu = (statistics.median(x) for x in (inconnu, faux, suspendu))
    assert abs(m_inconnu - m_faux) < 0.5 * m_faux, (m_inconnu, m_faux)
    assert abs(m_suspendu - m_faux) < 0.5 * m_faux, (m_suspendu, m_faux)


def test_reponse_identique_oubli_et_telephone_perdu_compte_inconnu(etab_a, population):
    """Les parcours publics qui reçoivent un e-mail ne révèlent pas l'existence du compte."""
    for url, corps_connu, corps_inconnu in (
        (
            f"{API_AUTH}/mot-de-passe/oubli",
            {"email": population["actif"].email},
            {"email": "personne@banque-a.sn"},
        ),
        (
            f"{API_AUTH}/telephone-perdu",
            {"email": population["actif"].email, "mot_de_passe": "Faux-Mdp-0123456!"},
            {"email": "personne@banque-a.sn", "mot_de_passe": "Faux-Mdp-0123456!"},
        ),
    ):
        a = poster(_client(), url, corps_connu, REMOTE_ADDR="10.40.0.1")
        b = poster(_client(), url, corps_inconnu, REMOTE_ADDR="10.40.0.2")
        assert a.status_code == b.status_code == 202, (url, a.content, b.content)
        assert a.json() == b.json()


# --- Limites de débit : même traitement pour les comptes inconnus ----------------------------


def test_limite_par_email_identique_pour_un_compte_inconnu_et_connu(etab_a, population):
    """Au 21e essai le blocage (429) tombe au même rang, que le compte existe ou non."""

    def rang_du_429(email: str) -> int:
        for essai in range(1, 40):
            r = _tenter(email, "Faux-Mdp-0123456!", f"10.50.{essai}.{abs(hash(email)) % 200}")
            if r.status_code == 429:
                return essai
        return -1

    assert rang_du_429("personne@banque-a.sn") == rang_du_429(population["actif"].email) == 21


def test_x_forwarded_for_forge_ne_contourne_pas_la_limite_par_ip(etab_a, population):
    """Seule l'adresse ajoutée par le proxy de confiance (à droite) compte, pas celles du client."""
    reponses = []
    for i in range(12):
        client = _client()
        r = poster(
            client,
            URL_CONNEXION,
            {"email": f"absent{i}@banque-a.sn", "mot_de_passe": "Faux-Mdp-0123456!"},
            REMOTE_ADDR="172.18.0.2",
            HTTP_X_FORWARDED_FOR=f"203.0.113.{i + 1}, 198.51.100.7",
        )
        reponses.append(r.status_code)
    assert reponses[:10] == [401] * 10
    assert reponses[10:] == [429, 429]


def test_casse_et_espaces_de_l_email_comptent_pour_le_verrouillage(etab_a):
    regler(etab_a, tentatives_max=3, verrouillage_min=10)
    compte = creer_compte(etab_a, email="a.diop@banque-a.sn")
    for i, variante in enumerate(
        ("A.DIOP@banque-a.sn", " a.diop@BANQUE-a.sn ", "a.Diop@banque-a.sn")
    ):
        r = _tenter(variante, "Faux-Mdp-0123456!", f"10.60.0.{i + 1}")
        assert r.status_code == 401, variante
    assert recharger(compte.utilisateur).verrouille_jusqua is not None
    # Verrouillé : le bon mot de passe est refusé dans toutes les graphies.
    assert _tenter("a.diop@banque-a.sn", MDP, "10.60.0.9").status_code == 401


# --- Anti-rejeu étendu -------------------------------------------------------------------------


def _preauth(compte, ip: str) -> Client:
    client = _client()
    r = poster(client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP}, REMOTE_ADDR=ip)
    assert r.json()["etape"] == "MFA_REQUIS", r.content
    return client


def test_totp_le_pas_ne_peut_que_croitre(etab_a):
    """Après un code du pas suivant, un code du pas courant (antérieur) est refusé."""
    compte = creer_compte(etab_a)
    client = _preauth(compte, "10.70.0.1")
    r = poster(client, URL_MFA, {"code": compte.totp(+1)})
    assert r.status_code == 200, r.content
    poster(client, URL_DECONNEXION)
    client = _preauth(compte, "10.70.0.2")
    assert poster(client, URL_MFA, {"code": compte.totp(0)}).status_code == 401
    assert poster(client, URL_MFA, {"code": compte.totp(-1)}).status_code == 401


def test_code_utilise_a_la_connexion_ne_resservira_pas_a_la_reinitialisation(etab_a):
    compte = creer_compte(etab_a, email="m.sow@banque-a.sn")
    client = _client()
    se_connecter(client, compte, code=compte.totp(+1))
    anonyme = _client()
    mail_envoye = poster(anonyme, f"{API_AUTH}/mot-de-passe/oubli", {"email": compte.email})
    assert mail_envoye.status_code == 202
    from django.core import mail

    jeton = lien_de(messages_pour(compte.email, "Réinitialisation")[0], "/reinitialisation/")
    mail.outbox.clear()
    url = f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}"
    nouveau = "Fromager-Solide-93!z"
    r = poster(
        anonyme, url, {"mot_de_passe": nouveau, "confirmation": nouveau, "code": compte.totp(+1)}
    )
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert recharger(compte.utilisateur).check_password(MDP)


def test_code_de_secours_utilise_ne_resservira_nulle_part(etab_a):
    compte = creer_compte(etab_a, email="m.sow@banque-a.sn")
    code = compte.codes[0]
    client = _preauth(compte, "10.71.0.1")
    assert poster(client, URL_MFA, {"code_secours": code}).status_code == 200
    # Même code, graphies différentes (minuscules, sans tiret) : refusé à la connexion...
    for graphie in (code, code.lower(), code.replace("-", "")):
        autre = _preauth(compte, "10.71.0.2")
        r = poster(autre, URL_MFA, {"code_secours": graphie})
        assert r.status_code == 401, graphie
    # ... et à la réinitialisation du mot de passe.
    anonyme = _client()
    poster(anonyme, f"{API_AUTH}/mot-de-passe/oubli", {"email": compte.email})
    jeton = lien_de(messages_pour(compte.email, "Réinitialisation")[0], "/reinitialisation/")
    nouveau = "Fromager-Solide-93!z"
    r = poster(
        anonyme,
        f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}",
        {"mot_de_passe": nouveau, "confirmation": nouveau, "code_secours": code},
    )
    assert r.status_code == 401, r.content
    assert recharger(compte.utilisateur).check_password(MDP)


def _course(compte, corps_mfa: dict, n: int = 4) -> list[int]:
    """n sessions pré-authentifiées soumettent EN MÊME TEMPS le même code ; statuts obtenus."""
    clients = [_preauth(compte, f"10.72.{i}.1") for i in range(n)]
    barriere = threading.Barrier(n)

    def tirer(client):
        try:
            barriere.wait(timeout=30)
            return poster(client, URL_MFA, corps_mfa).status_code
        finally:
            for alias in ("default", "audit"):
                connections[alias].close()

    with ThreadPoolExecutor(max_workers=n) as executeur:
        return [t.result(timeout=120) for t in [executeur.submit(tirer, c) for c in clients]]


def test_course_un_meme_code_totp_ne_sert_qu_une_fois(etab_a):
    compte = creer_compte(etab_a)
    statuts = _course(compte, {"code": compte.totp(+1)})
    assert sorted(statuts) == [200, 401, 401, 401], statuts


def test_course_un_meme_code_de_secours_ne_sert_qu_une_fois(etab_a):
    compte = creer_compte(etab_a)
    statuts = _course(compte, {"code_secours": compte.codes[3]})
    assert sorted(statuts) == [200, 401, 401, 401], statuts


# --- Fixation de session, rejeu de cookie -----------------------------------------------------


def test_cle_de_session_imposee_par_l_attaquant_n_est_pas_adoptee(etab_a):
    compte = creer_compte(etab_a)
    client = _client()
    imposee = "attaquant" + uuid.uuid4().hex
    client.cookies["alpha_sid"] = imposee
    se_connecter(client, compte)
    assert client.cookies["alpha_sid"].value != imposee
    # Le cookie imposé n'ouvre aucune session.
    pirate = _client()
    pirate.cookies["alpha_sid"] = imposee
    assert pirate.get(URL_SESSION).status_code == 401


def test_cookie_de_preauthentification_inutilisable_apres_la_connexion(etab_a):
    compte = creer_compte(etab_a)
    client = _client()
    poster(client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    cookie_preauth = client.cookies["alpha_sid"].value
    assert poster(client, URL_MFA, {"code": compte.totp(+1)}).status_code == 200
    assert client.cookies["alpha_sid"].value != cookie_preauth
    ancien = _client()
    ancien.cookies["alpha_sid"] = cookie_preauth
    assert ancien.get(URL_SESSION).status_code == 401
    assert ancien.get("/api/v1/moi").status_code in (401, 403)


def test_cookie_rejoue_apres_deconnexion_ne_donne_plus_acces(etab_a):
    compte = creer_compte(etab_a)
    client = _client()
    se_connecter(client, compte)
    cookie = client.cookies["alpha_sid"].value
    assert client.get("/api/v1/moi").status_code == 200
    assert poster(client, URL_DECONNEXION).status_code == 204
    rejoue = _client()
    rejoue.cookies["alpha_sid"] = cookie
    assert rejoue.get("/api/v1/moi").status_code == 401
    assert rejoue.get(URL_SESSION).status_code == 401


def test_nouvelle_connexion_tourne_la_session_et_le_jeton_csrf(etab_a):
    compte = creer_compte(etab_a)
    client = _client()
    jeton_csrf(client)
    avant_sid, avant_csrf = None, client.cookies["alpha_csrf"].value
    se_connecter(client, compte)
    assert client.cookies["alpha_csrf"].value != avant_csrf
    premier_sid = client.cookies["alpha_sid"].value
    assert premier_sid != avant_sid
    # Reconnexion depuis la même session : nouvelle clé, ancienne invalide.
    se_connecter(client, compte, code=compte.totp(+1))
    assert client.cookies["alpha_sid"].value != premier_sid
    ancien = _client()
    ancien.cookies["alpha_sid"] = premier_sid
    assert ancien.get("/api/v1/moi").status_code == 401


# --- CSRF sur toutes les routes d'écriture ----------------------------------------------------

PARAMETRE = re.compile(r"<(?:\w+:)?(\w+)>")


def _routes_d_ecriture() -> list[tuple[str, str]]:
    resultat: list[tuple[str, str]] = []

    def parcourir(motifs, prefixe=""):
        for motif in motifs:
            chemin = prefixe + str(motif.pattern)
            if isinstance(motif, URLResolver):
                parcourir(motif.url_patterns, chemin)
            elif isinstance(motif, URLPattern):
                vue = getattr(motif.callback, "view_class", None)
                if vue is None or not chemin.startswith("api/v1/"):
                    continue
                concret = PARAMETRE.sub(lambda m: str(uuid.uuid4()), "/" + chemin)
                concret = concret.replace("<uuid:", "<").replace("<str:", "<")
                concret = re.sub(r"<\w+>", lambda m: "x" + uuid.uuid4().hex[:8], concret)
                for methode in ("post", "put", "patch", "delete"):
                    if hasattr(vue, methode):
                        resultat.append((methode, concret))

    parcourir(get_resolver().url_patterns)
    return sorted(resultat)


ROUTES_ECRITURE = _routes_d_ecriture()


def test_l_enumeration_des_routes_d_ecriture_est_complete():
    chemins = {c.rsplit("/", 1)[0] for _, c in ROUTES_ECRITURE}
    assert len(ROUTES_ECRITURE) >= 45, len(ROUTES_ECRITURE)
    assert any("/auth/connexion" in c for _, c in ROUTES_ECRITURE)
    assert any("/plateforme/etablissements" in c for _, c in ROUTES_ECRITURE)
    assert any("/admin/roles" in c for _, c in ROUTES_ECRITURE)
    assert chemins


def test_toute_ecriture_sans_jeton_csrf_est_refusee_anonyme_ou_connecte(etab_a, utilisateur_a):
    """Aucune route d'écriture n'échappe au contrôle CSRF, connecté ou non."""
    anonyme = Client(enforce_csrf_checks=True)
    connecte = ouvrir_session(APIClient(enforce_csrf_checks=True), utilisateur_a)
    fautes = []
    for methode, chemin in ROUTES_ECRITURE:
        for nom, client in (("anonyme", anonyme), ("connecté", connecte)):
            if nom == "anonyme":
                r = getattr(client, methode)(chemin, "{}", content_type="application/json")
            else:
                r = getattr(client, methode)(chemin, {}, format="json")
            corps = r.json() if r.content else {}
            if r.status_code != 403 or corps.get("code") != "CSRF_INVALIDE":
                fautes.append(f"{methode.upper()} {chemin} ({nom}) -> {r.status_code} {corps}")
    assert not fautes, "Écritures non protégées contre le CSRF :\n" + "\n".join(fautes)


def test_jeton_csrf_valide_mais_origine_etrangere_refuse(etab_a):
    compte = creer_compte(etab_a)
    client = _client()
    jeton = jeton_csrf(client)
    r = client.post(
        URL_CONNEXION,
        {"email": compte.email, "mot_de_passe": MDP},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=jeton,
        HTTP_ORIGIN="https://pirate.example",
    )
    assert r.status_code == 403 and r.json()["code"] == "CSRF_INVALIDE"
    ok = client.post(
        URL_CONNEXION,
        {"email": compte.email, "mot_de_passe": MDP},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=jeton,
        HTTP_ORIGIN=django_settings.ALPHA_URL_FRONTEND,
    )
    assert ok.status_code == 200, ok.content


def test_jeton_csrf_d_une_autre_session_refuse(etab_a):
    """Le jeton lu dans le cookie d'un client ne vaut pas pour le cookie d'un autre."""
    a, b = _client(), _client()
    jeton_a = jeton_csrf(a)
    jeton_csrf(b)
    r = b.post(URL_CONNEXION, {}, content_type="application/json", HTTP_X_CSRFTOKEN=jeton_a)
    assert r.status_code == 403 and r.json()["code"] == "CSRF_INVALIDE"


# --- Attributs des cookies ---------------------------------------------------------------------


def test_cookies_de_session_et_csrf_en_configuration_de_production(settings, etab_a):
    """Avec Secure activé (production), Set-Cookie porte HttpOnly/Secure/SameSite pour la session,
    Secure/SameSite (sans HttpOnly, lu par le frontend) pour le jeton CSRF."""
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    compte = creer_compte(etab_a)
    client = _client()
    r = client.get(URL_CSRF)
    csrf = r.cookies["alpha_csrf"]
    assert csrf["secure"] and csrf["samesite"] == "Lax" and not csrf["httponly"]
    r = poster(client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP})
    sid = r.cookies["alpha_sid"]
    assert sid["secure"] and sid["httponly"] and sid["samesite"] == "Lax" and sid["path"] == "/"
    assert not sid["max-age"] or int(sid["max-age"]) <= 24 * 3600  # navigateur : cookie de session
    r = poster(client, URL_MFA, {"code": compte.totp()})
    sid = r.cookies["alpha_sid"]
    assert sid["secure"] and sid["httponly"] and sid["samesite"] == "Lax"
    r = poster(client, URL_DECONNEXION)
    suppression = r.cookies["alpha_sid"]
    assert suppression["samesite"] == "Lax" and suppression["max-age"] == 0


def test_les_reglages_de_production_posent_les_attributs_de_securite():
    """Importe réellement ``config.settings.prod`` (processus séparé) et lit les réglages."""
    code = (
        "import django, json;django.setup();from django.conf import settings as s;"
        "print(json.dumps({k: getattr(s, k) for k in ("
        "'SESSION_COOKIE_SECURE','SESSION_COOKIE_HTTPONLY','SESSION_COOKIE_SAMESITE',"
        "'CSRF_COOKIE_SECURE','CSRF_COOKIE_SAMESITE','CSRF_COOKIE_HTTPONLY','DEBUG',"
        "'SECURE_HSTS_SECONDS','SESSION_EXPIRE_AT_BROWSER_CLOSE','SECURE_PROXY_SSL_HEADER')}))"
    )
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.prod"}
    env["DJANGO_ALLOWED_HOSTS"] = "alpha.exemple.test"
    sortie = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys;sys.path.insert(0,{str(django_settings.BASE_DIR)!r});{code}",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=Path(django_settings.BASE_DIR),
    )
    assert sortie.returncode == 0, sortie.stderr[-800:]
    import json

    prod = json.loads(sortie.stdout.strip().splitlines()[-1])
    assert prod["SESSION_COOKIE_SECURE"] is True and prod["CSRF_COOKIE_SECURE"] is True
    assert prod["SESSION_COOKIE_HTTPONLY"] is True and prod["CSRF_COOKIE_HTTPONLY"] is False
    assert prod["SESSION_COOKIE_SAMESITE"] == "Lax" and prod["CSRF_COOKIE_SAMESITE"] == "Lax"
    assert prod["DEBUG"] is False and prod["SECURE_HSTS_SECONDS"] >= 31_536_000
    assert prod["SESSION_EXPIRE_AT_BROWSER_CLOSE"] is True
    assert prod["SECURE_PROXY_SSL_HEADER"] == ["HTTP_X_FORWARDED_PROTO", "https"]


# --- Expiration du mot de passe (P3) -----------------------------------------------------------


def _vieillir(compte, jours: int) -> None:
    with contexte_de(compte.utilisateur):
        type(compte.utilisateur).objects.filter(pk=compte.utilisateur.pk).update(
            mdp_modifie_le=timezone.now() - datetime.timedelta(days=jours)
        )


def test_expiration_desactivee_par_defaut_meme_tres_ancien(etab_a):
    compte = creer_compte(etab_a)
    _vieillir(compte, 2000)
    client = _client()
    se_connecter(client, compte)
    assert client.get("/api/v1/moi").json()["mot_de_passe_expire"] is False
    assert client.get("/api/v1/taches").status_code == 200


def test_expiration_bornes_exactes_et_reglage_par_etablissement(etab_a, etab_b):
    regler(etab_a, mdp_expiration_jours=90)
    a = creer_compte(etab_a, email="a@banque-a.sn")
    b = creer_compte(etab_b, email="b@sfd-b.sn")  # B : pas d'expiration
    _vieillir(a, 89)
    _vieillir(b, 400)
    ca, cb = _client(), _client()
    se_connecter(ca, a)
    se_connecter(cb, b)
    assert ca.get("/api/v1/moi").json()["mot_de_passe_expire"] is False
    # 91 jours après le dernier changement : expiré chez A, jamais chez B.
    _vieillir(a, 91)
    assert ca.get("/api/v1/moi").json()["mot_de_passe_expire"] is True
    assert cb.get("/api/v1/moi").json()["mot_de_passe_expire"] is False
    # Réglage modifié : 365 jours, A n'est plus expiré.
    regler(etab_a, mdp_expiration_jours=365)
    assert ca.get("/api/v1/moi").json()["mot_de_passe_expire"] is False


def _routes_etablissement() -> list[tuple[str, str, bool]]:
    """(méthode, chemin, autorise_mot_de_passe_expire) des routes d'établissement."""
    resultat = []

    def parcourir(motifs, prefixe=""):
        for motif in motifs:
            chemin = prefixe + str(motif.pattern)
            if isinstance(motif, URLResolver):
                parcourir(motif.url_patterns, chemin)
            elif isinstance(motif, URLPattern):
                vue = getattr(motif.callback, "view_class", None)
                if vue is None or not chemin.startswith("api/v1/"):
                    continue
                if chemin.startswith(
                    (
                        "api/v1/plateforme/",
                        "api/v1/auth/",
                        "api/v1/sante/",
                        "api/v1/schema",
                        "api/v1/docs",
                    )
                ):
                    continue
                concret = "/" + chemin
                concret = re.sub(r"<(?:\w+:)?\w+>", lambda m: str(uuid.uuid4()), concret)
                for methode in ("get", "post", "put", "patch", "delete"):
                    if hasattr(vue, methode):
                        resultat.append(
                            (
                                methode,
                                concret,
                                bool(getattr(vue, "autorise_mot_de_passe_expire", False)),
                            )
                        )

    parcourir(get_resolver().url_patterns)
    return sorted(resultat)


def test_mot_de_passe_expire_ferme_toutes_les_routes_sauf_mon_compte(etab_a):
    """Génération depuis le routeur : une route d'établissement qui contournerait la classe
    ``Session`` (donc l'expiration) fait échouer le test."""
    regler(etab_a, mdp_expiration_jours=90)
    from alpha.organisation.codes_permission import CodePermission
    from tests.fabriques import AffectationRoleFactory, RoleFactory

    compte = creer_compte(etab_a, email="admin@banque-a.sn")
    role = RoleFactory(etablissement=etab_a, code="tout", permissions=list(CodePermission.values))
    AffectationRoleFactory(utilisateur=compte.utilisateur, role=role, principal=True)
    _vieillir(compte, 120)
    client = _client()
    se_connecter(client, compte)
    ouvertes, fautes = [], []
    routes = _routes_etablissement()
    assert len(routes) >= 50
    # « Mon compte » a de vrais effets (téléphone perdu coupe la session) : ses routes en dernier.
    for methode, chemin, autorisee in sorted(routes, key=lambda r: r[2]):
        envoi = {} if methode == "get" else {"data": "{}", "content_type": "application/json"}
        r = getattr(client, methode)(chemin, HTTP_X_CSRFTOKEN=jeton_csrf(client), **envoi)
        corps = r.json() if r.content and r["Content-Type"].startswith("application/json") else {}
        if autorisee:
            ouvertes.append(chemin)
            assert corps.get("code") != "MOT_DE_PASSE_EXPIRE", chemin
        elif r.status_code != 403 or corps.get("code") != "MOT_DE_PASSE_EXPIRE":
            fautes.append(f"{methode.upper()} {chemin} -> {r.status_code} {str(corps)[:100]}")
    assert ouvertes  # « Mon compte » reste accessible
    assert not fautes, "Routes accessibles malgré un mot de passe expiré :\n" + "\n".join(fautes)


def test_changer_le_mot_de_passe_leve_l_expiration(etab_a):
    regler(etab_a, mdp_expiration_jours=90)
    compte = creer_compte(etab_a)
    _vieillir(compte, 100)
    client = _client()
    se_connecter(client, compte)
    assert client.get("/api/v1/taches").status_code == 403
    _libere(compte)
    nouveau = "Baobab-Sahel#42xw"
    r = poster(
        client,
        "/api/v1/moi/mot-de-passe",
        {"actuel": MDP, "nouveau": nouveau, "confirmation": nouveau, "code": compte.totp(+1)},
    )
    assert r.status_code == 204, r.content
    assert client.get("/api/v1/taches").status_code == 200
    # Le mot de passe expiré ne peut pas être « renouvelé » à l'identique.
    _libere(compte)
    r = poster(
        client,
        "/api/v1/moi/mot-de-passe",
        {"actuel": nouveau, "nouveau": nouveau, "confirmation": nouveau, "code": compte.totp(+1)},
    )
    assert r.status_code == 400, r.content


# --- Invalidation des sessions après réinitialisation MFA ------------------------------------


def _session_vivante(compte, **extra) -> Client:
    client = _client()
    se_connecter(client, compte, **extra)
    assert client.get("/api/v1/moi").status_code == 200
    return client


@pytest.fixture
def banque_t4():
    return BanqueFactory(roles_defaut=True)


def test_reinitialisation_par_un_administrateur_coupe_les_sessions_de_l_intéresse(banque_t4):
    victime = equiper(UtilisateurFactory(etablissement=banque_t4, email="v@banque.test"))
    admin = equiper(creer_admin(banque_t4, email="adm@banque.test"))
    # Perte du téléphone : signalement public, puis connexion de secours (session vivante).
    poster(
        _client(),
        f"{API_AUTH}/telephone-perdu",
        {"email": victime.email, "mot_de_passe": MDP},
    )
    vivante = _client()
    poster(vivante, URL_CONNEXION, {"email": victime.email, "mot_de_passe": MDP})
    assert poster(vivante, URL_MFA, {"code_secours": victime.codes[0]}).status_code == 200
    assert vivante.get(URL_SESSION).status_code == 200

    from alpha.comptes.models import SignalementTelephonePerdu
    from alpha.tenancy.contexte import contexte_tenant

    with contexte_tenant(banque_t4.id):
        signalement = SignalementTelephonePerdu.objects.get(utilisateur=victime.utilisateur)
    client_admin = ouvrir_session(APIClient(), admin.utilisateur)
    with mock.patch.object(mfa, "verifier_step_up", return_value=(mfa.STEP_UP_OK, None)):
        r = client_admin.post(
            f"/api/v1/admin/signalements-telephone/{signalement.id}/reinitialiser",
            {"mode_verification": "VISIO", "commentaire": "visio", "code": "123456"},
            format="json",
        )
    assert r.status_code == 200, r.content
    assert vivante.get(URL_SESSION).status_code == 401
    assert vivante.get("/api/v1/moi").status_code == 401


def test_reinitialisation_par_la_console_coupe_les_sessions_de_l_administrateur(banque_t4):
    seul = equiper(creer_admin(banque_t4, email="seul@banque.test"))
    vivante = _session_vivante(seul)
    super_admin = UtilisateurFactory(super_admin=True, email="ops@fyxop.test")
    console = ouvrir_session(APIClient(), super_admin)
    with mock.patch.object(mfa, "verifier_step_up", return_value=(mfa.STEP_UP_OK, None)):
        r = console.post(
            f"/api/v1/plateforme/etablissements/{banque_t4.id}/reinitialisation-authenticator",
            {
                "email": seul.email,
                "reference_demande": "DG/2026/114",
                "commentaire": "visio",
                "code": "123456",
            },
            format="json",
        )
    assert r.status_code == 200, r.content
    assert recharger(seul.utilisateur).mfa_a_reconfigurer
    assert vivante.get("/api/v1/moi").status_code == 401
    assert vivante.get(URL_SESSION).status_code == 401
    # La reconnexion impose le réenrôlement, jamais l'ancien code.
    r = poster(_client(), URL_CONNEXION, {"email": seul.email, "mot_de_passe": MDP})
    assert r.json()["etape"] == "REENROLEMENT_REQUIS"
    assert evenements(banque_t4.id, "telephone.reinitialise")


def test_changement_de_mot_de_passe_par_reinitialisation_coupe_toutes_les_sessions(etab_a):
    compte = creer_compte(etab_a, email="m.sow@banque-a.sn")
    s1 = _session_vivante(compte)
    _libere(compte)
    s2 = _session_vivante(compte, code=compte.totp(+1))
    anonyme = _client()
    poster(anonyme, f"{API_AUTH}/mot-de-passe/oubli", {"email": compte.email})
    jeton = lien_de(messages_pour(compte.email, "Réinitialisation")[0], "/reinitialisation/")
    nouveau = "Fromager-Solide-93!z"
    _libere(compte)
    r = poster(
        anonyme,
        f"{API_AUTH}/mot-de-passe/reinitialisation/{jeton}",
        {"mot_de_passe": nouveau, "confirmation": nouveau, "code": compte.totp(+1)},
    )
    assert r.status_code == 204, r.content
    assert s1.get("/api/v1/moi").status_code == 401
    assert s2.get("/api/v1/moi").status_code == 401


_ = (pyotp, StatutAuthenticator, timezone)

"""Verrouillage, blocage administrateur et limitation de débit (§ 4.2 étapes 2, 5, 7, 10 ; P2)."""

from __future__ import annotations

import datetime

from django.core import mail
from freezegun import freeze_time

from tests.outils_auth import (
    MDP,
    URL_CONNEXION,
    URL_MFA,
    creer_compte,
    evenements,
    poster,
    recharger,
    regler,
    transactionnel,
)

# Fixtures client_csrf et vider_limites (autouse).
pytest_plugins = ["tests.fixtures_auth"]
pytestmark = transactionnel


def _dans(minutes: int):
    return freeze_time(datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=minutes))


def _mdp(client, compte, mot_de_passe, **extra):
    return poster(
        client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": mot_de_passe}, **extra
    )


def test_verrouillage_apres_n_echecs_regle_par_l_etablissement(client_csrf, etab_a):
    regler(etab_a, tentatives_max=3, verrouillage_min=10)
    compte = creer_compte(etab_a)
    for _ in range(2):
        assert _mdp(client_csrf, compte, "mauvais-mot-de-passe").status_code == 401
    assert recharger(compte.utilisateur).echecs_connexion == 2
    assert _mdp(client_csrf, compte, "mauvais-mot-de-passe").status_code == 401
    utilisateur = recharger(compte.utilisateur)
    assert utilisateur.verrouille_jusqua is not None
    assert utilisateur.verrouillages_24h == 1 and utilisateur.echecs_connexion == 0
    # Verrouillé : même le bon mot de passe est refusé, avec la même réponse.
    r = _mdp(client_csrf, compte, MDP)
    assert r.status_code == 401 and r.json()["code"] == "IDENTIFIANTS_INVALIDES"

    echecs = evenements(etab_a.id, "auth.connexion.echec")
    assert [e.apres["motif"] for e in echecs] == ["MOT_DE_PASSE"] * 3 + ["COMPTE_VERROUILLE"]
    (verrou,) = evenements(etab_a.id, "auth.verrouillage")
    assert verrou.apres["bloque_par_admin"] is False
    assert any("verrouillé" in m.subject for m in mail.outbox)

    # Après la durée de verrouillage de l'établissement (10 min), la connexion repasse.
    with _dans(11):
        assert _mdp(client_csrf, compte, MDP).json()["etape"] == "MFA_REQUIS"


def test_troisieme_verrouillage_en_24h_deblocage_administrateur(client_csrf, etab_a):
    regler(etab_a, tentatives_max=2, verrouillage_min=1, verrouillages_max_24h=3)
    compte = creer_compte(etab_a)
    for vague in range(3):
        with _dans(vague * 2):
            for _ in range(2):
                _mdp(client_csrf, compte, "mauvais-mot-de-passe")
    utilisateur = recharger(compte.utilisateur)
    assert utilisateur.verrouillages_24h == 3 and utilisateur.bloque_par_admin is True
    with _dans(60):
        assert _mdp(client_csrf, compte, MDP).status_code == 401
    assert evenements(etab_a.id, "auth.verrouillage")[-1].apres["bloque_par_admin"] is True


def test_echecs_mfa_tentatives_restantes_puis_423(client_csrf, etab_a):
    regler(etab_a, tentatives_max=3)
    compte = creer_compte(etab_a)
    assert _mdp(client_csrf, compte, MDP).status_code == 200
    r = poster(client_csrf, URL_MFA, {"code": "000000"})
    assert r.status_code == 401 and r.json()["details"] == {"tentatives_restantes": 2}
    r = poster(client_csrf, URL_MFA, {"code_secours": "AAAA-AAAA"})
    assert r.status_code == 401 and r.json()["details"] == {"tentatives_restantes": 1}
    r = poster(client_csrf, URL_MFA, {"code": "000000"})
    assert r.status_code == 423
    corps = r.json()
    assert corps["code"] == "COMPTE_VERROUILLE"
    assert corps["details"]["jusqua"] and corps["details"]["deblocage_administrateur"] is False
    # Pré-authentification effacée.
    r = poster(client_csrf, URL_MFA, {"code": compte.totp()})
    assert r.status_code == 401 and r.json()["code"] == "PREAUTH_EXPIREE"
    motifs = [e.apres["motif"] for e in evenements(etab_a.id, "auth.connexion.echec")]
    assert motifs == ["MFA", "MFA", "MFA"]
    assert len(evenements(etab_a.id, "auth.verrouillage")) == 1


def test_echecs_mot_de_passe_et_mfa_cumules_puis_remise_a_zero(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    _mdp(client_csrf, compte, "mauvais-mot-de-passe")
    _mdp(client_csrf, compte, MDP)
    r = poster(client_csrf, URL_MFA, {"code": "000000"})
    assert r.json()["details"] == {"tentatives_restantes": 3}
    assert poster(client_csrf, URL_MFA, {"code": compte.totp()}).status_code == 200
    assert recharger(compte.utilisateur).echecs_connexion == 0


def test_limite_10_par_minute_par_ip(client_csrf, etab_a):
    compte = creer_compte(etab_a)
    for _ in range(10):
        assert _mdp(client_csrf, compte, "x" * 12).status_code in (401,)
        regler(etab_a, tentatives_max=100)  # ne pas verrouiller pendant le test
    r = _mdp(client_csrf, compte, MDP)
    assert r.status_code == 429
    assert r.json()["code"] == "TROP_DE_REQUETES"
    assert int(r["Retry-After"]) > 0
    # Autre IP : autorisée.
    assert _mdp(client_csrf, compte, MDP, REMOTE_ADDR="10.9.9.9").status_code == 200


def test_limite_20_par_heure_par_email(client_csrf, etab_a):
    regler(etab_a, tentatives_max=100)
    compte = creer_compte(etab_a)
    for i in range(20):
        r = _mdp(client_csrf, compte, "x" * 12, REMOTE_ADDR=f"10.0.{i}.1")
        assert r.status_code == 401
    r = _mdp(client_csrf, compte, MDP, REMOTE_ADDR="10.1.1.1")
    assert r.status_code == 429
    # La clé Redis ne contient pas l'e-mail en clair.
    from django.core.cache import cache

    cles = [str(c) for c in cache.keys("limite:*")]
    assert cles and not any("diop" in c for c in cles)


def test_limite_5_par_minute_par_session_sur_mfa(client_csrf, etab_a):
    regler(etab_a, tentatives_max=50)
    compte = creer_compte(etab_a)
    _mdp(client_csrf, compte, MDP)
    for _ in range(5):
        assert poster(client_csrf, URL_MFA, {"code": "000000"}).status_code == 401
    r = poster(client_csrf, URL_MFA, {"code": compte.totp()})
    assert r.status_code == 429 and "Retry-After" in r

"""Outils des tests d'authentification (tâche B5) ; fixtures dans ``tests/fixtures_auth.py``.

Écrits pour tourner aussi sous ``alpha_app`` (après T1) : toute lecture ou
écriture d'un modèle tenant se fait sous ``contexte_tenant``.

- ``poster`` : POST JSON avec l'en-tête X-CSRFToken lu dans le cookie ``alpha_csrf`` ;
- ``creer_compte`` : utilisateur actif avec mot de passe, Authenticator ACTIF et codes ;
- ``se_connecter`` : flux complet mot de passe → MFA ;
- ``evenements`` : événements d'audit d'une chaîne (lus sous le contexte adéquat).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import pyotp
import pytest
from django.test import Client
from django.utils import timezone

from alpha.audit.models import EvenementAudit
from alpha.comptes import mfa
from alpha.comptes.models import Utilisateur
from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import ParametresEtablissement
from tests.fabriques import MOT_DE_PASSE_TEST, UtilisateurFactory

MDP = MOT_DE_PASSE_TEST
UA_CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
UA_FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"

URL_CSRF = "/api/v1/auth/csrf"
URL_SESSION = "/api/v1/auth/session"
URL_CONNEXION = "/api/v1/auth/connexion"
URL_MFA = "/api/v1/auth/mfa"
URL_DECONNEXION = "/api/v1/auth/deconnexion"

# Les vues d'échec écrivent l'audit par la connexion indépendante « audit » :
# les tests HTTP sont transactionnels (données validées, visibles des deux connexions).
transactionnel = pytest.mark.django_db(transaction=True, databases=["default", "audit"])


@dataclass
class Compte:
    utilisateur: Utilisateur
    secret: str
    codes: list[str]

    @property
    def email(self) -> str:
        return self.utilisateur.email

    def totp(self, decalage_pas: int = 0) -> str:
        instant = timezone.now() + datetime.timedelta(seconds=30 * decalage_pas)
        return pyotp.TOTP(self.secret).at(instant)


def _contexte_de(utilisateur: Utilisateur):
    if utilisateur.est_super_admin:
        return contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=utilisateur.id)
    return contexte_tenant(utilisateur.etablissement_id, utilisateur_id=utilisateur.id)


def contexte_de(utilisateur: Utilisateur):
    return _contexte_de(utilisateur)


def equiper(utilisateur: Utilisateur, *, totp: bool = True, codes: bool = True) -> Compte:
    """Mot de passe ``MDP``, Authenticator ACTIF confirmé, 10 codes de secours."""
    secret, liste = "", []
    with _contexte_de(utilisateur):
        utilisateur.set_password(MDP)
        utilisateur.save()
        if totp:
            authenticator, secret = mfa.creer_authenticator_en_attente(utilisateur, "Téléphone")
            # Confirmation sur le pas précédent : le pas courant reste utilisable au test.
            premier = pyotp.TOTP(secret).at(timezone.now() - datetime.timedelta(seconds=30))
            assert mfa.confirmer_authenticator(authenticator, premier)
        if codes:
            liste = mfa.generer_codes_secours(utilisateur)
    return Compte(utilisateur, secret, liste)


def creer_compte(etablissement, email: str = "a.diop@banque-a.sn", **champs) -> Compte:
    """Utilisateur ACTIF (fabrique T1) équipé pour la connexion complète."""
    return equiper(UtilisateurFactory(etablissement=etablissement, email=email, **champs))


def creer_compte_super_admin(email: str = "admin@fyxop.test") -> Compte:
    return equiper(UtilisateurFactory(super_admin=True, email=email))


def regler(etablissement, **valeurs) -> None:
    """Modifie les paramètres de sécurité de l'établissement."""
    with contexte_tenant(etablissement.id):
        ParametresEtablissement.objects.filter(etablissement_id=etablissement.id).update(**valeurs)


def recharger(utilisateur: Utilisateur) -> Utilisateur:
    with _contexte_de(utilisateur):
        return Utilisateur.objects.get(pk=utilisateur.pk)


def jeton_csrf(client: Client) -> str:
    if "alpha_csrf" not in client.cookies or not client.cookies["alpha_csrf"].value:
        assert client.get(URL_CSRF).status_code == 204
    return client.cookies["alpha_csrf"].value


def poster(client: Client, url: str, donnees: dict | None = None, **extra):
    return client.post(
        url,
        donnees or {},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=jeton_csrf(client),
        **extra,
    )


def se_connecter(client: Client, compte: Compte, *, code: str | None = None, **extra):
    """Flux complet ; renvoie la réponse de /auth/mfa."""
    r = poster(client, URL_CONNEXION, {"email": compte.email, "mot_de_passe": MDP}, **extra)
    assert r.status_code == 200, r.content
    assert r.json()["etape"] == "MFA_REQUIS"
    r = poster(client, URL_MFA, {"code": code or compte.totp()}, **extra)
    assert r.status_code == 200, r.content
    return r


def evenements(etablissement_id=None, action: str | None = None) -> list[EvenementAudit]:
    """Événements d'une chaîne (établissement, ou plateforme si None), dans l'ordre."""
    if etablissement_id is None:
        cm = contexte_tenant(None, scope=contexte.SCOPE_PLATFORM)
    else:
        cm = contexte_tenant(etablissement_id)
    with cm:
        qs = EvenementAudit.objects.filter(etablissement_id=etablissement_id).order_by("seq")
        if action:
            qs = qs.filter(action=action)
        return list(qs)

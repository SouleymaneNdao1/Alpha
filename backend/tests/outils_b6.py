"""Outils des tests B6 (activation, réenrôlement, mot de passe oublié, téléphone perdu)."""

from __future__ import annotations

import datetime
import re

import pyotp
from django.core import mail
from django.utils import timezone

API_AUTH = "/api/v1/auth"
API_ADMIN = "/api/v1/admin"


def messages_pour(adresse: str, sujet: str | None = None) -> list:
    return [
        m
        for m in mail.outbox
        if adresse in m.to and (sujet is None or sujet.lower() in m.subject.lower())
    ]


def lien_de(message, chemin: str) -> str:
    """Jeton en clair extrait du lien ``…/<chemin>…`` d'un e-mail (texte)."""
    trouve = re.search(re.escape(chemin) + r"([A-Za-z0-9_\-]+)", message.body)
    assert trouve, message.body
    return trouve.group(1)


def secret_de(reponse) -> str:
    return reponse.json()["secret_affichable"].replace(" ", "")


def code_precedent(secret: str) -> str:
    """Code du pas précédent (accepté par la fenêtre ±1) : le pas courant reste libre."""
    return pyotp.TOTP(secret).at(timezone.now() - datetime.timedelta(seconds=30))


def code_courant(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def code_faux(secret: str) -> str:
    valides = {
        pyotp.TOTP(secret).at(timezone.now() + datetime.timedelta(seconds=30 * d))
        for d in (-1, 0, 1)
    }
    for candidat in ("000000", "111111", "222222", "333333"):
        if candidat not in valides:
            return candidat
    raise AssertionError("aucun code faux disponible")

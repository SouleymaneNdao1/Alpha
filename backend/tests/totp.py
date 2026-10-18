"""Utilitaire TOTP des tests (tâche T1 ; utilisé par B5, B6 et T4).

Paramètres de l'application (§ 4.2, étape 8) : ``pyotp.TOTP(secret)`` par défaut,
soit 6 chiffres, pas de 30 s, SHA-1, fenêtre de vérification ±1 pas, anti-rejeu par
``dernier_pas``. Pour tester le rejeu, on a donc besoin du code COURANT et du code
SUIVANT (accepté grâce à la fenêtre, puis compteur plus grand).

    secret = nouveau_secret()
    code = code_courant(secret)
    suivant = code_suivant(secret)
    with freeze_time(...):  # les fonctions suivent l'horloge (freezegun compris)
        ...
"""

from __future__ import annotations

import datetime

import pyotp

PAS_SECONDES = 30


def nouveau_secret() -> str:
    """Secret base32 aléatoire, comme celui qu'enrôle l'Authenticator."""
    return pyotp.random_base32()


def compteur(a: datetime.datetime | None = None) -> int:
    """Numéro du pas TOTP à l'instant ``a`` (maintenant par défaut) : valeur de ``dernier_pas``."""
    instant = a or datetime.datetime.now(tz=datetime.UTC)
    return int(instant.timestamp()) // PAS_SECONDES


def code_totp(secret: str, decalage: int = 0, a: datetime.datetime | None = None) -> str:
    """Code du pas ``compteur(a) + decalage`` (-1 : précédent, 0 : courant, +1 : suivant)."""
    return pyotp.TOTP(secret, interval=PAS_SECONDES).at((compteur(a) + decalage) * PAS_SECONDES)


def code_courant(secret: str, a: datetime.datetime | None = None) -> str:
    return code_totp(secret, 0, a)


def code_suivant(secret: str, a: datetime.datetime | None = None) -> str:
    return code_totp(secret, 1, a)


def code_precedent(secret: str, a: datetime.datetime | None = None) -> str:
    return code_totp(secret, -1, a)


def code_invalide(secret: str, a: datetime.datetime | None = None) -> str:
    """Code à 6 chiffres refusé par la fenêtre ±1 (différent des trois codes acceptables)."""
    acceptes = {code_totp(secret, d, a) for d in (-1, 0, 1)}
    for candidat in range(1_000_000):
        code = f"{candidat:06d}"
        if code not in acceptes:
            return code
    raise AssertionError("inatteignable")

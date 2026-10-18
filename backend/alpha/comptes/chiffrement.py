"""Chiffrement au repos des secrets TOTP (architecture § 4.9).

``MultiFernet`` sur ``ALPHA_CLES_CHIFFREMENT`` (liste de clés Fernet base64) :
la PREMIÈRE clé chiffre, toutes déchiffrent. Rotation : ajouter la nouvelle clé
en tête de la liste, incrémenter ``ALPHA_CLES_CHIFFREMENT_VERSION``, puis lancer
``manage.py rechiffrer_secrets`` ; l'ancienne clé peut ensuite être retirée.

Les clés ne sont jamais en base ni dans l'image (variables d'environnement ou
fichier secret Docker). Aucune fonction de ce module ne journalise de valeur.
"""

from __future__ import annotations

import functools

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@functools.cache
def _multifernet(cles: tuple[str, ...]) -> MultiFernet:
    if not cles:
        raise ImproperlyConfigured("ALPHA_CLES_CHIFFREMENT est vide.")
    try:
        return MultiFernet([Fernet(cle.strip().encode("ascii")) for cle in cles])
    except (ValueError, TypeError) as exc:
        # Message volontairement sans la valeur de la clé.
        raise ImproperlyConfigured(
            "ALPHA_CLES_CHIFFREMENT contient une clé Fernet invalide."
        ) from exc


def _chiffreur() -> MultiFernet:
    return _multifernet(tuple(c for c in settings.ALPHA_CLES_CHIFFREMENT if c.strip()))


def version_courante() -> int:
    """Version de la clé de chiffrement courante (``authenticator_totp.cle_version``)."""
    return int(getattr(settings, "ALPHA_CLES_CHIFFREMENT_VERSION", 1))


def chiffrer(texte: str) -> bytes:
    """Jeton MultiFernet (octets) du texte, chiffré avec la première clé."""
    return _chiffreur().encrypt(texte.encode("utf-8"))


def dechiffrer(jeton: bytes | memoryview) -> str:
    """Texte clair d'un jeton produit par ``chiffrer`` (n'importe quelle clé de la liste)."""
    return _chiffreur().decrypt(bytes(jeton)).decode("utf-8")


def rechiffrer(jeton: bytes | memoryview) -> bytes:
    """Rechiffre un jeton avec la première clé (rotation)."""
    return _chiffreur().rotate(bytes(jeton))

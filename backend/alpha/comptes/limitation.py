"""Limitation de débit par compteurs Redis à fenêtre fixe (architecture § 4.2, § 4.5, § 4.7).

    retry = consommer("connexion:ip", ip, limite=10, fenetre_s=60)
    if retry is not None: return reponse_trop_de_requetes(retry)

Les identifiants sensibles (e-mail, clé de session) ne figurent jamais en clair
dans les clés Redis : ils sont remplacés par leur HMAC-SHA256 poivré
(``ALPHA_HMAC_POIVRE``).
"""

from __future__ import annotations

import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response

from alpha.core.erreurs import TROP_DE_REQUETES, reponse_erreur

PREFIXE = "limite"

# Limites du § 4.2.
CONNEXION_PAR_IP = (10, 60)  # 10 / min par IP
CONNEXION_PAR_EMAIL = (20, 3600)  # 20 / h par e-mail
MFA_PAR_SESSION = (5, 60)  # 5 / min par session
STEP_UP_PAR_UTILISATEUR = (5, 60)  # 5 / min par utilisateur (choix B5)


def empreinte(valeur: str) -> str:
    """HMAC-SHA256 poivré (hexadécimal) d'un identifiant, pour les clés Redis."""
    poivre = settings.ALPHA_HMAC_POIVRE.encode("utf-8")
    return hmac.new(poivre, valeur.encode("utf-8"), hashlib.sha256).hexdigest()


def consommer(espace: str, identifiant: str, *, limite: int, fenetre_s: int) -> int | None:
    """Compte une tentative ; renvoie ``None`` si autorisée, sinon le délai d'attente (s)."""
    cle = f"{PREFIXE}:{espace}:{empreinte(identifiant)}"
    cache.add(cle, 0, timeout=fenetre_s)
    try:
        nombre = cache.incr(cle)
    except ValueError:  # clé expirée entre add() et incr()
        cache.set(cle, 1, timeout=fenetre_s)
        nombre = 1
    if nombre <= limite:
        return None
    restant = cache.ttl(cle) if hasattr(cache, "ttl") else None
    return int(restant) if restant and restant > 0 else fenetre_s


def reponse_trop_de_requetes(attente_s: int) -> Response:
    """429 ``TROP_DE_REQUETES`` avec l'en-tête ``Retry-After``."""
    return reponse_erreur(
        TROP_DE_REQUETES,
        statut=status.HTTP_429_TOO_MANY_REQUESTS,
        details={"reessayer_dans_s": attente_s},
        entetes={"Retry-After": str(attente_s)},
    )

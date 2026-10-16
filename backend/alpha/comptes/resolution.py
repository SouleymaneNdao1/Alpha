"""Appels aux fonctions SECURITY DEFINER de résolution (architecture § 3.5, § 4.2, § 4.3).

Ces fonctions sont les seuls passages contrôlés à travers les établissements :
elles ne renvoient que des identifiants. Après résolution, l'appelant pose
``contexte_tenant(etablissement_id)`` (ou la portée « platform » pour un
super-admin) puis relit l'utilisateur ou le jeton par le chemin normal
(manager + RLS).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import NamedTuple

from django.db import DEFAULT_DB_ALIAS, connections


class ResolutionConnexion(NamedTuple):
    utilisateur_id: uuid.UUID
    etablissement_id: uuid.UUID | None
    est_super_admin: bool


class ResolutionJeton(NamedTuple):
    jeton_id: uuid.UUID
    etablissement_id: uuid.UUID | None
    utilisateur_id: uuid.UUID
    objet: str


def empreinte_jeton(jeton_clair: str) -> str:
    """SHA-256 hexadécimal du jeton en clair (seule forme stockée en base)."""
    return hashlib.sha256(jeton_clair.encode("utf-8")).hexdigest()


def resoudre_connexion(email: str, *, using: str = DEFAULT_DB_ALIAS) -> ResolutionConnexion | None:
    """Compte correspondant à l'e-mail (insensible à la casse), ou ``None``."""
    with connections[using].cursor() as curseur:
        curseur.execute("SELECT * FROM alpha_resoudre_connexion(%s)", [email.strip()])
        ligne = curseur.fetchone()
    return ResolutionConnexion(*ligne) if ligne else None


def resoudre_jeton(jeton_clair: str, *, using: str = DEFAULT_DB_ALIAS) -> ResolutionJeton | None:
    """Jeton valide (ni utilisé, ni annulé, ni expiré) correspondant au jeton clair, ou ``None``."""
    with connections[using].cursor() as curseur:
        curseur.execute("SELECT * FROM alpha_resoudre_jeton(%s)", [empreinte_jeton(jeton_clair)])
        ligne = curseur.fetchone()
    return ResolutionJeton(*ligne) if ligne else None

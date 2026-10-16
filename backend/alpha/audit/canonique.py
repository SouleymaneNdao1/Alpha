"""Format canonique et calcul de la chaîne d'empreintes (architecture § 6.2).

Partagé par l'écriture (``services.journaliser``) et par la vérification
(``verification``) : le payload est reconstruit À L'IDENTIQUE depuis les
colonnes, ce qui détecte la modification d'une colonne.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import uuid
from typing import Any

VERSION_FORMAT = 1
UUID_PLATEFORME = uuid.UUID(int=0)

# Champs du payload, dans l'ordre du § 6.2 (l'ordre réel est imposé par sort_keys).
CHAMPS_PAYLOAD = (
    "etablissement_id",
    "horodatage",
    "acteur_type",
    "acteur_id",
    "acteur_libelle",
    "categorie",
    "action",
    "objet_type",
    "objet_id",
    "objet_libelle",
    "avant",
    "apres",
    "detail",
    "ip",
    "user_agent",
    "request_id",
)


def horodatage_canonique(valeur: dt.datetime) -> str:
    """« 2026-10-10T20:31:07.123456Z » : UTC, microsecondes, suffixe Z."""
    if valeur.tzinfo is None:
        raise ValueError("Horodatage sans fuseau horaire.")
    return valeur.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _texte_ou_none(valeur: Any) -> str | None:
    return None if valeur is None or valeur == "" else str(valeur)


def ip_canonique(valeur: Any) -> str | None:
    """Forme normalisée de l'adresse (identique à ce que renvoie PostgreSQL pour ``inet``)."""
    if valeur is None or valeur == "":
        return None
    return str(ipaddress.ip_address(str(valeur).split("/")[0]))


def construire_payload(champs: dict[str, Any]) -> str:
    """JSON canonique (§ 6.2) : clés triées, séparateurs compacts, UTF-8 non échappé."""
    donnees = {
        "v": VERSION_FORMAT,
        "etablissement_id": _texte_ou_none(champs["etablissement_id"]),
        "horodatage": horodatage_canonique(champs["horodatage"]),
        "acteur_type": champs["acteur_type"],
        "acteur_id": _texte_ou_none(champs["acteur_id"]),
        "acteur_libelle": champs["acteur_libelle"],
        "categorie": champs["categorie"],
        "action": champs["action"],
        "objet_type": champs["objet_type"],
        "objet_id": champs["objet_id"],
        "objet_libelle": champs["objet_libelle"],
        "avant": champs["avant"],
        "apres": champs["apres"],
        "detail": champs["detail"],
        "ip": ip_canonique(champs["ip"]),
        "user_agent": champs["user_agent"],
        "request_id": _texte_ou_none(champs["request_id"]),
    }
    return json.dumps(donnees, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cle_chaine(etablissement_id: Any) -> uuid.UUID:
    """Clé de la chaîne : l'établissement, ou l'uuid nul pour la chaîne de la plateforme."""
    if etablissement_id is None or etablissement_id == "":
        return UUID_PLATEFORME
    return (
        etablissement_id
        if isinstance(etablissement_id, uuid.UUID)
        else uuid.UUID(str(etablissement_id))
    )


def genese(etablissement_id: Any) -> str:
    """hex(SHA-256("ALPHA-GENESIS|" + cle_chaine)) : ``hash_precedent`` de l'événement seq = 1."""
    texte = f"ALPHA-GENESIS|{cle_chaine(etablissement_id)}"
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def empreinte(hash_precedent: str, seq: int, payload_canonique: str) -> str:
    """hex(SHA-256(UTF-8(hash_precedent + "\\n" + seq + "\\n" + payload_canonique)))."""
    texte = f"{hash_precedent}\n{seq}\n{payload_canonique}"
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()

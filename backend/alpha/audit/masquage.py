"""Masquage des données sensibles dans le journal d'audit (architecture § 6.1).

Deux barrières :

1. **Liste blanche par modèle** : chaque modèle journalisé déclare
   ``AUDIT_CHAMPS`` (champs autorisés dans ``avant``/``apres``).
   ``extraire_champs(instance)`` ne lit QUE ces champs ; un modèle sans
   ``AUDIT_CHAMPS`` est refusé (échec fermé).
2. **Liste noire de secours** : toute clé dont le nom évoque un secret (mot de
   passe, secret TOTP, code de secours, OTP, jeton, hachage, clé, poivre) est
   remplacée par ``MASQUE``, à tous les niveaux d'imbrication, même si un
   appelant la passe directement dans ``avant``/``apres``.

Les valeurs sont ensuite normalisées en JSON simple (``normaliser_json``) :
``DjangoJSONEncoder`` puis ``json.loads`` ; les ``Decimal`` deviennent des
chaînes ; les flottants sont interdits (ValueError), car leur représentation
n'est pas stable d'un langage à l'autre et casserait la vérification.
"""

from __future__ import annotations

import json
import re
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder

MASQUE = "[masqué]"

# Segment (séparé par « _ ») évoquant un secret. « mdp » seul ou en fin de nom
# (« nouveau_mdp ») est masqué, mais pas les réglages « mdp_longueur_min »,
# « mdp_historique » ni « mdp_expiration_jours ».
_CLE_SENSIBLE = re.compile(
    r"(^|_)(password|passwd|mot_de_passe|secret|secrets|totp|otp|code_secours|codes_secours|"
    r"codes|jeton|jetons|token|tokens|hash|hachage|cle|cles|poivre|pepper|api_key)($|_)"
    r"|(^|_)mdp$",
    re.IGNORECASE,
)


def cle_sensible(cle: str) -> bool:
    """Vrai si le nom de champ évoque un secret (jamais journalisé en clair)."""
    return bool(_CLE_SENSIBLE.search(cle))


def masquer(valeur: Any) -> Any:
    """Remplace récursivement la valeur des clés sensibles par ``MASQUE``."""
    if isinstance(valeur, dict):
        return {
            cle: (MASQUE if cle_sensible(str(cle)) else masquer(sous_valeur))
            for cle, sous_valeur in valeur.items()
        }
    if isinstance(valeur, list | tuple):
        return [masquer(element) for element in valeur]
    return valeur


def _refuser_flottant(texte: str) -> Any:
    raise ValueError(
        f"Valeur flottante interdite dans le journal d'audit ({texte}) : "
        "utiliser Decimal (journalisé en chaîne) ou un entier."
    )


def normaliser_json(valeur: Any) -> Any:
    """Valeur JSON simple : chaînes, entiers, booléens, null, listes et objets (§ 6.1)."""
    if valeur is None:
        return None
    texte = json.dumps(valeur, cls=DjangoJSONEncoder, ensure_ascii=False)
    return json.loads(texte, parse_float=_refuser_flottant)


def champs_audit(modele: type) -> tuple[str, ...]:
    """Liste blanche ``AUDIT_CHAMPS`` du modèle ; erreur si elle n'est pas déclarée."""
    champs = getattr(modele, "AUDIT_CHAMPS", None)
    if champs is None:
        raise ImproperlyConfigured(
            f"{modele.__name__} doit déclarer AUDIT_CHAMPS (liste blanche des champs journalisés)."
        )
    return tuple(champs)


def extraire_champs(instance: Any, champs: list[str] | tuple[str, ...] | None = None) -> dict:
    """Instantané des champs autorisés d'une instance, prêt pour ``avant``/``apres``.

    ``champs`` restreint encore la liste blanche (ex. les seuls champs modifiés) ;
    un champ hors liste blanche est refusé (ValueError).
    """
    autorises = champs_audit(type(instance))
    if champs is not None:
        interdits = sorted(set(champs) - set(autorises))
        if interdits:
            raise ValueError(f"Champs hors AUDIT_CHAMPS : {', '.join(interdits)}.")
        autorises = tuple(c for c in autorises if c in champs)
    resultat = {}
    for nom in autorises:
        if cle_sensible(nom):
            resultat[nom] = MASQUE
            continue
        try:
            champ = instance._meta.get_field(nom)
            attribut = champ.attname
        except Exception:  # propriété ou attribut calculé déclaré dans AUDIT_CHAMPS
            attribut = nom
        resultat[nom] = getattr(instance, attribut)
    return resultat


def preparer(valeur: Any) -> Any:
    """Masquage puis normalisation JSON (ordre important : masquer avant de sérialiser)."""
    if valeur is None:
        return None
    return normaliser_json(masquer(valeur))

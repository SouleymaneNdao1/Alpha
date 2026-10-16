"""Écriture dans le journal d'audit : point d'entrée unique ``journaliser()`` (architecture § 6.1).

    from alpha.audit.services import journaliser
    from alpha.audit.models import Categorie

    journaliser("role.modifie", Categorie.PARAMETRAGE, objet=role,
                avant=extraire_champs(ancien), apres=extraire_champs(role))

- Acteur, IP, user agent et ``request_id`` sont lus dans ``alpha.core.contexte`` ;
  hors requête (tâche Celery, commande), l'acteur est « Système » et ces champs
  sont vides.
- ``etablissement_id`` vaut par défaut le tenant courant, sinon NULL (chaîne de
  la plateforme). Passer explicitement ``etablissement_id=None`` écrit dans la
  chaîne de la plateforme même sous un contexte tenant.
- ``seq``, ``hash_precedent`` et ``hash`` sont calculés par le trigger
  ``audit_chainer`` ; l'application ne fournit que ``payload_canonique``.
- Par défaut, l'événement est écrit DANS la transaction de l'action : l'action
  et sa trace sont validées ou annulées ensemble (§ 6.1).
- ``hors_transaction=True`` écrit par une connexion séparée (alias
  ``ALPHA_AUDIT_ALIAS_INDEPENDANT``, rôle applicatif, même RLS), validée
  immédiatement : l'événement survit à l'annulation de la transaction
  appelante. Réservé aux événements qui doivent survivre à un échec (ex.
  ``auth.connexion.echec`` quand la vue ne peut pas simplement RETOURNER une
  réponse 401/423, cf. § 3.3). Précaution : ne pas l'utiliser pour une chaîne
  dans laquelle la transaction appelante a DÉJÀ écrit (elle détient le verrou de
  la chaîne) ; un ``lock_timeout`` de 5 s transforme ce cas en erreur au lieu
  d'un blocage.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from alpha.core import contexte
from alpha.tenancy.contexte import appliquer_contexte
from alpha.tenancy.exceptions import ViolationTenant

from . import canonique, masquage
from .models import Categorie, EvenementAudit, TypeActeur

journal = logging.getLogger("alpha.audit")

# Valeur sentinelle : « l'établissement courant » (défaut de ``etablissement_id``).
COURANT: Any = object()

_LONGUEURS = {
    "acteur_libelle": 150,
    "action": 60,
    "objet_type": 60,
    "objet_id": 64,
    "objet_libelle": 200,
    "user_agent": 300,
}

_ESPACE_REQUEST_ID = uuid.UUID("6f1c2d3e-4b5a-4c6d-8e7f-a1b2c3d4e5f6")
LOCK_TIMEOUT_HORS_TRANSACTION = "5s"


@dataclass(frozen=True)
class Acteur:
    """Auteur d'un événement : type, identifiant (sans clé étrangère) et libellé figé."""

    type: str
    id: uuid.UUID | None = None
    libelle: str = ""


ACTEUR_SYSTEME = Acteur(TypeActeur.SYSTEME, None, "Système ALPHA")
ACTEUR_ANONYME = Acteur(TypeActeur.ANONYME, None, "inconnu")


# --- Normalisation des champs ---------------------------------------------------------------


def _texte(valeur: Any, champ: str | None = None) -> str:
    """Chaîne sans caractère NUL (refusé par PostgreSQL), tronquée à la longueur de la colonne."""
    texte = "" if valeur is None else str(valeur).replace("\x00", "")
    if champ in _LONGUEURS:
        texte = texte[: _LONGUEURS[champ]]
    return texte


def _uuid(valeur: Any) -> uuid.UUID | None:
    if valeur is None or valeur == "":
        return None
    return valeur if isinstance(valeur, uuid.UUID) else uuid.UUID(str(valeur))


def _request_id(valeur: str | None) -> uuid.UUID | None:
    """``request_id`` du contexte en uuid (colonne ``uuid``, § 2.2).

    Le middleware produit un uuid hexadécimal ; un X-Request-ID entrant qui n'est
    pas un uuid (ex. « caddy-1234abcd ») est converti en uuid5 déterministe, pour
    que tous les événements d'une même requête restent corrélés.
    """
    if not valeur:
        return None
    try:
        return uuid.UUID(valeur)
    except ValueError:
        return uuid.uuid5(_ESPACE_REQUEST_ID, valeur)


def _resolveur_acteur():
    chemin = getattr(settings, "ALPHA_AUDIT_RESOLVEUR_ACTEUR", None)
    return import_string(chemin) if chemin else None


def resoudre_acteur(acteur: Any = None) -> Acteur:
    """Acteur explicite (``Acteur`` ou objet utilisateur), sinon déduit du contexte.

    - objet utilisateur (B3) : ``pk``, ``est_super_admin``, ``get_full_name()`` ;
    - utilisateur du contexte : libellé fourni par ``ALPHA_AUDIT_RESOLVEUR_ACTEUR``
      (chemin pointé vers une fonction ``uuid -> Acteur | None``, à brancher par
      B3), sinon libellé provisoire « utilisateur <8 premiers caractères> » ;
    - requête sans utilisateur : ANONYME « inconnu » ; hors requête : SYSTEME.
    """
    if isinstance(acteur, Acteur):
        if acteur.type not in TypeActeur.values:
            raise ValueError(f"Type d'acteur inconnu : {acteur.type!r}.")
        return Acteur(acteur.type, _uuid(acteur.id), _texte(acteur.libelle, "acteur_libelle"))
    if acteur is not None:
        type_acteur = (
            TypeActeur.SUPER_ADMIN
            if getattr(acteur, "est_super_admin", False)
            else TypeActeur.UTILISATEUR
        )
        nom_complet = getattr(acteur, "get_full_name", None)
        libelle = (nom_complet() if callable(nom_complet) else "") or str(acteur)
        return Acteur(type_acteur, _uuid(acteur.pk), _texte(libelle, "acteur_libelle"))

    utilisateur = contexte.utilisateur_courant()
    if utilisateur is not None:
        resolveur = _resolveur_acteur()
        trouve = resolveur(utilisateur) if resolveur else None
        if trouve is not None:
            return resoudre_acteur(trouve)
        type_acteur = (
            TypeActeur.SUPER_ADMIN
            if contexte.scope_courant() == contexte.SCOPE_PLATFORM
            else TypeActeur.UTILISATEUR
        )
        return Acteur(type_acteur, utilisateur, f"utilisateur {str(utilisateur)[:8]}")
    if contexte.request_id() is not None:
        return ACTEUR_ANONYME
    return ACTEUR_SYSTEME


def _objet(objet: Any) -> tuple[str, str, str]:
    """(objet_type, objet_id, libellé par défaut) d'une instance de modèle ou d'un couple."""
    if objet is None:
        return "", "", ""
    if isinstance(objet, tuple):
        objet_type, objet_id = objet
        return str(objet_type), "" if objet_id is None else str(objet_id), ""
    meta = objet._meta
    return f"{meta.app_label}.{meta.model_name}", str(objet.pk), str(objet)


def _etablissement(etablissement_id: Any) -> uuid.UUID | None:
    tenant = contexte.tenant_courant()
    if etablissement_id is COURANT:
        return tenant
    cible = _uuid(etablissement_id)
    if cible is not None and cible != tenant:
        # La RLS le refuserait aussi ; message explicite côté application.
        raise ViolationTenant()
    return cible


# --- Écriture ---------------------------------------------------------------------------------

_COLONNES = (
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
    "payload_canonique",
)
_CASTS = {"avant": "::jsonb", "apres": "::jsonb", "ip": "::inet", "request_id": "::uuid"}
# Requête construite à partir de noms de colonnes constants (aucune donnée externe) ;
# toutes les valeurs passent en paramètres.
_SQL_INSERTION = (
    "INSERT INTO evenement_audit ("  # noqa: S608
    + ", ".join(_COLONNES)
    + ") VALUES ("
    + ", ".join(f"%s{_CASTS.get(c, '')}" for c in _COLONNES)
    + ")"
)
_SQL_RETOUR = " RETURNING id, seq, hash_precedent, hash"


def _ligne_visible(etablissement_id: uuid.UUID | None) -> bool:
    """La ligne insérée passe-t-elle la politique de LECTURE (condition d'un RETURNING) ?

    Sous RLS, ``INSERT … RETURNING`` exige que la nouvelle ligne soit lisible ; un
    échec anonyme écrit dans la chaîne plateforme ne l'est pas : on insère alors
    sans RETURNING (``seq`` et ``hash`` restent inconnus de l'appelant).
    """
    if etablissement_id is not None:
        return etablissement_id == contexte.tenant_courant()
    return contexte.scope_courant() == contexte.SCOPE_PLATFORM


def _inserer(champs: dict[str, Any], using: str) -> EvenementAudit:
    valeurs = []
    for colonne in _COLONNES:
        valeur = champs[colonne]
        if colonne in ("avant", "apres"):
            valeur = None if valeur is None else json.dumps(valeur, ensure_ascii=False)
        elif colonne in ("etablissement_id", "acteur_id", "request_id"):
            valeur = None if valeur is None else str(valeur)
        valeurs.append(valeur)

    retour = _ligne_visible(champs["etablissement_id"])
    evenement = EvenementAudit(**{c: champs[c] for c in _COLONNES})
    with connections[using].cursor() as curseur:
        curseur.execute(_SQL_INSERTION + (_SQL_RETOUR if retour else ""), valeurs)
        if retour:
            (evenement.id, evenement.seq, evenement.hash_precedent, evenement.hash) = (
                curseur.fetchone()
            )
    evenement._state.adding = False
    evenement._state.db = using
    return evenement


def journaliser(
    action: str,
    categorie: str,
    *,
    objet: Any = None,
    objet_libelle: str | None = None,
    avant: Any = None,
    apres: Any = None,
    detail: str = "",
    acteur: Any = None,
    etablissement_id: Any = COURANT,
    hors_transaction: bool = False,
    using: str = DEFAULT_DB_ALIAS,
) -> EvenementAudit:
    """Ajoute un événement à la chaîne d'audit (§ 6.1, § 6.2) et le renvoie.

    ``avant``/``apres`` : valeurs JSON simples ; masquées (clés sensibles) puis
    normalisées (``Decimal`` → chaîne ; flottant → ValueError). Pour un modèle,
    utiliser ``masquage.extraire_champs(instance)`` (liste blanche ``AUDIT_CHAMPS``).

    Les ``id``, ``seq`` et ``hash`` de l'événement renvoyé ne sont renseignés
    que si la ligne est lisible sous le contexte courant (voir ``_ligne_visible``).
    """
    if not action or len(action) > _LONGUEURS["action"]:
        raise ValueError(f"Code d'action invalide : {action!r}.")
    if categorie not in Categorie.values:
        raise ValueError(f"Catégorie d'audit inconnue : {categorie!r}.")

    qui = resoudre_acteur(acteur)
    objet_type, objet_id, libelle_defaut = _objet(objet)
    champs: dict[str, Any] = {
        "etablissement_id": _etablissement(etablissement_id),
        "horodatage": timezone.now(),
        "acteur_type": str(qui.type),
        "acteur_id": qui.id,
        "acteur_libelle": qui.libelle,
        "categorie": str(categorie),
        "action": action,
        "objet_type": _texte(objet_type, "objet_type"),
        "objet_id": _texte(objet_id, "objet_id"),
        "objet_libelle": _texte(
            objet_libelle if objet_libelle is not None else libelle_defaut, "objet_libelle"
        ),
        "avant": masquage.preparer(avant),
        "apres": masquage.preparer(apres),
        "detail": _texte(detail),
        "ip": canonique.ip_canonique(contexte.ip()),
        "user_agent": _texte(contexte.user_agent(), "user_agent"),
        "request_id": _request_id(contexte.request_id()),
    }
    champs["payload_canonique"] = canonique.construire_payload(champs)

    if not hors_transaction:
        return _inserer(champs, using)
    return _inserer_hors_transaction(champs)


def _inserer_hors_transaction(champs: dict[str, Any]) -> EvenementAudit:
    """Écrit par la connexion indépendante, dans sa propre transaction, validée aussitôt."""
    alias = getattr(settings, "ALPHA_AUDIT_ALIAS_INDEPENDANT", "audit")
    if alias not in settings.DATABASES:
        raise ImproperlyConfigured(
            f"Connexion « {alias} » absente de DATABASES (journalisation hors transaction)."
        )
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as curseur:
            curseur.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_HORS_TRANSACTION}'")
        with appliquer_contexte(
            contexte.tenant_courant(),
            contexte.scope_courant(),
            contexte.utilisateur_courant(),
            using=alias,
        ):
            return _inserer(champs, alias)

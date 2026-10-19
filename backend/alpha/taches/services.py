"""Seul point d'écriture de la boîte « À traiter » (architecture § 2.2, § 2.5, tâche B8).

Les modules (absences au S1, moteur de workflow au S2) n'écrivent JAMAIS dans
``Tache`` directement ; ils appellent :

    ouvrir(source, *, module, action, titre, assigne_utilisateur=…, assigne_role=…, …) -> Tache
    terminer(source, action, *, par, resultat="") -> Tache | None
    annuler(source, action=None) -> list[Tache]
    reassigner(tache, *, assigne_utilisateur=…, assigne_role=…, assigne_unite=…) -> Tache
    tache_ouverte(source, action) -> Tache | None

``source`` est une instance de modèle (``app_label.model_name`` + ``pk``) ou un
couple ``("workflow.instance_etape", uuid)``. Les destinataires acceptent une
instance ou un identifiant.

Garanties :
- idempotence : une seule tâche OUVERTE par (source, action) ; ``ouvrir`` renvoie
  la tâche existante (sans nouvel audit), ``terminer``/``annuler`` sans tâche
  ouverte ne font rien ;
- chaque écriture effective est journalisée (``tache.ouverte``, ``tache.terminee``,
  ``tache.annulee``, ``tache.reassignee``, catégorie MODIFICATION) dans la
  transaction de l'appelant, et émet un signal (``alpha.taches.signaux``) auquel
  les notifications (B9) se raccordent ;
- ``terminer`` renseigne ``pour_compte_de`` quand ``par`` agit par délégation.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from alpha.audit.masquage import extraire_champs
from alpha.audit.models import Categorie
from alpha.audit.services import journaliser

from . import signaux
from .models import Action, Module, StatutTache, Tache, TypeEcheance

#: Valeur sentinelle de ``reassigner`` : « ne pas changer ce destinataire ».
INCHANGE: Any = object()
#: Valeur sentinelle de ``terminer`` : ``pour_compte_de`` déduit des délégations.
AUTO: Any = object()


def cle_source(source: Any) -> tuple[str, uuid.UUID]:
    """(source_type, source_id) d'une instance de modèle ou d'un couple explicite."""
    if isinstance(source, tuple):
        source_type, source_id = source
    else:
        meta = source._meta
        source_type, source_id = f"{meta.app_label}.{meta.model_name}", source.pk
    if not source_type or len(source_type) > 60:
        raise ValueError(f"Type de source invalide : {source_type!r}.")
    if source_id is None:
        raise ValueError("La source n'a pas d'identifiant (objet non enregistré ?).")
    return str(source_type), source_id if isinstance(source_id, uuid.UUID) else uuid.UUID(
        str(source_id)
    )


def _pk(valeur: Any) -> Any:
    return getattr(valeur, "pk", valeur)


def _ouvertes(source_type: str, source_id: uuid.UUID):
    return Tache.objects.filter(
        source_type=source_type, source_id=source_id, statut=StatutTache.OUVERTE
    )


def tache_ouverte(source: Any, action: str) -> Tache | None:
    """Tâche ouverte de ``source`` pour ``action``, ou ``None``."""
    source_type, source_id = cle_source(source)
    return _ouvertes(source_type, source_id).filter(action=action).first()


def _journaliser(action_audit: str, tache: Tache, *, avant=None, acteur=None, detail=""):
    journaliser(
        action_audit,
        Categorie.MODIFICATION,
        objet=tache,
        objet_libelle=str(tache)[:200],
        avant=avant,
        apres=extraire_champs(tache),
        acteur=acteur,
        detail=detail,
    )


def ouvrir(
    source: Any,
    *,
    module: str,
    action: str,
    titre: str,
    assigne_utilisateur: Any = None,
    assigne_role: Any = None,
    assigne_unite: Any = None,
    echeance: datetime.datetime | None = None,
    type_echeance: str = TypeEcheance.AVANT,
    reference: str = "",
    sous_titre: str = "",
    montant: Decimal | None = None,
    devise: str = "XOF",
    demandeur: Any = None,
    lien: str = "",
    acteur: Any = None,
) -> Tache:
    """Ouvre la tâche (source, action) ; si elle est déjà ouverte, la renvoie telle quelle."""
    if module not in Module.values:
        raise ValueError(f"Module inconnu : {module!r}.")
    if action not in Action.values:
        raise ValueError(f"Action inconnue : {action!r}.")
    if assigne_utilisateur is None and assigne_role is None:
        raise ValueError("Une tâche doit être assignée à un utilisateur ou à un rôle.")
    if assigne_unite is not None and assigne_role is None:
        raise ValueError("Une unité ne s'utilise qu'avec un rôle destinataire.")
    if echeance is not None and timezone.is_naive(echeance):
        raise ValueError("L'échéance doit être un datetime avec fuseau horaire.")
    source_type, source_id = cle_source(source)

    existante = _ouvertes(source_type, source_id).filter(action=action).first()
    if existante is not None:
        return existante
    tache = Tache(
        module=module,
        source_type=source_type,
        source_id=source_id,
        action=action,
        titre=titre[:200],
        sous_titre=sous_titre[:300],
        reference=reference[:40],
        montant=montant,
        devise=devise,
        type_echeance=type_echeance,
        echeance=echeance,
        assigne_utilisateur_id=_pk(assigne_utilisateur),
        assigne_role_id=_pk(assigne_role),
        assigne_unite_id=_pk(assigne_unite),
        demandeur_id=_pk(demandeur),
        lien=lien[:300],
    )
    try:
        with transaction.atomic():
            tache.save()
    except IntegrityError:
        # Ouverture concurrente de la même tâche : l'index unique partiel a tranché.
        existante = _ouvertes(source_type, source_id).filter(action=action).first()
        if existante is None:
            raise
        return existante
    _journaliser("tache.ouverte", tache, acteur=acteur)
    signaux.tache_ouverte.send(sender=Tache, tache=tache)
    return tache


def _pour_compte_de(tache: Tache, par_id: uuid.UUID) -> uuid.UUID | None:
    from .visibilite import visibles_pour  # import local : visibilite dépend de delegations

    ligne = visibles_pour(par_id).filter(pk=tache.pk).values_list("par_delegation_de_id").first()
    return ligne[0] if ligne else None


def _fermer(tache: Tache, statut: str, *, par_id, resultat: str, pour_compte_de_id, acteur):
    avant = extraire_champs(tache, ["statut", "resultat"])
    tache.statut = statut
    tache.resultat = resultat[:30]
    tache.terminee_le = timezone.now()
    tache.terminee_par_id = par_id
    tache.pour_compte_de_id = pour_compte_de_id
    tache.save(
        update_fields=["statut", "resultat", "terminee_le", "terminee_par", "pour_compte_de"]
    )
    action_audit = "tache.terminee" if statut == StatutTache.TERMINEE else "tache.annulee"
    _journaliser(action_audit, tache, avant=avant, acteur=acteur)
    signaux.tache_fermee.send(sender=Tache, tache=tache)


def terminer(
    source: Any,
    action: str,
    *,
    par: Any,
    resultat: str = "",
    pour_compte_de: Any = AUTO,
    acteur: Any = None,
) -> Tache | None:
    """Termine la tâche ouverte (source, action) ; ``None`` s'il n'y en a pas (idempotent).

    ``par`` : utilisateur qui a fait l'action (ou ``None`` pour le système).
    ``pour_compte_de`` : par défaut, le délégant si ``par`` ne voyait la tâche que
    par délégation ; ``None`` pour forcer « en propre ».
    """
    source_type, source_id = cle_source(source)
    tache = _ouvertes(source_type, source_id).filter(action=action).select_for_update().first()
    if tache is None:
        return None
    par_id = _pk(par)
    if pour_compte_de is AUTO:
        compte = _pour_compte_de(tache, par_id) if par_id is not None else None
    else:
        compte = _pk(pour_compte_de)
    _fermer(
        tache,
        StatutTache.TERMINEE,
        par_id=par_id,
        resultat=resultat,
        pour_compte_de_id=compte,
        acteur=acteur if acteur is not None else par,
    )
    return tache


def annuler(
    source: Any, action: str | None = None, *, par: Any = None, acteur: Any = None
) -> list[Tache]:
    """Annule les tâches ouvertes de ``source`` (toutes actions si ``action`` est ``None``)."""
    source_type, source_id = cle_source(source)
    qs = _ouvertes(source_type, source_id)
    if action is not None:
        qs = qs.filter(action=action)
    taches = list(qs.select_for_update().order_by("cree_le", "id"))
    for tache in taches:
        _fermer(
            tache,
            StatutTache.ANNULEE,
            par_id=_pk(par),
            resultat="",
            pour_compte_de_id=None,
            acteur=acteur if acteur is not None else par,
        )
    return taches


def reassigner(
    tache: Tache,
    *,
    assigne_utilisateur: Any = INCHANGE,
    assigne_role: Any = INCHANGE,
    assigne_unite: Any = INCHANGE,
    acteur: Any = None,
) -> Tache:
    """Change le destinataire d'une tâche ouverte (ex. S2 : rôle vacant, escalade)."""
    tache = Tache.objects.select_for_update().get(pk=tache.pk)
    if tache.statut != StatutTache.OUVERTE:
        raise ValueError("Seule une tâche ouverte peut être réassignée.")
    avant = extraire_champs(tache, ["assigne_utilisateur", "assigne_role", "assigne_unite"])
    if assigne_utilisateur is not INCHANGE:
        tache.assigne_utilisateur_id = _pk(assigne_utilisateur)
    if assigne_role is not INCHANGE:
        tache.assigne_role_id = _pk(assigne_role)
    if assigne_unite is not INCHANGE:
        tache.assigne_unite_id = _pk(assigne_unite)
    if tache.assigne_utilisateur_id is None and tache.assigne_role_id is None:
        raise ValueError("Une tâche doit être assignée à un utilisateur ou à un rôle.")
    if tache.assigne_unite_id is not None and tache.assigne_role_id is None:
        raise ValueError("Une unité ne s'utilise qu'avec un rôle destinataire.")
    tache.save(update_fields=["assigne_utilisateur", "assigne_role", "assigne_unite"])
    _journaliser("tache.reassignee", tache, avant=avant, acteur=acteur)
    signaux.tache_reassignee.send(sender=Tache, tache=tache, avant=avant)
    return tache

"""Vérification d'une chaîne d'audit (architecture § 6.4).

``lancer_verification(etablissement_id, declencheur)`` ouvre le contexte de la
chaîne (établissement, ou portée « platform » pour la chaîne de la plateforme),
puis ``verifier_chaine()`` :

1. crée un ``ControleIntegriteAudit`` ``EN_COURS`` ;
2. parcourt la chaîne par ``seq`` croissant (curseur serveur, lots de 5 000),
   sous le rôle applicatif et la RLS (aucun contournement) ;
3. pour chaque événement vérifie :
   a. ``seq`` = précédent + 1 (pas de trou) ;
   b. ``hash_precedent`` = ``hash`` du précédent (ou genèse) ;
   c. payload recalculé depuis les COLONNES = ``payload_canonique`` (colonne modifiée) ;
   d. SHA-256 recalculé = ``hash`` (payload modifié) ;
4. vérifie que la dernière ancre ``INTACTE`` (``dernier_seq``, ``dernier_hash``)
   est toujours présente et identique (troncature de fin de chaîne) ;
5. termine en ``INTACTE`` (nouvelle ancre) ou ``ROMPUE`` (``premier_seq_invalide``
   + motif) ; une exception inattendue donne ``ERREUR``. En cas de rupture :
   événement ``SECURITE`` dans la chaîne et alerte par e-mail (après COMMIT).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import DEFAULT_DB_ALIAS, transaction
from django.db.models import Max
from django.utils import timezone

from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant

from . import alertes, canonique
from .models import (
    Categorie,
    ControleIntegriteAudit,
    Declencheur,
    EvenementAudit,
    StatutControle,
    TypeActeur,
)
from .services import Acteur, journaliser

journal = logging.getLogger("alpha.audit")

TAILLE_LOT = 5000
ACTION_RUPTURE = "audit.chaine_rompue"
ACTEUR_CONTROLE = Acteur(TypeActeur.SYSTEME, None, "Contrôle d'intégrité")

_COLONNES = (
    "seq",
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
    "hash_precedent",
    "hash",
)


@dataclass
class Rupture:
    seq: int
    motif: str


def _filtre_chaine(etablissement_id: uuid.UUID | None) -> dict[str, Any]:
    if etablissement_id is None:
        return {"etablissement__isnull": True}
    return {"etablissement_id": etablissement_id}


def _derniere_ancre(etablissement_id, exclure, using: str) -> ControleIntegriteAudit | None:
    return (
        ControleIntegriteAudit.objects.using(using)
        .filter(
            **_filtre_chaine(etablissement_id),
            statut=StatutControle.INTACTE,
            dernier_seq__isnull=False,
        )
        .exclude(pk=exclure)
        .order_by("-lance_le")
        .first()
    )


def _parcourir(
    etablissement_id: uuid.UUID | None, depuis_seq: int | None, using: str
) -> tuple[int, int | None, str | None, Rupture | None]:
    """Parcourt la chaîne ; renvoie (nb, dernier_seq, dernier_hash, rupture éventuelle)."""
    filtre = _filtre_chaine(etablissement_id)
    evenements = EvenementAudit.objects.using(using).filter(**filtre)

    attendu = 1
    precedent = canonique.genese(etablissement_id)
    if depuis_seq and depuis_seq > 1:
        attendu = depuis_seq
        ligne = evenements.filter(seq=depuis_seq - 1).values_list("hash", flat=True).first()
        if ligne is None:
            return 0, None, None, Rupture(depuis_seq - 1, "événement de départ introuvable")
        precedent = ligne
        evenements = evenements.filter(seq__gte=depuis_seq)

    nb = 0
    dernier_seq: int | None = None
    curseur = evenements.order_by("seq").values_list(*_COLONNES).iterator(chunk_size=TAILLE_LOT)
    for valeurs in curseur:
        ligne = dict(zip(_COLONNES, valeurs, strict=True))
        seq = ligne["seq"]
        if seq != attendu:  # a
            motif = f"événement(s) manquant(s) : seq {attendu} attendu, seq {seq} trouvé"
            return nb, dernier_seq, precedent, Rupture(min(seq, attendu), motif)
        if ligne["hash_precedent"] != precedent:  # b
            return (
                nb,
                dernier_seq,
                precedent,
                Rupture(seq, "hash_precedent différent de l'empreinte de l'événement précédent"),
            )
        if canonique.construire_payload(ligne) != ligne["payload_canonique"]:  # c
            return (
                nb,
                dernier_seq,
                precedent,
                Rupture(
                    seq, "payload canonique différent des colonnes (colonne ou payload modifié)"
                ),
            )
        if canonique.empreinte(precedent, seq, ligne["payload_canonique"]) != ligne["hash"]:  # d
            return (
                nb,
                dernier_seq,
                precedent,
                Rupture(seq, "empreinte recalculée différente (payload ou empreinte modifiés)"),
            )
        nb += 1
        dernier_seq = seq
        precedent = ligne["hash"]
        attendu = seq + 1
    return nb, dernier_seq, precedent, None


def _verifier_ancre(etablissement_id, controle, using: str) -> Rupture | None:
    """Étape 4 : la dernière ancre INTACTE est-elle toujours présente et identique ?"""
    ancre = _derniere_ancre(etablissement_id, controle.pk, using)
    if ancre is None:
        return None
    date = timezone.localtime(ancre.lance_le).strftime("%d/%m/%Y %H:%M")
    chaine = EvenementAudit.objects.using(using).filter(**_filtre_chaine(etablissement_id))
    actuel = chaine.filter(seq=ancre.dernier_seq).values_list("hash", flat=True).first()
    if actuel is None:
        dernier = chaine.aggregate(m=Max("seq"))["m"] or 0
        return Rupture(
            dernier + 1,
            f"troncature de fin de chaîne : l'ancre du {date} (seq {ancre.dernier_seq}) "
            f"est absente ; dernier événement présent : seq {dernier}",
        )
    if actuel != ancre.dernier_hash:
        return Rupture(
            ancre.dernier_seq,
            f"empreinte de l'ancre du {date} (seq {ancre.dernier_seq}) modifiée",
        )
    return None


def verifier_chaine(
    etablissement_id: uuid.UUID | None,
    declencheur: str = Declencheur.PLANIFIE,
    *,
    depuis_seq: int | None = None,
    using: str = DEFAULT_DB_ALIAS,
    controle: ControleIntegriteAudit | None = None,
) -> ControleIntegriteAudit:
    """Vérifie la chaîne SOUS LE CONTEXTE DÉJÀ OUVERT (voir ``lancer_verification``).

    ``controle`` : ligne ``EN_COURS`` déjà créée (lancement manuel par l'API, B11, qui
    renvoie son identifiant avant l'exécution) ; sinon une ligne est créée ici.
    """
    if etablissement_id != contexte.tenant_courant():
        raise ValueError("Le contexte courant ne correspond pas à la chaîne à vérifier.")
    if controle is None:
        controle = ControleIntegriteAudit(
            etablissement_id=etablissement_id,
            lance_le=timezone.now(),
            declencheur=declencheur,
            statut=StatutControle.EN_COURS,
        )
        controle.save(using=using)
    try:
        with transaction.atomic(using=using):
            nb, dernier_seq, dernier_hash, rupture = _parcourir(etablissement_id, depuis_seq, using)
            if rupture is None:
                rupture = _verifier_ancre(etablissement_id, controle, using)
    except Exception as erreur:
        journal.exception("Vérification de la chaîne d'audit %s en erreur.", etablissement_id)
        controle.statut = StatutControle.ERREUR
        controle.message = f"Erreur technique : {type(erreur).__name__}"
        controle.termine_le = timezone.now()
        controle.save(using=using)
        return controle

    controle.nb_evenements = nb
    controle.dernier_seq = dernier_seq
    controle.dernier_hash = dernier_hash if dernier_seq is not None else None
    controle.termine_le = timezone.now()
    if rupture is None:
        controle.statut = StatutControle.INTACTE
        controle.message = "Chaîne d'empreintes intacte."
        controle.save(using=using)
        return controle

    controle.statut = StatutControle.ROMPUE
    controle.premier_seq_invalide = rupture.seq
    controle.message = f"Chaîne rompue au seq {rupture.seq} : {rupture.motif}."
    controle.save(using=using)
    journal.error(
        "Chaîne d'audit ROMPUE (établissement %s) : %s", etablissement_id, controle.message
    )
    journaliser(
        ACTION_RUPTURE,
        Categorie.SECURITE,
        objet=controle,
        objet_libelle=f"Contrôle du {timezone.localtime(controle.lance_le):%d/%m/%Y %H:%M}",
        detail=controle.message,
        acteur=ACTEUR_CONTROLE,
        using=using,
    )
    alertes.programmer_alerte_rupture(controle)
    return controle


def lancer_verification(
    etablissement_id: Any,
    declencheur: str = Declencheur.PLANIFIE,
    *,
    depuis_seq: int | None = None,
    using: str = DEFAULT_DB_ALIAS,
) -> ControleIntegriteAudit:
    """Ouvre le contexte de la chaîne puis la vérifie (tâches Celery, commande, API B11).

    ``etablissement_id=None`` : chaîne de la plateforme (portée « platform »).
    """
    if etablissement_id is None:
        with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=None, using=using):
            return verifier_chaine(None, declencheur, depuis_seq=depuis_seq, using=using)
    tid = (
        etablissement_id
        if isinstance(etablissement_id, uuid.UUID)
        else uuid.UUID(str(etablissement_id))
    )
    with contexte_tenant(tid, utilisateur_id=None, using=using):
        return verifier_chaine(tid, declencheur, depuis_seq=depuis_seq, using=using)

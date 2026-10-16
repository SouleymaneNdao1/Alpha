"""Ancrage quotidien du journal d'audit hors de la base (architecture § 6.5, décision P7).

Pour chaque chaîne, ``ancrer()`` (sous le contexte de la chaîne) :
1. reprend le contrôle d'intégrité de la nuit (tâche de 02:00) s'il est
   ``INTACTE`` et récent ; sinon lance une vérification maintenant, ce qui
   enregistre un nouveau ``ControleIntegriteAudit`` ;
2. si la chaîne est intacte, prépare l'e-mail d'ancre (dernier ``seq``/``hash``)
   pour le contrôle interne de l'établissement et l'adresse sécurité FYXOP ;
   une chaîne rompue n'est pas ancrée (l'alerte de rupture est déjà partie).
"""

from __future__ import annotations

import datetime as dt
import uuid

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from alpha.core import contexte
from alpha.tenancy.contexte import contexte_tenant

from . import alertes
from .models import ControleIntegriteAudit, Declencheur, StatutControle
from .verification import verifier_chaine

# Un contrôle plus ancien n'est pas réutilisé comme ancre du jour.
FRAICHEUR_CONTROLE = dt.timedelta(hours=6)


def ancrer(
    etablissement_id: uuid.UUID | None, *, using: str = DEFAULT_DB_ALIAS
) -> ControleIntegriteAudit:
    """Prépare l'ancre de la chaîne courante ; renvoie le contrôle utilisé (§ 6.5)."""
    filtre = (
        {"etablissement__isnull": True}
        if etablissement_id is None
        else {"etablissement_id": etablissement_id}
    )
    controle = (
        ControleIntegriteAudit.objects.using(using)
        .filter(**filtre)
        .exclude(statut=StatutControle.EN_COURS)
        .order_by("-lance_le")
        .first()
    )
    if (
        controle is None
        or controle.statut != StatutControle.INTACTE
        or controle.lance_le < timezone.now() - FRAICHEUR_CONTROLE
    ):
        controle = verifier_chaine(etablissement_id, Declencheur.PLANIFIE, using=using)
    if controle.statut == StatutControle.INTACTE:
        alertes.programmer_ancre(controle)
    return controle


def ancrer_plateforme(*, using: str = DEFAULT_DB_ALIAS) -> ControleIntegriteAudit:
    """Ancre de la chaîne de la plateforme (destinataire : FYXOP sécurité seulement)."""
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=None, using=using):
        return ancrer(None, using=using)

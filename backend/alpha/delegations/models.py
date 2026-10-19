"""Absences et délégations (architecture § 2.2, décision P5, tâche B8).

- ``Absence`` : période déclarée par un utilisateur, validée (ou refusée) par son
  responsable hiérarchique, à défaut par un administrateur (P5).
- ``Delegation`` : pendant l'absence, le délégataire voit et traite les tâches du
  délégant (règle 3 de visibilité, ``alpha.taches.visibilite``). Une délégation
  est toujours bornée (``debut`` < ``fin``), jamais transitive (pas de
  sous-délégation) et réservée à un délégataire aux pouvoirs au moins égaux.

Cycle d'une délégation d'absence :
    EN_ATTENTE (absence soumise) → ACTIVE (absence validée) → TERMINEE (après ``fin``)
                                 → REFUSEE (absence refusée) / ANNULEE (absence annulée)
Elle est **effective** quand ``statut = ACTIVE`` et ``debut <= now < fin``. Les tâches
planifiées (``alpha.delegations.tasks``) datent son entrée en vigueur (``activee_le``,
audit ``delegation.active``) et la clôturent (``TERMINEE``, audit ``delegation.terminee``) ;
la visibilité, elle, est calculée à l'instant de la requête et ne dépend pas du
passage de ces tâches.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.functions import Coalesce

from alpha.tenancy.models import TenantModel

UUID_NUL = uuid.UUID("00000000-0000-0000-0000-000000000000")


class TsTzRange(Func):
    """``tstzrange(debut, fin)`` (intervalle semi-ouvert [debut, fin))."""

    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class MotifAbsence(models.TextChoices):
    CONGE = "CONGE", "Congé"
    MISSION = "MISSION", "Mission"
    FORMATION = "FORMATION", "Formation"
    MALADIE = "MALADIE", "Maladie"
    AUTRE = "AUTRE", "Autre"


class StatutAbsence(models.TextChoices):
    SOUMISE = "SOUMISE", "Soumise"
    VALIDEE = "VALIDEE", "Validée"
    REFUSEE = "REFUSEE", "Refusée"
    ANNULEE = "ANNULEE", "Annulée"


class Absence(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur absent",
        on_delete=models.RESTRICT,
        related_name="absences",
    )
    debut = models.DateTimeField("début")
    fin = models.DateTimeField("fin")
    motif = models.CharField("motif", max_length=12, choices=MotifAbsence.choices)
    commentaire = models.TextField("commentaire", blank=True, default="")
    statut = models.CharField(
        "statut", max_length=10, choices=StatutAbsence.choices, default=StatutAbsence.SOUMISE
    )
    valideur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="valideur",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="absences_a_valider",
        help_text="Fixé à la soumission (responsable, sinon un administrateur) ; "
        "remplacé par l'auteur effectif de la décision.",
    )
    decide_le = models.DateTimeField("décidée le", null=True, blank=True)
    motif_refus = models.TextField("motif du refus", blank=True, default="")
    cree_le = models.DateTimeField("créée le", auto_now_add=True)

    AUDIT_CHAMPS = ("utilisateur", "debut", "fin", "motif", "statut", "valideur", "decide_le")

    class Meta:
        db_table = "absence"
        verbose_name = "absence"
        verbose_name_plural = "absences"
        ordering = ["-debut"]
        constraints = [
            models.CheckConstraint(condition=Q(fin__gt=F("debut")), name="absence_fin_apres_debut"),
            models.CheckConstraint(
                condition=Q(motif__in=MotifAbsence.values), name="absence_motif_valide"
            ),
            models.CheckConstraint(
                condition=Q(statut__in=StatutAbsence.values), name="absence_statut_valide"
            ),
            models.CheckConstraint(
                condition=Q(valideur__isnull=True) | ~Q(valideur=F("utilisateur")),
                name="absence_valideur_different",
            ),
            models.UniqueConstraint(fields=["id", "etablissement"], name="absence_id_etab_uniq"),
        ]
        indexes = [
            models.Index(
                fields=["etablissement", "utilisateur", "debut"], name="absence_etab_util_idx"
            ),
            models.Index(
                fields=["valideur"],
                condition=Q(statut=StatutAbsence.SOUMISE),
                name="absence_a_valider_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Absence {self.utilisateur_id} du {self.debut:%d/%m/%Y}"


class OrigineDelegation(models.TextChoices):
    ABSENCE = "ABSENCE", "Absence"
    POUVOIR = "POUVOIR", "Délégation de pouvoir"  # réservé S2/S3


class StatutDelegation(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente"
    ACTIVE = "ACTIVE", "Active"
    TERMINEE = "TERMINEE", "Terminée"
    ANNULEE = "ANNULEE", "Annulée"
    REFUSEE = "REFUSEE", "Refusée"


#: Statuts qui « réservent » la période (contrainte d'exclusion).
STATUTS_EN_COURS = (StatutDelegation.EN_ATTENTE, StatutDelegation.ACTIVE)


class Delegation(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    origine = models.CharField(
        "origine",
        max_length=10,
        choices=OrigineDelegation.choices,
        default=OrigineDelegation.ABSENCE,
    )
    absence = models.ForeignKey(
        Absence,
        verbose_name="absence",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="delegations",
    )
    delegant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="délégant",
        on_delete=models.RESTRICT,
        related_name="delegations_donnees",
    )
    delegataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="délégataire",
        on_delete=models.RESTRICT,
        related_name="delegations_recues",
    )
    role = models.ForeignKey(
        "organisation.Role",
        verbose_name="rôle délégué",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Vide : tous les rôles du délégant.",
    )
    debut = models.DateTimeField("début")
    fin = models.DateTimeField("fin")
    statut = models.CharField(
        "statut",
        max_length=12,
        choices=StatutDelegation.choices,
        default=StatutDelegation.EN_ATTENTE,
    )
    portee = models.JSONField("portée", default=dict, blank=True)
    cree_le = models.DateTimeField("créée le", auto_now_add=True)
    # Ajouts B8 : traces des tâches planifiées (idempotence, § 6.5).
    activee_le = models.DateTimeField("entrée en vigueur le", null=True, blank=True)
    terminee_le = models.DateTimeField("terminée le", null=True, blank=True)

    AUDIT_CHAMPS = (
        "origine",
        "absence",
        "delegant",
        "delegataire",
        "role",
        "debut",
        "fin",
        "statut",
        "activee_le",
        "terminee_le",
    )

    class Meta:
        db_table = "delegation"
        verbose_name = "délégation"
        verbose_name_plural = "délégations"
        constraints = [
            models.CheckConstraint(
                condition=Q(fin__gt=F("debut")), name="delegation_fin_apres_debut"
            ),
            models.CheckConstraint(
                condition=~Q(delegataire=F("delegant")), name="delegation_delegataire_different"
            ),
            models.CheckConstraint(
                condition=Q(origine__in=OrigineDelegation.values),
                name="delegation_origine_valide",
            ),
            models.CheckConstraint(
                condition=Q(statut__in=StatutDelegation.values), name="delegation_statut_valide"
            ),
            models.CheckConstraint(
                condition=~Q(origine=OrigineDelegation.ABSENCE) | Q(absence__isnull=False),
                name="delegation_absence_obligatoire",
            ),
            # Une seule délégation en cours par (délégant, rôle) sur une période donnée.
            ExclusionConstraint(
                name="delegation_sans_chevauchement",
                expressions=[
                    (F("delegant"), RangeOperators.EQUAL),
                    (Coalesce(F("role"), Value(UUID_NUL)), RangeOperators.EQUAL),
                    (TsTzRange(F("debut"), F("fin")), RangeOperators.OVERLAPS),
                ],
                condition=Q(statut__in=STATUTS_EN_COURS),
            ),
        ]
        indexes = [
            models.Index(
                fields=["delegataire", "debut", "fin"],
                condition=Q(statut=StatutDelegation.ACTIVE),
                name="delegation_recue_active_idx",
            ),
            models.Index(fields=["delegant", "statut"], name="delegation_delegant_idx"),
        ]

    def __str__(self) -> str:
        return f"Délégation {self.delegant_id} → {self.delegataire_id}"

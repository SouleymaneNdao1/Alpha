"""Boîte « À traiter » : tâches génériques (architecture § 2.2, § 2.5, tâche B8).

Une tâche désigne un objet à traiter, quel que soit le module : un couple
(``source_type``, ``source_id``), un libellé (référence, titre, sous-titre,
montant), une échéance et un destinataire (utilisateur, ou rôle sur une unité).
Le modèle ne connaît RIEN du moteur de workflow : au sprint 2, celui-ci ouvrira
et fermera ses tâches (``source_type="workflow.instance_etape"``) par les seuls
services de ``alpha.taches.services``, comme le font déjà les absences.

Visibilité et regroupement par urgence : ``alpha.taches.visibilite``.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from alpha.tenancy.models import TenantModel


class Module(models.TextChoices):
    # Sprint 1
    COMPTE = "COMPTE", "Mon compte"
    ADMINISTRATION = "ADMINISTRATION", "Administration"
    # Sprints 2 et 3 (déclarés dès maintenant : la contrainte CHECK les accepte)
    CREDIT = "CREDIT", "Crédit"
    INTERNE = "INTERNE", "Décisions internes"
    RH = "RH", "Ressources humaines"
    TRESORERIE = "TRESORERIE", "Trésorerie"
    CONTRATS = "CONTRATS", "Contrats"
    GOUVERNANCE = "GOUVERNANCE", "Gouvernance"
    FISCAL = "FISCAL", "Fiscalité"
    PME_FOURNISSEURS = "PME_FOURNISSEURS", "Fournisseurs"
    PME_BUDGET = "PME_BUDGET", "Budget"
    PME_COMMERCIAL = "PME_COMMERCIAL", "Commercial"


class Action(models.TextChoices):
    """Action attendue : libellé du bouton de la ligne."""

    DECIDER = "DECIDER", "Décider"
    SIGNER = "SIGNER", "Signer"
    VALIDER = "VALIDER", "Valider"
    COMPLETER = "COMPLETER", "Compléter"
    TRAITER = "TRAITER", "Traiter"


class TypeEcheance(models.TextChoices):
    AVANT = "AVANT", "Avant le"
    ECHEANCE = "ECHEANCE", "Échéance le"
    EXECUTION = "EXECUTION", "Exécution le"
    PREAVIS = "PREAVIS", "Préavis avant le"


class StatutTache(models.TextChoices):
    OUVERTE = "OUVERTE", "Ouverte"
    TERMINEE = "TERMINEE", "Terminée"
    ANNULEE = "ANNULEE", "Annulée"


class Groupe(models.TextChoices):
    """Regroupement par urgence (§ 2.2), dans cet ordre d'affichage."""

    EN_RETARD = "EN_RETARD", "En retard"
    AUJOURDHUI = "AUJOURDHUI", "Aujourd'hui"
    CETTE_SEMAINE = "CETTE_SEMAINE", "Cette semaine"
    PLUS_TARD = "PLUS_TARD", "Plus tard"


def _fk_utilisateur(libelle: str, related_name: str = "+", **kwargs) -> models.ForeignKey:
    return models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=libelle,
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name=related_name,
        **kwargs,
    )


class Tache(TenantModel):
    """Élément de la boîte « À traiter » d'un utilisateur ou d'un rôle."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.CharField("module", max_length=20, choices=Module.choices)
    source_type = models.CharField(
        "type de l'objet source",
        max_length=60,
        help_text="« app.modele », ex. delegations.absence ; S2 : workflow.instance_etape.",
    )
    source_id = models.UUIDField("identifiant de l'objet source")
    reference = models.CharField("référence", max_length=40, blank=True, default="")
    titre = models.CharField("titre", max_length=200)
    sous_titre = models.CharField("sous-titre", max_length=300, blank=True, default="")
    montant = models.DecimalField("montant", max_digits=18, decimal_places=2, null=True, blank=True)
    devise = models.CharField("devise", max_length=3, default="XOF")
    action = models.CharField("action", max_length=12, choices=Action.choices)
    type_echeance = models.CharField(
        "type d'échéance", max_length=12, choices=TypeEcheance.choices, default=TypeEcheance.AVANT
    )
    echeance = models.DateTimeField(
        "échéance", null=True, blank=True, help_text="Vide : plus tard."
    )
    assigne_utilisateur = _fk_utilisateur("assignée à l'utilisateur", "taches_assignees")
    assigne_role = models.ForeignKey(
        "organisation.Role",
        verbose_name="assignée au rôle",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="taches",
    )
    assigne_unite = models.ForeignKey(
        "organisation.UniteOrganisationnelle",
        verbose_name="périmètre (unité)",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="taches",
        help_text="Avec un rôle : titulaires du rôle sur cette unité ou une unité parente.",
    )
    demandeur = _fk_utilisateur("demandeur")
    lien = models.CharField("lien (route du frontend)", max_length=300, blank=True, default="")
    statut = models.CharField(
        "statut", max_length=10, choices=StatutTache.choices, default=StatutTache.OUVERTE
    )
    resultat = models.CharField("résultat", max_length=30, blank=True, default="")
    cree_le = models.DateTimeField("créée le", auto_now_add=True)
    terminee_le = models.DateTimeField("fermée le", null=True, blank=True)
    terminee_par = _fk_utilisateur("fermée par")
    pour_compte_de = _fk_utilisateur(
        "pour le compte de", help_text="Délégant, si l'action a été faite par délégation."
    )

    #: Champs journalisés (liste blanche du journal d'audit, § 6.1).
    AUDIT_CHAMPS = (
        "module",
        "source_type",
        "source_id",
        "reference",
        "titre",
        "action",
        "echeance",
        "assigne_utilisateur",
        "assigne_role",
        "assigne_unite",
        "statut",
        "resultat",
        "terminee_par",
        "pour_compte_de",
    )

    class Meta:
        db_table = "tache"
        verbose_name = "tâche"
        verbose_name_plural = "tâches"
        constraints = [
            models.CheckConstraint(
                condition=Q(assigne_utilisateur__isnull=False) | Q(assigne_role__isnull=False),
                name="tache_destinataire_obligatoire",
            ),
            models.CheckConstraint(
                condition=Q(assigne_unite__isnull=True) | Q(assigne_role__isnull=False),
                name="tache_unite_avec_role",
            ),
            models.CheckConstraint(
                condition=Q(module__in=Module.values), name="tache_module_valide"
            ),
            models.CheckConstraint(
                condition=Q(action__in=Action.values), name="tache_action_valide"
            ),
            models.CheckConstraint(
                condition=Q(type_echeance__in=TypeEcheance.values),
                name="tache_type_echeance_valide",
            ),
            models.CheckConstraint(
                condition=Q(statut__in=StatutTache.values), name="tache_statut_valide"
            ),
            models.CheckConstraint(
                condition=Q(statut=StatutTache.OUVERTE, terminee_le__isnull=True)
                | (~Q(statut=StatutTache.OUVERTE) & Q(terminee_le__isnull=False)),
                name="tache_fermeture_datee",
            ),
            models.CheckConstraint(
                condition=Q(montant__isnull=True) | Q(montant__gte=0),
                name="tache_montant_positif",
            ),
            # Idempotence : une seule tâche ouverte par (objet source, action).
            models.UniqueConstraint(
                fields=["etablissement", "source_type", "source_id", "action"],
                condition=Q(statut=StatutTache.OUVERTE),
                name="tache_ouverte_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=["etablissement", "statut", "echeance"], name="tache_etab_statut_idx"
            ),
            models.Index(
                fields=["assigne_utilisateur"],
                condition=Q(statut=StatutTache.OUVERTE),
                name="tache_ouverte_utilisateur_idx",
            ),
            models.Index(
                fields=["assigne_role", "assigne_unite"],
                condition=Q(statut=StatutTache.OUVERTE),
                name="tache_ouverte_role_idx",
            ),
            models.Index(fields=["source_type", "source_id"], name="tache_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.titre}" if self.reference else self.titre

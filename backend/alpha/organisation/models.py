"""Organisation d'un établissement : unités, catalogue des rôles, affectations (§ 2.2).

Toutes les tables sont des tables tenant (``TenantModel`` + ``activer_rls`` dans
la migration). Les références vers une autre table tenant (utilisateur, rôle,
unité) sont doublées d'une clé étrangère composite « même établissement »
(``alpha.tenancy.coherence``), d'où la contrainte ``UNIQUE (id, etablissement)``
sur les tables cibles.
"""

from __future__ import annotations

import datetime
import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

from alpha.tenancy.models import TenantManager, TenantModel, TenantQuerySet

from .codes_permission import CodePermission, valider_codes


def _unique_id_etablissement(table: str) -> models.UniqueConstraint:
    """Cible des clés étrangères composites « même établissement »."""
    return models.UniqueConstraint(fields=["id", "etablissement"], name=f"{table}_id_etab_uniq")


# --- Unités organisationnelles --------------------------------------------------------


class TypeUnite(models.TextChoices):
    DIRECTION = "DIRECTION", "Direction"
    SERVICE = "SERVICE", "Service"
    AGENCE = "AGENCE", "Agence"
    COMITE = "COMITE", "Comité"


class UniteOrganisationnelle(TenantModel):
    """Périmètre : direction, service, agence ou comité (arbre via ``parent``)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(
        "self",
        verbose_name="unité parente",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="enfants",
    )
    type = models.CharField("type", max_length=12, choices=TypeUnite.choices)
    code = models.CharField("code", max_length=40)
    libelle = models.CharField("libellé", max_length=150)
    actif = models.BooleanField("active", default=True)
    cree_le = models.DateTimeField("créée le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        db_table = "unite_organisationnelle"
        verbose_name = "unité organisationnelle"
        verbose_name_plural = "unités organisationnelles"
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "code"], name="unite_code_uniq"),
            _unique_id_etablissement("unite"),
            models.CheckConstraint(
                condition=Q(type__in=TypeUnite.values), name="unite_type_valide"
            ),
            models.CheckConstraint(
                condition=Q(parent__isnull=True) | ~Q(parent=F("id")),
                name="unite_parent_different",
            ),
        ]
        indexes = [models.Index(fields=["etablissement", "parent"], name="unite_etab_parent_idx")]

    def __str__(self) -> str:
        return self.libelle


# --- Catalogue des rôles -------------------------------------------------------------------


class Role(TenantModel):
    """Rôle du catalogue de l'établissement (§ 2.2, § 2.3).

    ``permissions`` : codes système (``CodePermission``) ; les rôles métier semés
    par défaut n'en ont aucun, ils serviront de responsables d'étapes aux
    circuits S2 (FK ``PROTECT`` vers ``role.id``). Pas de suppression physique :
    désactivation (``actif=False``) uniquement.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("code", max_length=50)
    libelle = models.CharField("libellé", max_length=100)
    description = models.TextField("description", blank=True, default="")
    permissions = ArrayField(
        models.CharField(max_length=50, choices=CodePermission.choices),
        verbose_name="permissions",
        default=list,
        blank=True,
        validators=[valider_codes],
    )
    est_systeme = models.BooleanField(
        "rôle système",
        default=False,
        help_text="Non supprimable ; ses permissions ne peuvent pas être retirées.",
    )
    actif = models.BooleanField("actif", default=True)
    ordre = models.SmallIntegerField("ordre d'affichage", default=0)
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        db_table = "role"
        verbose_name = "rôle"
        verbose_name_plural = "rôles"
        ordering = ["ordre", "libelle"]
        constraints = [
            models.UniqueConstraint(fields=["etablissement", "code"], name="role_code_uniq"),
            models.UniqueConstraint(F("etablissement"), Lower("libelle"), name="role_libelle_uniq"),
            _unique_id_etablissement("role"),
            models.CheckConstraint(
                condition=Q(code__regex=r"^[a-z0-9]+(-[a-z0-9]+)*$"), name="role_code_format"
            ),
            models.CheckConstraint(
                condition=Q(permissions__contained_by=CodePermission.values),
                name="role_permissions_connues",
            ),
        ]
        indexes = [GinIndex(fields=["permissions"], name="role_permissions_gin")]

    def __str__(self) -> str:
        return self.libelle


# --- Affectations ----------------------------------------------------------------------------


class AffectationRoleQuerySet(TenantQuerySet):
    def actives(self, a_la_date: datetime.date | None = None):
        """Affectations en vigueur à la date donnée (aujourd'hui, heure de Dakar, par défaut)."""
        jour = a_la_date or timezone.localdate()
        return self.filter(Q(fin__isnull=True) | Q(fin__gte=jour), debut__lte=jour)

    def en_cours(self, a_la_date: datetime.date | None = None):
        """Affectations commencées et non terminées (``fin`` NULL), au sens des habilitations.

        Ajout B7 : c'est la définition retenue pour les permissions de l'API et pour
        l'invariant « dernier administrateur ». Une affectation terminée par
        l'administrateur (``fin`` = jour de clôture) cesse d'ouvrir des droits
        immédiatement, alors que ``actives()`` la compte encore jusqu'à minuit.
        """
        jour = a_la_date or timezone.localdate()
        return self.filter(fin__isnull=True, debut__lte=jour)


class AffectationRoleManager(TenantManager.from_queryset(AffectationRoleQuerySet)):
    pass


class AffectationRole(TenantModel):
    """Habilitation : un utilisateur détient un rôle, sur une unité ou tout l'établissement."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="utilisateur",
        on_delete=models.RESTRICT,
        related_name="affectations",
    )
    role = models.ForeignKey(
        Role, verbose_name="rôle", on_delete=models.RESTRICT, related_name="affectations"
    )
    unite = models.ForeignKey(
        UniteOrganisationnelle,
        verbose_name="unité",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="affectations",
        help_text="Vide : tout l'établissement.",
    )
    principal = models.BooleanField("rôle principal", default=False)
    debut = models.DateField("début", default=timezone.localdate)
    fin = models.DateField("fin", null=True, blank=True, help_text="Vide : en cours.")
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créée par",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )
    cree_le = models.DateTimeField("créée le", auto_now_add=True)

    objects = AffectationRoleManager()  # + manager non filtré hérité de TenantModel

    class Meta:
        db_table = "affectation_role"
        verbose_name = "affectation de rôle"
        verbose_name_plural = "affectations de rôles"
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur"],
                condition=Q(principal=True, fin__isnull=True),
                name="affectation_principale_unique",
            ),
            models.UniqueConstraint(
                fields=["utilisateur", "role", "unite"],
                condition=Q(fin__isnull=True),
                nulls_distinct=False,
                name="affectation_en_cours_unique",
            ),
            models.CheckConstraint(
                condition=Q(fin__isnull=True) | Q(fin__gte=F("debut")),
                name="affectation_fin_apres_debut",
            ),
        ]
        indexes = [
            models.Index(
                fields=["etablissement", "role"],
                condition=Q(fin__isnull=True),
                name="affectation_titulaires_idx",
            ),
            models.Index(fields=["utilisateur", "fin"], name="affectation_utilisateur_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur_id} · {self.role_id}"

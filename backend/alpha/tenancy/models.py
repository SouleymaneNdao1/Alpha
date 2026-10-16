"""Établissements et socle des modèles tenant (architecture § 2.2, § 3.4, § 10).

- ``Etablissement`` : client d'ALPHA (banque, SFD, PME). Table protégée par des
  politiques RLS spécifiques (lecture du seul établissement courant, écriture
  réservée à la portée « platform »).
- ``TenantModel`` : modèle abstrait dont héritent TOUTES les tables tenant ;
  ``TenantManager`` filtre automatiquement sur l'établissement courant et
  échoue fermé sans contexte ; ``save()`` refuse d'écrire pour un autre
  établissement. La RLS PostgreSQL (``alpha.tenancy.rls``) est la seconde barrière.
- ``ParametresEtablissement`` : réglages de sécurité propres à chaque
  établissement (décisions P2 et P3 du 15/10/2026), avec les valeurs par défaut validées.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from alpha.core import contexte

from .exceptions import TenantNonDefini, ViolationTenant

# --- Établissement ------------------------------------------------------------------


class TypeEtablissement(models.TextChoices):
    BANQUE = "BANQUE", "Banque"
    SFD = "SFD", "Système financier décentralisé"
    PME = "PME", "PME"


class StatutEtablissement(models.TextChoices):
    ACTIF = "ACTIF", "Actif"
    LECTURE_SEULE = "LECTURE_SEULE", "Lecture seule"
    SUSPENDU = "SUSPENDU", "Suspendu"
    ARCHIVE = "ARCHIVE", "Archivé"


class Etablissement(models.Model):
    """Établissement client (tenant). Pas de ``TenantManager`` : la RLS filtre seule.

    ``cree_par`` (§ 2.2) désigne le super-administrateur FYXOP qui a provisionné
    l'établissement ; la colonne est ajoutée par ``tenancy.0002`` (tâche B3), car
    ``utilisateur`` dépend lui-même d'``etablissement``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField("code", max_length=40, unique=True)
    raison_sociale = models.CharField("raison sociale", max_length=200)
    type = models.CharField("type", max_length=10, choices=TypeEtablissement.choices)
    pays = models.CharField("pays", max_length=2, default="SN")
    statut = models.CharField(
        "statut", max_length=15, choices=StatutEtablissement.choices, default="ACTIF"
    )
    fuseau_horaire = models.CharField("fuseau horaire", max_length=40, default="Africa/Dakar")
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
    )

    class Meta:
        db_table = "etablissement"
        verbose_name = "établissement"
        verbose_name_plural = "établissements"
        constraints = [
            models.CheckConstraint(
                condition=Q(code__regex=r"^[a-z0-9-]+$"), name="etablissement_code_format"
            ),
            models.CheckConstraint(
                condition=Q(type__in=TypeEtablissement.values), name="etablissement_type_valide"
            ),
            models.CheckConstraint(
                condition=Q(statut__in=StatutEtablissement.values),
                name="etablissement_statut_valide",
            ),
            models.CheckConstraint(
                condition=Q(pays__regex=r"^[A-Z]{2}$"), name="etablissement_pays_format"
            ),
        ]

    def __str__(self) -> str:
        return self.raison_sociale


# --- Socle des tables tenant ---------------------------------------------------------


class TenantQuerySet(models.QuerySet):
    """QuerySet des tables tenant : contrôle aussi les insertions en masse."""

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        tid = _tenant_obligatoire()
        for obj in objs:
            if obj.etablissement_id is None:
                obj.etablissement_id = tid
            elif obj.etablissement_id != tid:
                raise ViolationTenant()
        return super().bulk_create(objs, *args, **kwargs)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    """Manager par défaut des tables tenant : filtre sur l'établissement courant.

    Sans établissement courant, lève ``TenantNonDefini`` (échec fermé côté
    application) au lieu de renvoyer toutes les lignes.
    """

    def get_queryset(self):
        return super().get_queryset().filter(etablissement_id=_tenant_obligatoire())


def _tenant_obligatoire() -> uuid.UUID:
    tid = contexte.tenant_courant()
    if tid is None:
        raise TenantNonDefini()
    return tid


class TenantModel(models.Model):
    """Base abstraite de toute table tenant (§ 3.4).

    - ``objects`` : filtré sur l'établissement courant (à utiliser partout) ;
    - ``objets_globaux`` : non filtré, RÉSERVÉ aux migrations de données, aux
      commandes d'exploitation et à ``plateforme/services.py`` (vérifié par
      ``tests/test_rls_couverture.py``). Même mal utilisé, la RLS ne renvoie que
      les lignes du tenant courant.
    - la migration qui crée la table DOIT appeler ``activer_rls()`` (§ 3.6),
      ce que vérifie le test de couverture RLS.
    """

    etablissement = models.ForeignKey(
        "tenancy.Etablissement", on_delete=models.RESTRICT, editable=False
    )

    objects = TenantManager()
    objets_globaux = models.Manager()  # noqa: DJ012 - second manager, pas un champ

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self._verifier_tenant()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.etablissement_id != _tenant_obligatoire():
            raise ViolationTenant()
        return super().delete(*args, **kwargs)

    def _verifier_tenant(self) -> None:
        tid = _tenant_obligatoire()
        if self.etablissement_id is None:
            self.etablissement_id = tid
        elif self.etablissement_id != tid:
            raise ViolationTenant()


# --- Paramètres de l'établissement -------------------------------------------------------


def _entre(champ: str, minimum: int, maximum: int | None = None) -> Q:
    condition = Q(**{f"{champ}__gte": minimum})
    if maximum is not None:
        condition &= Q(**{f"{champ}__lte": maximum})
    return condition


class ParametresEtablissement(TenantModel):
    """Réglages de sécurité d'un établissement (relation 1–1, § 2.2).

    Décisions validées (§ 10) : toutes les durées de P2 et l'expiration du mot
    de passe (P3) sont réglables par établissement ; les valeurs par défaut
    ci-dessous sont celles qui ont été validées.
    """

    # Clé primaire = clé étrangère : remplace le champ ``etablissement`` hérité.
    etablissement = models.OneToOneField(
        Etablissement,
        on_delete=models.RESTRICT,
        primary_key=True,
        editable=False,
        related_name="parametres",
    )

    # Sessions (P2, § 4.8)
    inactivite_session_min = models.SmallIntegerField("inactivité de session (min)", default=15)
    duree_max_session_h = models.SmallIntegerField("durée maximale de session (h)", default=12)

    # Mot de passe (P3, § 4.9)
    mdp_longueur_min = models.SmallIntegerField("longueur minimale du mot de passe", default=12)
    mdp_historique = models.SmallIntegerField("nombre d'anciens mots de passe interdits", default=5)
    mdp_expiration_jours = models.SmallIntegerField(
        "expiration du mot de passe (jours)",
        null=True,
        blank=True,
        default=None,
        help_text="Vide : pas d'expiration périodique (défaut, P3). Ex. 90 pour la banque pilote.",
    )

    # Verrouillage (P2, § 4.2)
    tentatives_max = models.SmallIntegerField("essais avant verrouillage", default=5)
    verrouillage_min = models.SmallIntegerField("durée du verrouillage (min)", default=15)
    verrouillages_max_24h = models.SmallIntegerField(
        "verrouillages en 24 h avant déblocage par un administrateur", default=3
    )

    # Liens envoyés par e-mail (P2, § 4.3, § 4.7)
    validite_invitation_h = models.SmallIntegerField("validité de l'invitation (h)", default=72)
    validite_reinit_mdp_min = models.SmallIntegerField(
        "validité du lien de réinitialisation (min)", default=30
    )

    # Journal d'audit
    retention_audit_annees = models.SmallIntegerField(
        "durée de conservation du journal (années)", default=10
    )

    # Modules du menu (dérivés du type d'établissement ; S2/S3).
    modules_actifs = ArrayField(models.TextField(), default=list, blank=True)

    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        db_table = "parametres_etablissement"
        verbose_name = "paramètres de l'établissement"
        verbose_name_plural = "paramètres des établissements"
        constraints = [
            models.CheckConstraint(
                condition=_entre("inactivite_session_min", 5, 60),
                name="parametres_inactivite_5_60",
            ),
            models.CheckConstraint(
                condition=_entre("duree_max_session_h", 1, 24),
                name="parametres_duree_session_1_24",
            ),
            models.CheckConstraint(
                condition=_entre("mdp_longueur_min", 12), name="parametres_mdp_longueur_min_12"
            ),
            models.CheckConstraint(
                condition=_entre("mdp_historique", 0), name="parametres_mdp_historique_positif"
            ),
            models.CheckConstraint(
                condition=Q(mdp_expiration_jours__isnull=True) | _entre("mdp_expiration_jours", 1),
                name="parametres_mdp_expiration_positive",
            ),
            models.CheckConstraint(
                condition=_entre("tentatives_max", 1), name="parametres_tentatives_positif"
            ),
            models.CheckConstraint(
                condition=_entre("verrouillage_min", 1), name="parametres_verrouillage_positif"
            ),
            models.CheckConstraint(
                condition=_entre("verrouillages_max_24h", 1),
                name="parametres_verrouillages_24h_positif",
            ),
            models.CheckConstraint(
                condition=_entre("validite_invitation_h", 1),
                name="parametres_invitation_positive",
            ),
            models.CheckConstraint(
                condition=_entre("validite_reinit_mdp_min", 1),
                name="parametres_reinit_mdp_positive",
            ),
            models.CheckConstraint(
                condition=_entre("retention_audit_annees", 1),
                name="parametres_retention_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"Paramètres de {self.etablissement_id}"


# --- Manager non filtré pour les modèles hors TenantModel ----------------------------------


class ObjetsGlobauxMixin(models.Model):
    """Ajoute ``objets_globaux`` (non filtré) à un modèle qui n'hérite pas de ``TenantModel``.

    Mêmes restrictions d'usage que ``TenantModel.objets_globaux`` (vérifiées par
    ``tests/test_rls_couverture.py``). Le modèle doit déclarer
    ``Meta.default_manager_name = "objects"`` pour que son manager filtré reste
    le manager par défaut.
    """

    objets_globaux = models.Manager()

    class Meta:
        abstract = True


# --- Tables « tenant ou plateforme » (§ 3.5, tables marquées (*)) -------------------------


class TenantOuPlateformeManager(models.Manager.from_queryset(TenantQuerySet)):
    """Manager des tables (*) pouvant contenir des lignes du super-admin.

    - portée « tenant » : lignes de l'établissement courant ;
    - portée « platform » : lignes sans établissement de l'utilisateur courant
      (miroir applicatif de la politique ``isolation_tenant_ou_plateforme``) ;
    - autre portée : ``TenantNonDefini`` (échec fermé).

    Ces tables doivent avoir une colonne ``utilisateur_id``.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tid = contexte.tenant_courant()
        if tid is not None:
            return qs.filter(etablissement_id=tid)
        if contexte.scope_courant() == contexte.SCOPE_PLATFORM:
            return qs.filter(
                etablissement_id__isnull=True, utilisateur_id=contexte.utilisateur_courant()
            )
        raise TenantNonDefini()


class TenantOuPlateformeModel(TenantModel):
    """Base abstraite des tables (*) du § 3.5 : ``etablissement`` NULL pour le super-admin.

    La migration qui crée la table doit appeler ``activer_rls(table, plateforme=True)``.
    Hérite de ``TenantModel`` pour être couverte par le test de couverture RLS.
    """

    etablissement = models.ForeignKey(
        "tenancy.Etablissement",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        editable=False,
    )

    objects = TenantOuPlateformeManager()
    objets_globaux = models.Manager()  # noqa: DJ012 - second manager, pas un champ

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        self._verifier_tenant()
        return super(TenantModel, self).delete(*args, **kwargs)

    def _verifier_tenant(self) -> None:
        tid = contexte.tenant_courant()
        if tid is not None:
            if self.etablissement_id is None:
                self.etablissement_id = tid
            elif self.etablissement_id != tid:
                raise ViolationTenant()
            return
        if contexte.scope_courant() == contexte.SCOPE_PLATFORM:
            if self.etablissement_id is not None:
                raise ViolationTenant()
            return
        raise TenantNonDefini()

"""Journal d'audit chaîné, en ajout seul (architecture § 2.2, § 6).

- ``EvenementAudit`` : un événement par ligne ; une chaîne SHA-256 par
  établissement, plus la chaîne de la plateforme (``etablissement_id`` NULL).
  ``seq``, ``hash_precedent`` et ``hash`` sont fixés par le trigger
  ``audit_chainer`` ; UPDATE, DELETE et TRUNCATE sont refusés par trigger, même
  au propriétaire. On n'écrit JAMAIS par l'ORM : seul point d'entrée,
  ``alpha.audit.services.journaliser()``.
- ``ControleIntegriteAudit`` : résultat d'une vérification de chaîne ; chaque
  contrôle ``INTACTE`` sert d'ancre au suivant (détection d'une troncature).

Pas de clé étrangère vers l'utilisateur : ``acteur_id`` est un uuid libre et
``acteur_libelle`` un instantané (« Awa Diop », « Admin FYXOP », « inconnu »).
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Coalesce

UUID_PLATEFORME = uuid.UUID(int=0)


class CharFixe(models.CharField):
    """``char(n)`` PostgreSQL (empreintes hexadécimales SHA-256 de 64 caractères)."""

    def db_type(self, connection):
        return f"char({self.max_length})"


class TypeActeur(models.TextChoices):
    UTILISATEUR = "UTILISATEUR", "Utilisateur"
    SUPER_ADMIN = "SUPER_ADMIN", "Super-administrateur FYXOP"
    SYSTEME = "SYSTEME", "Système"
    API = "API", "API"
    IA = "IA", "IA"
    ANONYME = "ANONYME", "Anonyme"


class Categorie(models.TextChoices):
    CONNEXION = "CONNEXION", "Connexion"
    DECISION = "DECISION", "Décision"
    MODIFICATION = "MODIFICATION", "Modification"
    PARAMETRAGE = "PARAMETRAGE", "Paramétrage"
    ACCES_API = "ACCES_API", "Accès API"
    SUPER_ADMIN = "SUPER_ADMIN", "Super-administration"
    SECURITE = "SECURITE", "Sécurité"
    DOCUMENT = "DOCUMENT", "Document"
    ENVOI_EXTERNE = "ENVOI_EXTERNE", "Envoi externe"
    IA = "IA", "IA"


class JournalImmuable(Exception):
    """Tentative de modifier ou de supprimer un événement d'audit par l'ORM."""


class EvenementAuditQuerySet(models.QuerySet):
    """Lecture seule côté ORM (la base refuse de toute façon UPDATE et DELETE)."""

    def update(self, **kwargs):
        raise JournalImmuable("Le journal d'audit est en ajout seul : update() interdit.")

    def delete(self):
        raise JournalImmuable("Le journal d'audit est en ajout seul : delete() interdit.")

    def bulk_create(self, *args, **kwargs):
        raise JournalImmuable("Écrire dans le journal avec alpha.audit.services.journaliser().")

    def bulk_update(self, *args, **kwargs):
        raise JournalImmuable("Le journal d'audit est en ajout seul : bulk_update() interdit.")


class EvenementAudit(models.Model):
    """Événement du journal d'audit (§ 2.2, § 6). Lecture : RLS ``audit_lecture``."""

    id = models.BigAutoField(primary_key=True)  # GENERATED ALWAYS AS IDENTITY (migration)
    etablissement = models.ForeignKey(
        "tenancy.Etablissement",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        help_text="NULL : chaîne de la plateforme.",
    )
    seq = models.BigIntegerField("rang dans la chaîne", editable=False)
    horodatage = models.DateTimeField("horodatage", editable=False)
    acteur_type = models.CharField("type d'acteur", max_length=12, choices=TypeActeur.choices)
    acteur_id = models.UUIDField("identifiant de l'acteur", null=True, blank=True)
    acteur_libelle = models.CharField("acteur", max_length=150)
    categorie = models.CharField("catégorie", max_length=15, choices=Categorie.choices)
    action = models.CharField("action", max_length=60)
    objet_type = models.CharField("type d'objet", max_length=60, blank=True, default="")
    objet_id = models.CharField("identifiant de l'objet", max_length=64, blank=True, default="")
    objet_libelle = models.CharField("objet", max_length=200, blank=True, default="")
    avant = models.JSONField("avant", null=True, blank=True)
    apres = models.JSONField("après", null=True, blank=True)
    detail = models.TextField("détail", blank=True, default="")
    ip = models.GenericIPAddressField("adresse IP", null=True, blank=True)
    user_agent = models.CharField("user agent", max_length=300, blank=True, default="")
    request_id = models.UUIDField("identifiant de requête", null=True, blank=True)
    payload_canonique = models.TextField("payload canonique", editable=False)
    hash_precedent = CharFixe("empreinte précédente", max_length=64, editable=False)
    hash = CharFixe("empreinte", max_length=64, editable=False)

    objects = EvenementAuditQuerySet.as_manager()

    class Meta:
        db_table = "evenement_audit"
        verbose_name = "événement d'audit"
        verbose_name_plural = "événements d'audit"
        constraints = [
            models.UniqueConstraint(
                Coalesce("etablissement", Value(UUID_PLATEFORME, output_field=models.UUIDField())),
                "seq",
                name="evenement_audit_chaine_seq_uniq",
            ),
            models.CheckConstraint(
                condition=Q(acteur_type__in=TypeActeur.values),
                name="evenement_audit_acteur_type_valide",
            ),
            models.CheckConstraint(
                condition=Q(categorie__in=Categorie.values),
                name="evenement_audit_categorie_valide",
            ),
            models.CheckConstraint(condition=Q(seq__gte=1), name="evenement_audit_seq_positif"),
        ]
        indexes = [
            models.Index(fields=["etablissement", "-horodatage"], name="evt_audit_etab_horo_idx"),
            models.Index(
                fields=["etablissement", "categorie", "-horodatage"],
                name="evt_audit_etab_cat_horo_idx",
            ),
            models.Index(
                fields=["etablissement", "acteur_id", "-horodatage"],
                name="evt_audit_etab_acteur_idx",
            ),
            models.Index(
                fields=["etablissement", "objet_type", "objet_id"], name="evt_audit_etab_objet_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"#{self.seq} {self.action}"

    def save(self, *args, **kwargs):
        raise JournalImmuable("Écrire dans le journal avec alpha.audit.services.journaliser().")

    def delete(self, *args, **kwargs):
        raise JournalImmuable("Le journal d'audit est en ajout seul : delete() interdit.")


class Declencheur(models.TextChoices):
    PLANIFIE = "PLANIFIE", "Planifié"
    MANUEL = "MANUEL", "Manuel"


class StatutControle(models.TextChoices):
    EN_COURS = "EN_COURS", "En cours"
    INTACTE = "INTACTE", "Intacte"
    ROMPUE = "ROMPUE", "Rompue"
    ERREUR = "ERREUR", "Erreur"


class ControleIntegriteAudit(models.Model):
    """Contrôle d'intégrité d'une chaîne (§ 2.2, § 6.4). Un contrôle INTACTE est une ancre."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    etablissement = models.ForeignKey(
        "tenancy.Etablissement",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        help_text="NULL : chaîne de la plateforme.",
    )
    lance_le = models.DateTimeField("lancé le")
    termine_le = models.DateTimeField("terminé le", null=True, blank=True)
    declencheur = models.CharField("déclencheur", max_length=10, choices=Declencheur.choices)
    statut = models.CharField(
        "statut", max_length=10, choices=StatutControle.choices, default=StatutControle.EN_COURS
    )
    nb_evenements = models.BigIntegerField("événements vérifiés", default=0)
    dernier_seq = models.BigIntegerField("dernier rang", null=True, blank=True)
    dernier_hash = CharFixe("dernière empreinte", max_length=64, null=True, blank=True)
    premier_seq_invalide = models.BigIntegerField("premier rang invalide", null=True, blank=True)
    message = models.TextField("message", blank=True, default="")

    class Meta:
        db_table = "controle_integrite_audit"
        verbose_name = "contrôle d'intégrité du journal"
        verbose_name_plural = "contrôles d'intégrité du journal"
        constraints = [
            models.CheckConstraint(
                condition=Q(declencheur__in=Declencheur.values),
                name="controle_audit_declencheur_valide",
            ),
            models.CheckConstraint(
                condition=Q(statut__in=StatutControle.values),
                name="controle_audit_statut_valide",
            ),
        ]
        indexes = [
            models.Index(fields=["etablissement", "-lance_le"], name="ctrl_audit_etab_lance_idx"),
        ]

    def __str__(self) -> str:
        return f"Contrôle {self.statut} du {self.lance_le:%d/%m/%Y %H:%M}"

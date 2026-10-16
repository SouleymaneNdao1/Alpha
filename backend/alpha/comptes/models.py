"""Comptes : utilisateur (``AUTH_USER_MODEL``) et jetons à usage unique (§ 2.2, tâche B3).

``Utilisateur`` n'hérite pas de ``TenantModel`` : un super-administrateur FYXOP
n'a pas d'établissement (``etablissement`` NULL, ``est_super_admin`` vrai). Son
manager applique la même règle que la politique RLS ``isolation_utilisateur`` :
- portée « tenant » : utilisateurs de l'établissement courant ;
- portée « platform » : super-administrateurs ;
- autre portée : ``TenantNonDefini`` (échec fermé).

La connexion, qui ne connaît pas encore l'établissement, passe par
``alpha_resoudre_connexion`` (``alpha.comptes.resolution``), puis relit
l'utilisateur par ce manager sous ``contexte_tenant``.

Les autres tables du § 2.2 (Authenticator, codes de secours, sessions,
historique des mots de passe, téléphone perdu) relèvent des tâches B5 et B6.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models import F, Q

from alpha.core import contexte
from alpha.tenancy.exceptions import TenantNonDefini, ViolationTenant
from alpha.tenancy.models import ObjetsGlobauxMixin, TenantOuPlateformeModel

# --- Types de colonnes ---------------------------------------------------------------------


class EmailInsensibleCasse(models.EmailField):
    """Adresse e-mail en ``citext`` : comparaisons et unicité insensibles à la casse (P1)."""

    def db_type(self, connection):
        return "citext"


class Empreinte64(models.CharField):
    """Empreinte hexadécimale de 64 caractères (SHA-256, HMAC-SHA256) en ``char(64)``."""

    def __init__(self, *args, **kwargs):
        kwargs["max_length"] = 64
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        nom, chemin, args, kwargs = super().deconstruct()
        kwargs.pop("max_length", None)
        return nom, chemin, args, kwargs

    def db_type(self, connection):
        return "char(64)"


def _unique_id_etablissement(table: str) -> models.UniqueConstraint:
    return models.UniqueConstraint(fields=["id", "etablissement"], name=f"{table}_id_etab_uniq")


# --- Utilisateur ----------------------------------------------------------------------------


class StatutUtilisateur(models.TextChoices):
    INVITE = "INVITE", "Invité"
    ACTIF = "ACTIF", "Actif"
    SUSPENDU = "SUSPENDU", "Suspendu"
    DESACTIVE = "DESACTIVE", "Désactivé"


class Langue(models.TextChoices):
    FR = "fr", "Français"
    EN = "en", "English"


class UtilisateurManager(BaseUserManager):
    """Manager par défaut : filtré par le contexte (voir la docstring du module)."""

    def get_queryset(self):
        qs = super().get_queryset()
        tid = contexte.tenant_courant()
        if tid is not None:
            return qs.filter(etablissement_id=tid)
        if contexte.scope_courant() == contexte.SCOPE_PLATFORM:
            return qs.filter(etablissement_id__isnull=True)
        raise TenantNonDefini()

    def create_user(self, email, prenom, nom, password=None, **champs):
        """Crée un utilisateur de l'établissement courant (mot de passe inutilisable par défaut)."""
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        utilisateur = self.model(
            email=self.normalize_email(email), prenom=prenom, nom=nom, **champs
        )
        utilisateur.set_password(password)  # None → mot de passe inutilisable
        utilisateur.save(using=self._db)
        return utilisateur

    def create_superuser(self, *args, **kwargs):
        # § 3.8 : un super-admin n'est créé QUE par « manage.py creer_super_admin » (B10).
        raise NotImplementedError(
            "Utiliser « manage.py creer_super_admin » pour créer un super-administrateur."
        )


class Utilisateur(AbstractBaseUser, ObjetsGlobauxMixin):
    """Compte d'un utilisateur d'établissement ou d'un super-administrateur FYXOP."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    etablissement = models.ForeignKey(
        "tenancy.Etablissement",
        verbose_name="établissement",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        editable=False,
        related_name="utilisateurs",
        help_text="Vide uniquement pour un super-administrateur FYXOP.",
    )
    est_super_admin = models.BooleanField("super-administrateur FYXOP", default=False)
    email = EmailInsensibleCasse("adresse e-mail", max_length=254, unique=True)
    prenom = models.CharField("prénom", max_length=80)
    nom = models.CharField("nom", max_length=80)
    # NULL plutôt que chaîne vide (§ 2.2) : la contrainte E.164 ne vise que les numéros saisis.
    telephone_mobile = models.CharField(  # noqa: DJ001
        "téléphone mobile", max_length=20, null=True, blank=True, help_text="Format E.164."
    )
    langue = models.CharField("langue", max_length=2, choices=Langue.choices, default=Langue.FR)
    statut = models.CharField(
        "statut", max_length=12, choices=StatutUtilisateur.choices, default=StatutUtilisateur.INVITE
    )
    responsable = models.ForeignKey(
        "self",
        verbose_name="responsable hiérarchique",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="collaborateurs",
        help_text="Valide les absences (P5) ; même établissement.",
    )
    mfa_a_reconfigurer = models.BooleanField("MFA à reconfigurer", default=False)
    signature_bloquee = models.BooleanField("signature bloquée", default=False)
    echecs_connexion = models.SmallIntegerField("échecs de connexion", default=0)
    verrouille_jusqua = models.DateTimeField("verrouillé jusqu'à", null=True, blank=True)
    verrouillages_24h = models.SmallIntegerField("verrouillages sur 24 h", default=0)
    bloque_par_admin = models.BooleanField("bloqué (déblocage administrateur)", default=False)
    derniere_connexion = models.DateTimeField("dernière connexion", null=True, blank=True)
    mdp_modifie_le = models.DateTimeField("mot de passe modifié le", null=True, blank=True)
    active_le = models.DateTimeField("activé le", null=True, blank=True)
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)
    cree_par = models.ForeignKey(
        "self",
        verbose_name="créé par",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )

    # « derniere_connexion » remplace « last_login » : la mise à jour est faite
    # explicitement par la connexion (B5), pas par le signal de Django.
    last_login = None

    objects = UtilisateurManager()  # + manager non filtré via ObjetsGlobauxMixin

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["prenom", "nom"]

    class Meta:
        db_table = "utilisateur"
        default_manager_name = "objects"
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        constraints = [
            models.CheckConstraint(
                condition=Q(etablissement__isnull=True, est_super_admin=True)
                | Q(etablissement__isnull=False, est_super_admin=False),
                name="utilisateur_super_admin_sans_etab",
            ),
            models.CheckConstraint(
                condition=Q(statut__in=StatutUtilisateur.values),
                name="utilisateur_statut_valide",
            ),
            models.CheckConstraint(
                condition=Q(langue__in=Langue.values), name="utilisateur_langue_valide"
            ),
            models.CheckConstraint(
                condition=Q(telephone_mobile__isnull=True)
                | Q(telephone_mobile__regex=r"^\+[1-9][0-9]{6,14}$"),
                name="utilisateur_telephone_e164",
            ),
            models.CheckConstraint(
                condition=Q(responsable__isnull=True) | ~Q(responsable=F("id")),
                name="utilisateur_responsable_different",
            ),
            models.CheckConstraint(
                condition=Q(echecs_connexion__gte=0, verrouillages_24h__gte=0),
                name="utilisateur_compteurs_positifs",
            ),
            _unique_id_etablissement("utilisateur"),
        ]
        indexes = [
            models.Index(fields=["etablissement", "statut"], name="utilisateur_etab_statut_idx"),
            models.Index(
                fields=["etablissement", "nom", "prenom"], name="utilisateur_etab_nom_idx"
            ),
            models.Index(fields=["responsable"], name="utilisateur_responsable_idx"),
        ]

    def __str__(self) -> str:
        return self.nom_complet

    @property
    def nom_complet(self) -> str:
        return f"{self.prenom} {self.nom}".strip()

    def get_full_name(self) -> str:
        return self.nom_complet

    def get_short_name(self) -> str:
        return self.prenom

    @property
    def is_active(self) -> bool:  # lu par ModelBackend (session invalidée si faux)
        return self.statut == StatutUtilisateur.ACTIF

    def save(self, *args, **kwargs):
        self._verifier_tenant()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._verifier_tenant()
        return super().delete(*args, **kwargs)

    def _verifier_tenant(self) -> None:
        """Même règle que ``TenantModel`` ; un super-admin exige la portée « platform »."""
        tid = contexte.tenant_courant()
        if self.est_super_admin:
            if contexte.scope_courant() != contexte.SCOPE_PLATFORM:
                raise ViolationTenant("Un super-administrateur ne s'écrit qu'en portée plateforme.")
            return
        if tid is None:
            raise TenantNonDefini()
        if self.etablissement_id is None:
            self.etablissement_id = tid
        elif self.etablissement_id != tid:
            raise ViolationTenant()


# --- Jetons à usage unique -----------------------------------------------------------------


class ObjetJeton(models.TextChoices):
    INVITATION = "INVITATION", "Invitation"
    REINIT_MDP = "REINIT_MDP", "Réinitialisation du mot de passe"
    REENROLEMENT_MFA = "REENROLEMENT_MFA", "Réenrôlement MFA"


class EtapeJeton(models.TextChoices):
    CREE = "CREE", "Créé"
    MDP_OK = "MDP_OK", "Mot de passe défini"
    TOTP_EN_ATTENTE = "TOTP_EN_ATTENTE", "Authenticator en attente"
    TOTP_OK = "TOTP_OK", "Authenticator confirmé"


class JetonUsageUnique(TenantOuPlateformeModel):
    """Lien envoyé par e-mail (activation, réinitialisation, réenrôlement).

    Seule l'empreinte SHA-256 est stockée ; le jeton en clair n'existe que dans
    l'e-mail. Le lien est résolu, avant tout contexte, par ``alpha_resoudre_jeton``.
    Table (*) du § 3.5 : ``etablissement`` NULL pour un super-administrateur.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="jetons",
    )
    objet = models.CharField("objet", max_length=20, choices=ObjetJeton.choices)
    jeton_hash = Empreinte64("empreinte SHA-256 du jeton", unique=True)
    etape = models.CharField(
        "étape", max_length=20, choices=EtapeJeton.choices, default=EtapeJeton.CREE
    )
    expire_le = models.DateTimeField("expire le")
    utilise_le = models.DateTimeField("utilisé le", null=True, blank=True)
    annule_le = models.DateTimeField("annulé le", null=True, blank=True)
    cree_par = models.ForeignKey(
        Utilisateur,
        verbose_name="créé par",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )
    cree_le = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        db_table = "jeton_usage_unique"
        verbose_name = "jeton à usage unique"
        verbose_name_plural = "jetons à usage unique"
        constraints = [
            models.CheckConstraint(
                condition=Q(objet__in=ObjetJeton.values), name="jeton_objet_valide"
            ),
            models.CheckConstraint(
                condition=Q(etape__in=EtapeJeton.values), name="jeton_etape_valide"
            ),
            models.CheckConstraint(
                condition=Q(jeton_hash__regex=r"^[0-9a-f]{64}$"), name="jeton_hash_format"
            ),
        ]
        indexes = [
            # Annulation des jetons précédents du même objet (§ 2.2).
            models.Index(
                fields=["utilisateur", "objet"],
                condition=Q(utilise_le__isnull=True, annule_le__isnull=True),
                name="jeton_en_cours_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.objet} · {self.utilisateur_id}"

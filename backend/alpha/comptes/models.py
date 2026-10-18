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

Tâche B5 : ``AuthenticatorTOTP``, ``CodeSecours``, ``SessionAppareil`` et
``HistoriqueMotDePasse`` (tables (*) du § 3.5, politique « tenant ou
plateforme »). Le signalement « téléphone perdu » relève de B6 ; le blocage de
la signature qu'il entraîne est porté dès B5 par ``Utilisateur.signature_bloquee``
et vérifié par ``alpha.comptes.mfa.verifier_signature_autorisee``.
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

    @property
    def peut_signer(self) -> bool:
        """Faux après un signalement « téléphone perdu » (lu par la signature S2, CDC § 4.6)."""
        return self.is_active and not self.signature_bloquee

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


# --- MFA : Authenticator TOTP et codes de secours (§ 2.2, § 4.2, § 4.4 ; tâche B5) ----------


class StatutAuthenticator(models.TextChoices):
    EN_ATTENTE = "EN_ATTENTE", "En attente de confirmation"
    ACTIF = "ACTIF", "Actif"
    SUSPENDU = "SUSPENDU", "Suspendu (téléphone perdu)"
    REVOQUE = "REVOQUE", "Révoqué"


class AuthenticatorTOTP(TenantOuPlateformeModel):
    """Application d'authentification (TOTP, RFC 6238) d'un utilisateur.

    Le secret base32 (160 bits) n'est stocké que chiffré (``alpha.comptes.chiffrement``,
    MultiFernet sur ``ALPHA_CLES_CHIFFREMENT``) ; il n'est jamais journalisé.
    ``dernier_pas`` : dernier compteur TOTP accepté ; tout code d'un pas inférieur
    ou égal est refusé (anti-rejeu). Un Authenticator ``SUSPENDU`` (téléphone
    perdu) n'est plus accepté ; seuls les codes de secours restent utilisables.
    """

    AUDIT_CHAMPS = ("libelle", "statut", "cle_version", "confirme_le", "revoque_le")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="authenticators",
    )
    secret_chiffre = models.BinaryField("secret chiffré (jeton MultiFernet)")
    cle_version = models.SmallIntegerField("version de la clé de chiffrement")
    libelle = models.CharField("libellé", max_length=80, blank=True, default="")
    statut = models.CharField(
        "statut",
        max_length=10,
        choices=StatutAuthenticator.choices,
        default=StatutAuthenticator.EN_ATTENTE,
    )
    dernier_pas = models.BigIntegerField("dernier pas TOTP accepté", null=True, blank=True)
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    confirme_le = models.DateTimeField("confirmé le", null=True, blank=True)
    revoque_le = models.DateTimeField("révoqué le", null=True, blank=True)

    class Meta:
        db_table = "authenticator_totp"
        verbose_name = "Authenticator TOTP"
        verbose_name_plural = "Authenticators TOTP"
        constraints = [
            models.CheckConstraint(
                condition=Q(statut__in=StatutAuthenticator.values),
                name="authenticator_statut_valide",
            ),
            models.UniqueConstraint(
                fields=["utilisateur"],
                condition=Q(statut__in=["ACTIF", "SUSPENDU"]),
                name="authenticator_un_seul_actif",
            ),
        ]
        indexes = [
            models.Index(fields=["utilisateur", "statut"], name="authenticator_util_statut_idx"),
        ]

    def __str__(self) -> str:
        return f"Authenticator {self.statut} · {self.utilisateur_id}"


class CodeSecours(TenantOuPlateformeModel):
    """Code de secours à usage unique (§ 4.4) ; seul son HMAC-SHA256 poivré est stocké."""

    AUDIT_CHAMPS = ("lot", "utilise_le", "invalide_le")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="codes_secours",
    )
    lot = models.UUIDField("lot de génération")
    code_hmac = Empreinte64("HMAC-SHA256 du code normalisé")
    utilise_le = models.DateTimeField("utilisé le", null=True, blank=True)
    invalide_le = models.DateTimeField("invalidé le", null=True, blank=True)

    class Meta:
        db_table = "code_secours"
        verbose_name = "code de secours"
        verbose_name_plural = "codes de secours"
        constraints = [
            models.UniqueConstraint(
                fields=["utilisateur", "code_hmac"], name="code_secours_hmac_uniq"
            ),
            models.CheckConstraint(
                condition=Q(code_hmac__regex=r"^[0-9a-f]{64}$"), name="code_secours_hmac_format"
            ),
        ]
        indexes = [
            models.Index(
                fields=["utilisateur"],
                condition=Q(utilise_le__isnull=True, invalide_le__isnull=True),
                name="code_secours_disponibles_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Code de secours · {self.utilisateur_id}"


# --- Sessions par appareil (§ 2.2, § 4.8 ; tâche B5) ---------------------------------------


class MethodeMfa(models.TextChoices):
    TOTP = "TOTP", "Application d'authentification"
    CODE_SECOURS = "CODE_SECOURS", "Code de secours"


class MotifFinSession(models.TextChoices):
    DECONNEXION = "DECONNEXION", "Déconnexion"
    INACTIVITE = "INACTIVITE", "Inactivité"
    EXPIRATION = "EXPIRATION", "Durée maximale atteinte"
    REVOCATION_UTILISATEUR = "REVOCATION_UTILISATEUR", "Révoquée par l'utilisateur"
    REVOCATION_ADMIN = "REVOCATION_ADMIN", "Révoquée par un administrateur"
    TELEPHONE_PERDU = "TELEPHONE_PERDU", "Téléphone perdu"
    MDP_CHANGE = "MDP_CHANGE", "Mot de passe modifié"


class SessionAppareil(TenantOuPlateformeModel):
    """Session ouverte sur un appareil, après mot de passe ET MFA (§ 4.2 étape 11, § 4.8).

    ``cle_session_hash`` : SHA-256 de la clé de session Django (la clé elle-même
    n'est jamais stockée ici). Une session absente ou révoquée est refusée par
    ``SessionActiviteMiddleware`` (401 ``SESSION_EXPIREE``).
    """

    AUDIT_CHAMPS = (
        "appareil",
        "ip",
        "methode_mfa",
        "cree_le",
        "derniere_activite",
        "expire_le",
        "revoque_le",
        "motif_fin",
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="sessions_appareil",
    )
    cle_session_hash = Empreinte64("SHA-256 de la clé de session", unique=True)
    appareil = models.CharField("appareil", max_length=120, blank=True, default="")
    user_agent = models.TextField("user agent", blank=True, default="")
    ip = models.GenericIPAddressField("adresse IP", null=True, blank=True)
    methode_mfa = models.CharField("méthode MFA", max_length=12, choices=MethodeMfa.choices)
    cree_le = models.DateTimeField("créée le")
    derniere_activite = models.DateTimeField("dernière activité")
    expire_le = models.DateTimeField("expire le")
    revoque_le = models.DateTimeField("révoquée le", null=True, blank=True)
    motif_fin = models.CharField(
        "motif de fin", max_length=25, choices=MotifFinSession.choices, blank=True, default=""
    )

    class Meta:
        db_table = "session_appareil"
        verbose_name = "session d'appareil"
        verbose_name_plural = "sessions d'appareil"
        constraints = [
            models.CheckConstraint(
                condition=Q(methode_mfa__in=MethodeMfa.values), name="session_methode_mfa_valide"
            ),
            models.CheckConstraint(
                condition=Q(motif_fin="") | Q(motif_fin__in=MotifFinSession.values),
                name="session_motif_fin_valide",
            ),
            models.CheckConstraint(
                condition=Q(cle_session_hash__regex=r"^[0-9a-f]{64}$"),
                name="session_cle_hash_format",
            ),
        ]
        indexes = [
            models.Index(fields=["utilisateur", "revoque_le"], name="session_util_revoque_idx"),
            models.Index(
                fields=["etablissement", "derniere_activite"], name="session_etab_activite_idx"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.appareil or 'appareil inconnu'} · {self.utilisateur_id}"

    @property
    def active(self) -> bool:
        return self.revoque_le is None


# --- Historique des mots de passe (§ 2.2, § 4.9 ; tâche B5) -------------------------------


class HistoriqueMotDePasse(TenantOuPlateformeModel):
    """Anciens hachages Argon2 : un mot de passe ne peut pas reprendre l'un des N derniers."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    utilisateur = models.ForeignKey(
        Utilisateur,
        verbose_name="utilisateur",
        on_delete=models.CASCADE,
        related_name="historique_mots_de_passe",
    )
    password = models.CharField("hachage du mot de passe", max_length=128)
    cree_le = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        db_table = "historique_mot_de_passe"
        verbose_name = "ancien mot de passe"
        verbose_name_plural = "historique des mots de passe"
        indexes = [
            models.Index(fields=["utilisateur", "-cree_le"], name="historique_mdp_util_idx"),
        ]

    def __str__(self) -> str:
        return f"Ancien mot de passe · {self.utilisateur_id}"

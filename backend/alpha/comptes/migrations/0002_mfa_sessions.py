# Générée par Django 5.2.18 le 18/10/2026, complétée à la main (tâche B5).
#
# Tables authenticator_totp, code_secours, historique_mot_de_passe et
# session_appareil (§ 2.2). Ce sont des tables (*) du § 3.5 (lignes du
# super-admin possibles, etablissement_id NULL) : RLS activée et forcée dans la
# MÊME migration avec la politique « tenant ou plateforme » (§ 3.6), puis clé
# étrangère composite « même établissement » vers utilisateur.

import alpha.comptes.models
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

from alpha.tenancy.coherence import cle_meme_etablissement
from alpha.tenancy.rls import activer_rls

TABLES = ("authenticator_totp", "code_secours", "historique_mot_de_passe", "session_appareil")


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0001_initial"),
        ("tenancy", "0003_parametres_email_controle_interne"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthenticatorTOTP",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "secret_chiffre",
                    models.BinaryField(
                        verbose_name="secret chiffré (jeton MultiFernet)"
                    ),
                ),
                (
                    "cle_version",
                    models.SmallIntegerField(
                        verbose_name="version de la clé de chiffrement"
                    ),
                ),
                (
                    "libelle",
                    models.CharField(
                        blank=True, default="", max_length=80, verbose_name="libellé"
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("EN_ATTENTE", "En attente de confirmation"),
                            ("ACTIF", "Actif"),
                            ("SUSPENDU", "Suspendu (téléphone perdu)"),
                            ("REVOQUE", "Révoqué"),
                        ],
                        default="EN_ATTENTE",
                        max_length=10,
                        verbose_name="statut",
                    ),
                ),
                (
                    "dernier_pas",
                    models.BigIntegerField(
                        blank=True, null=True, verbose_name="dernier pas TOTP accepté"
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créé le"),
                ),
                (
                    "confirme_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="confirmé le"
                    ),
                ),
                (
                    "revoque_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="révoqué le"
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="tenancy.etablissement",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="authenticators",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "Authenticator TOTP",
                "verbose_name_plural": "Authenticators TOTP",
                "db_table": "authenticator_totp",
                "indexes": [
                    models.Index(
                        fields=["utilisateur", "statut"],
                        name="authenticator_util_statut_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "statut__in",
                                ["EN_ATTENTE", "ACTIF", "SUSPENDU", "REVOQUE"],
                            )
                        ),
                        name="authenticator_statut_valide",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("statut__in", ["ACTIF", "SUSPENDU"])),
                        fields=("utilisateur",),
                        name="authenticator_un_seul_actif",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CodeSecours",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("lot", models.UUIDField(verbose_name="lot de génération")),
                (
                    "code_hmac",
                    alpha.comptes.models.Empreinte64(
                        verbose_name="HMAC-SHA256 du code normalisé"
                    ),
                ),
                (
                    "utilise_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="utilisé le"
                    ),
                ),
                (
                    "invalide_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="invalidé le"
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="tenancy.etablissement",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="codes_secours",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "code de secours",
                "verbose_name_plural": "codes de secours",
                "db_table": "code_secours",
                "indexes": [
                    models.Index(
                        condition=models.Q(
                            ("invalide_le__isnull", True), ("utilise_le__isnull", True)
                        ),
                        fields=["utilisateur"],
                        name="code_secours_disponibles_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("utilisateur", "code_hmac"),
                        name="code_secours_hmac_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("code_hmac__regex", "^[0-9a-f]{64}$")),
                        name="code_secours_hmac_format",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="HistoriqueMotDePasse",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "password",
                    models.CharField(
                        max_length=128, verbose_name="hachage du mot de passe"
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créé le"),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="tenancy.etablissement",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="historique_mots_de_passe",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "ancien mot de passe",
                "verbose_name_plural": "historique des mots de passe",
                "db_table": "historique_mot_de_passe",
                "indexes": [
                    models.Index(
                        fields=["utilisateur", "-cree_le"],
                        name="historique_mdp_util_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SessionAppareil",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "cle_session_hash",
                    alpha.comptes.models.Empreinte64(
                        unique=True, verbose_name="SHA-256 de la clé de session"
                    ),
                ),
                (
                    "appareil",
                    models.CharField(
                        blank=True, default="", max_length=120, verbose_name="appareil"
                    ),
                ),
                (
                    "user_agent",
                    models.TextField(blank=True, default="", verbose_name="user agent"),
                ),
                (
                    "ip",
                    models.GenericIPAddressField(
                        blank=True, null=True, verbose_name="adresse IP"
                    ),
                ),
                (
                    "methode_mfa",
                    models.CharField(
                        choices=[
                            ("TOTP", "Application d'authentification"),
                            ("CODE_SECOURS", "Code de secours"),
                        ],
                        max_length=12,
                        verbose_name="méthode MFA",
                    ),
                ),
                ("cree_le", models.DateTimeField(verbose_name="créée le")),
                (
                    "derniere_activite",
                    models.DateTimeField(verbose_name="dernière activité"),
                ),
                ("expire_le", models.DateTimeField(verbose_name="expire le")),
                (
                    "revoque_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="révoquée le"
                    ),
                ),
                (
                    "motif_fin",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("DECONNEXION", "Déconnexion"),
                            ("INACTIVITE", "Inactivité"),
                            ("EXPIRATION", "Durée maximale atteinte"),
                            ("REVOCATION_UTILISATEUR", "Révoquée par l'utilisateur"),
                            ("REVOCATION_ADMIN", "Révoquée par un administrateur"),
                            ("TELEPHONE_PERDU", "Téléphone perdu"),
                            ("MDP_CHANGE", "Mot de passe modifié"),
                        ],
                        default="",
                        max_length=25,
                        verbose_name="motif de fin",
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="tenancy.etablissement",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sessions_appareil",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "session d'appareil",
                "verbose_name_plural": "sessions d'appareil",
                "db_table": "session_appareil",
                "indexes": [
                    models.Index(
                        fields=["utilisateur", "revoque_le"],
                        name="session_util_revoque_idx",
                    ),
                    models.Index(
                        fields=["etablissement", "derniere_activite"],
                        name="session_etab_activite_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("methode_mfa__in", ["TOTP", "CODE_SECOURS"])
                        ),
                        name="session_methode_mfa_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("motif_fin", ""),
                            (
                                "motif_fin__in",
                                [
                                    "DECONNEXION",
                                    "INACTIVITE",
                                    "EXPIRATION",
                                    "REVOCATION_UTILISATEUR",
                                    "REVOCATION_ADMIN",
                                    "TELEPHONE_PERDU",
                                    "MDP_CHANGE",
                                ],
                            ),
                            _connector="OR",
                        ),
                        name="session_motif_fin_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("cle_session_hash__regex", "^[0-9a-f]{64}$")
                        ),
                        name="session_cle_hash_format",
                    ),
                ],
            },
        ),
        *[activer_rls(table, plateforme=True) for table in TABLES],
        *[cle_meme_etablissement(table, "utilisateur_id", "utilisateur") for table in TABLES],
    ]

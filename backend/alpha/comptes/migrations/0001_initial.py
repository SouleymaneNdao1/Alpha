# Générée par Django 5.2.18 le 16/10/2026, complétée à la main (tâche B3).
#
# Ordre des opérations (architecture § 2.2, § 3.5, § 3.6) :
#   1. tables utilisateur et jeton_usage_unique, contraintes et index ;
#   2. RLS dans la MÊME migration : isolation_utilisateur (politique spécifique)
#      et isolation_tenant_ou_plateforme pour jeton_usage_unique (table (*)) ;
#   3. clés étrangères composites « même établissement » (responsable, jeton) ;
#   4. fonctions SECURITY DEFINER alpha_resoudre_connexion / alpha_resoudre_jeton.
#
# Les tables sont créées par alpha_owner après tenancy.0001 : les DEFAULT
# PRIVILEGES donnent SELECT/INSERT/UPDATE/DELETE à alpha_app.

import alpha.comptes.models
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

from alpha.comptes import sql
from alpha.tenancy.coherence import cle_meme_etablissement
from alpha.tenancy.rls import activer_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Utilisateur",
            fields=[
                ("password", models.CharField(max_length=128, verbose_name="password")),
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
                    "est_super_admin",
                    models.BooleanField(
                        default=False, verbose_name="super-administrateur FYXOP"
                    ),
                ),
                (
                    "email",
                    alpha.comptes.models.EmailInsensibleCasse(
                        max_length=254, unique=True, verbose_name="adresse e-mail"
                    ),
                ),
                ("prenom", models.CharField(max_length=80, verbose_name="prénom")),
                ("nom", models.CharField(max_length=80, verbose_name="nom")),
                (
                    "telephone_mobile",
                    models.CharField(
                        blank=True,
                        help_text="Format E.164.",
                        max_length=20,
                        null=True,
                        verbose_name="téléphone mobile",
                    ),
                ),
                (
                    "langue",
                    models.CharField(
                        choices=[("fr", "Français"), ("en", "English")],
                        default="fr",
                        max_length=2,
                        verbose_name="langue",
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("INVITE", "Invité"),
                            ("ACTIF", "Actif"),
                            ("SUSPENDU", "Suspendu"),
                            ("DESACTIVE", "Désactivé"),
                        ],
                        default="INVITE",
                        max_length=12,
                        verbose_name="statut",
                    ),
                ),
                (
                    "mfa_a_reconfigurer",
                    models.BooleanField(
                        default=False, verbose_name="MFA à reconfigurer"
                    ),
                ),
                (
                    "signature_bloquee",
                    models.BooleanField(
                        default=False, verbose_name="signature bloquée"
                    ),
                ),
                (
                    "echecs_connexion",
                    models.SmallIntegerField(
                        default=0, verbose_name="échecs de connexion"
                    ),
                ),
                (
                    "verrouille_jusqua",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="verrouillé jusqu'à"
                    ),
                ),
                (
                    "verrouillages_24h",
                    models.SmallIntegerField(
                        default=0, verbose_name="verrouillages sur 24 h"
                    ),
                ),
                (
                    "bloque_par_admin",
                    models.BooleanField(
                        default=False, verbose_name="bloqué (déblocage administrateur)"
                    ),
                ),
                (
                    "derniere_connexion",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="dernière connexion"
                    ),
                ),
                (
                    "mdp_modifie_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="mot de passe modifié le"
                    ),
                ),
                (
                    "active_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="activé le"
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créé le"),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(auto_now=True, verbose_name="modifié le"),
                ),
                (
                    "cree_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créé par",
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        help_text="Vide uniquement pour un super-administrateur FYXOP.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="utilisateurs",
                        to="tenancy.etablissement",
                        verbose_name="établissement",
                    ),
                ),
                (
                    "responsable",
                    models.ForeignKey(
                        blank=True,
                        help_text="Valide les absences (P5) ; même établissement.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="collaborateurs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="responsable hiérarchique",
                    ),
                ),
            ],
            options={
                "verbose_name": "utilisateur",
                "verbose_name_plural": "utilisateurs",
                "db_table": "utilisateur",
                "default_manager_name": "objects",
            },
        ),
        migrations.CreateModel(
            name="JetonUsageUnique",
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
                    "objet",
                    models.CharField(
                        choices=[
                            ("INVITATION", "Invitation"),
                            ("REINIT_MDP", "Réinitialisation du mot de passe"),
                            ("REENROLEMENT_MFA", "Réenrôlement MFA"),
                        ],
                        max_length=20,
                        verbose_name="objet",
                    ),
                ),
                (
                    "jeton_hash",
                    alpha.comptes.models.Empreinte64(
                        unique=True, verbose_name="empreinte SHA-256 du jeton"
                    ),
                ),
                (
                    "etape",
                    models.CharField(
                        choices=[
                            ("CREE", "Créé"),
                            ("MDP_OK", "Mot de passe défini"),
                            ("TOTP_EN_ATTENTE", "Authenticator en attente"),
                            ("TOTP_OK", "Authenticator confirmé"),
                        ],
                        default="CREE",
                        max_length=20,
                        verbose_name="étape",
                    ),
                ),
                ("expire_le", models.DateTimeField(verbose_name="expire le")),
                (
                    "utilise_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="utilisé le"
                    ),
                ),
                (
                    "annule_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="annulé le"
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créé le"),
                ),
                (
                    "cree_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créé par",
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
                        related_name="jetons",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "jeton à usage unique",
                "verbose_name_plural": "jetons à usage unique",
                "db_table": "jeton_usage_unique",
            },
        ),
        migrations.AddIndex(
            model_name="utilisateur",
            index=models.Index(
                fields=["etablissement", "statut"], name="utilisateur_etab_statut_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="utilisateur",
            index=models.Index(
                fields=["etablissement", "nom", "prenom"],
                name="utilisateur_etab_nom_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="utilisateur",
            index=models.Index(
                fields=["responsable"], name="utilisateur_responsable_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("est_super_admin", True), ("etablissement__isnull", True)
                    ),
                    models.Q(
                        ("est_super_admin", False), ("etablissement__isnull", False)
                    ),
                    _connector="OR",
                ),
                name="utilisateur_super_admin_sans_etab",
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("statut__in", ["INVITE", "ACTIF", "SUSPENDU", "DESACTIVE"])
                ),
                name="utilisateur_statut_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.CheckConstraint(
                condition=models.Q(("langue__in", ["fr", "en"])),
                name="utilisateur_langue_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("telephone_mobile__isnull", True),
                    ("telephone_mobile__regex", "^\\+[1-9][0-9]{6,14}$"),
                    _connector="OR",
                ),
                name="utilisateur_telephone_e164",
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("responsable__isnull", True),
                    models.Q(("responsable", models.F("id")), _negated=True),
                    _connector="OR",
                ),
                name="utilisateur_responsable_different",
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("echecs_connexion__gte", 0), ("verrouillages_24h__gte", 0)
                ),
                name="utilisateur_compteurs_positifs",
            ),
        ),
        migrations.AddConstraint(
            model_name="utilisateur",
            constraint=models.UniqueConstraint(
                fields=("id", "etablissement"), name="utilisateur_id_etab_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="jetonusageunique",
            index=models.Index(
                condition=models.Q(
                    ("annule_le__isnull", True), ("utilise_le__isnull", True)
                ),
                fields=["utilisateur", "objet"],
                name="jeton_en_cours_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="jetonusageunique",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("objet__in", ["INVITATION", "REINIT_MDP", "REENROLEMENT_MFA"])
                ),
                name="jeton_objet_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="jetonusageunique",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("etape__in", ["CREE", "MDP_OK", "TOTP_EN_ATTENTE", "TOTP_OK"])
                ),
                name="jeton_etape_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="jetonusageunique",
            constraint=models.CheckConstraint(
                condition=models.Q(("jeton_hash__regex", "^[0-9a-f]{64}$")),
                name="jeton_hash_format",
            ),
        ),
        sql.rls_utilisateur(),
        activer_rls("jeton_usage_unique", plateforme=True),
        cle_meme_etablissement("utilisateur", "responsable_id", "utilisateur"),
        cle_meme_etablissement("jeton_usage_unique", "utilisateur_id", "utilisateur"),
        sql.fonctions_resolution(),
    ]

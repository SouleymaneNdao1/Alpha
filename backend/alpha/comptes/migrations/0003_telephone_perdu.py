# Générée par Django 5.2.18 le 19/10/2026, complétée à la main (tâche B6).
#
# Table signalement_telephone_perdu (§ 2.2, § 4.5) : table d'établissement
# (etablissement_id NOT NULL). RLS activée et forcée dans la MÊME migration
# (§ 3.6), puis clé étrangère composite « même établissement » vers utilisateur
# pour l'intéressé. ``traite_par`` n'en a pas : il peut s'agir du super-admin
# FYXOP (décision P4), qui n'a pas d'établissement.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

from alpha.tenancy.coherence import cle_meme_etablissement
from alpha.tenancy.rls import activer_rls


class Migration(migrations.Migration):

    dependencies = [
        ("comptes", "0002_mfa_sessions"),
        ("tenancy", "0003_parametres_email_controle_interne"),
    ]

    operations = [
        migrations.CreateModel(
            name="SignalementTelephonePerdu",
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
                    "canal",
                    models.CharField(
                        choices=[
                            ("PAGE_PUBLIQUE", "Page publique"),
                            ("MON_COMPTE", "Mon compte"),
                            ("ADMIN", "Administration"),
                        ],
                        max_length=15,
                        verbose_name="canal",
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("OUVERT", "Ouvert"),
                            ("REINITIALISE", "Réinitialisé"),
                            ("ANNULE", "Annulé (téléphone retrouvé)"),
                        ],
                        default="OUVERT",
                        max_length=15,
                        verbose_name="statut",
                    ),
                ),
                ("signale_le", models.DateTimeField(verbose_name="signalé le")),
                (
                    "mode_verification",
                    models.CharField(
                        blank=True,
                        choices=[
                            (
                                "PRESENTIEL_PIECE",
                                "En présentiel, avec pièce d'identité",
                            ),
                            ("RAPPEL_TELEPHONIQUE", "Rappel au numéro connu"),
                            ("VISIO", "Appel vidéo"),
                            ("AUTRE", "Autre"),
                        ],
                        default="",
                        max_length=20,
                        verbose_name="mode de vérification d'identité",
                    ),
                ),
                (
                    "reference_demande",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=120,
                        verbose_name="référence de la demande écrite (P4)",
                    ),
                ),
                (
                    "commentaire",
                    models.TextField(
                        blank=True, default="", verbose_name="commentaire"
                    ),
                ),
                (
                    "traite_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="traité le"
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="tenancy.etablissement",
                    ),
                ),
                (
                    "traite_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="traité par",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="signalements_telephone",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "signalement de téléphone perdu",
                "verbose_name_plural": "signalements de téléphone perdu",
                "db_table": "signalement_telephone_perdu",
                "indexes": [
                    models.Index(
                        fields=["etablissement", "statut"],
                        name="signalement_etab_statut_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("statut__in", ["OUVERT", "REINITIALISE", "ANNULE"])
                        ),
                        name="signalement_statut_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("canal__in", ["PAGE_PUBLIQUE", "MON_COMPTE", "ADMIN"])
                        ),
                        name="signalement_canal_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("mode_verification", ""),
                            (
                                "mode_verification__in",
                                [
                                    "PRESENTIEL_PIECE",
                                    "RAPPEL_TELEPHONIQUE",
                                    "VISIO",
                                    "AUTRE",
                                ],
                            ),
                            _connector="OR",
                        ),
                        name="signalement_mode_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("traite_par__isnull", True),
                            models.Q(
                                ("traite_par", models.F("utilisateur")), _negated=True
                            ),
                            _connector="OR",
                        ),
                        name="signalement_pas_d_auto_traitement",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("statut", "OUVERT")),
                        fields=("utilisateur",),
                        name="signalement_un_seul_ouvert",
                    ),
                ],
            },
        ),
        activer_rls("signalement_telephone_perdu"),
        cle_meme_etablissement("signalement_telephone_perdu", "utilisateur_id", "utilisateur"),
    ]

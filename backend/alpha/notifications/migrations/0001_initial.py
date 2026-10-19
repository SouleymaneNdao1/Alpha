# Générée par Django 5.2.18 le 19/10/2026, complétée à la main (tâche B9).
#
# Tables preferences_notification et notification (§ 2.2). Ce sont des tables (*)
# du § 3.5 : RLS activée et forcée dans la MÊME migration avec la politique
# « tenant ou plateforme », puis clé étrangère composite « même établissement »
# vers utilisateur.

import datetime
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

from alpha.tenancy.coherence import cle_meme_etablissement
from alpha.tenancy.rls import activer_rls

TABLES = ("preferences_notification", "notification")


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("comptes", "0003_telephone_perdu"),
        ("tenancy", "0003_parametres_email_controle_interne"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PreferencesNotification",
            fields=[
                (
                    "utilisateur",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="preferences_notification",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
                ("email", models.BooleanField(default=True, verbose_name="e-mail")),
                (
                    "push",
                    models.BooleanField(
                        default=False,
                        help_text="Enregistré ; envoi au sprint 4.",
                        verbose_name="notification mobile",
                    ),
                ),
                (
                    "sms",
                    models.BooleanField(
                        default=False,
                        help_text="Enregistré ; envoi au sprint 4.",
                        verbose_name="SMS",
                    ),
                ),
                (
                    "resume_quotidien",
                    models.BooleanField(default=False, verbose_name="résumé quotidien"),
                ),
                (
                    "heure_resume",
                    models.TimeField(
                        default=datetime.time(7, 30), verbose_name="heure du résumé"
                    ),
                ),
                (
                    "par_evenement",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Réservé.",
                        verbose_name="surcharges par type d'événement",
                    ),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(auto_now=True, verbose_name="modifié le"),
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
            ],
            options={
                "verbose_name": "préférences de notification",
                "verbose_name_plural": "préférences de notification",
                "db_table": "preferences_notification",
            },
        ),
        migrations.CreateModel(
            name="Notification",
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
                ("type", models.CharField(max_length=40, verbose_name="type")),
                ("titre", models.CharField(max_length=200, verbose_name="titre")),
                (
                    "corps",
                    models.TextField(blank=True, default="", verbose_name="corps"),
                ),
                (
                    "lien",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=300,
                        verbose_name="lien (route du frontend)",
                    ),
                ),
                (
                    "lue_le",
                    models.DateTimeField(blank=True, null=True, verbose_name="lue le"),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créée le"),
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
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="destinataire",
                    ),
                ),
            ],
            options={
                "verbose_name": "notification",
                "verbose_name_plural": "notifications",
                "db_table": "notification",
                "indexes": [
                    models.Index(
                        models.F("utilisateur"),
                        models.F("lue_le"),
                        models.OrderBy(models.F("cree_le"), descending=True),
                        name="notification_util_lue_idx",
                    )
                ],
            },
        ),
        *[activer_rls(table, plateforme=True) for table in TABLES],
        *[cle_meme_etablissement(table, "utilisateur_id", "utilisateur") for table in TABLES],
    ]

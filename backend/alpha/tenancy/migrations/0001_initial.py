# Générée par Django 5.2.18 le 16/10/2026, complétée à la main (tâche B2).
#
# Ordre des opérations (architecture § 3.1, § 3.2, § 3.5) :
#   1. extensions, droits sur le schéma, DEFAULT PRIVILEGES, rattrapage des tables
#      techniques de Django déjà créées (correctif remonté en B1) ;
#   2. fonctions app_current_tenant(), app_scope(), app_current_user() ;
#   3. tables etablissement et parametres_etablissement ;
#   4. RLS de etablissement (politiques spécifiques) et de parametres_etablissement.
#
# Dépendances explicites sur contenttypes, auth et sessions : leurs tables sont
# ainsi TOUJOURS créées avant cette migration (ordre déterministe) et le
# rattrapage « GRANT … ON ALL TABLES » les couvre ; tout ce qui est créé ensuite
# l'est par les DEFAULT PRIVILEGES.

import django.contrib.postgres.fields
import django.db.models.deletion
import uuid
from django.db import migrations, models

from alpha.tenancy import rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        rls.droits_par_defaut(),
        rls.fonctions_contexte(),
        migrations.CreateModel(
            name="Etablissement",
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
                    "code",
                    models.CharField(max_length=40, unique=True, verbose_name="code"),
                ),
                (
                    "raison_sociale",
                    models.CharField(max_length=200, verbose_name="raison sociale"),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("BANQUE", "Banque"),
                            ("SFD", "Système financier décentralisé"),
                            ("PME", "PME"),
                        ],
                        max_length=10,
                        verbose_name="type",
                    ),
                ),
                (
                    "pays",
                    models.CharField(default="SN", max_length=2, verbose_name="pays"),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("ACTIF", "Actif"),
                            ("LECTURE_SEULE", "Lecture seule"),
                            ("SUSPENDU", "Suspendu"),
                            ("ARCHIVE", "Archivé"),
                        ],
                        default="ACTIF",
                        max_length=15,
                        verbose_name="statut",
                    ),
                ),
                (
                    "fuseau_horaire",
                    models.CharField(
                        default="Africa/Dakar",
                        max_length=40,
                        verbose_name="fuseau horaire",
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
            ],
            options={
                "verbose_name": "établissement",
                "verbose_name_plural": "établissements",
                "db_table": "etablissement",
            },
        ),
        migrations.CreateModel(
            name="ParametresEtablissement",
            fields=[
                (
                    "etablissement",
                    models.OneToOneField(
                        editable=False,
                        on_delete=django.db.models.deletion.RESTRICT,
                        primary_key=True,
                        related_name="parametres",
                        serialize=False,
                        to="tenancy.etablissement",
                    ),
                ),
                (
                    "inactivite_session_min",
                    models.SmallIntegerField(
                        default=15, verbose_name="inactivité de session (min)"
                    ),
                ),
                (
                    "duree_max_session_h",
                    models.SmallIntegerField(
                        default=12, verbose_name="durée maximale de session (h)"
                    ),
                ),
                (
                    "mdp_longueur_min",
                    models.SmallIntegerField(
                        default=12, verbose_name="longueur minimale du mot de passe"
                    ),
                ),
                (
                    "mdp_historique",
                    models.SmallIntegerField(
                        default=5,
                        verbose_name="nombre d'anciens mots de passe interdits",
                    ),
                ),
                (
                    "mdp_expiration_jours",
                    models.SmallIntegerField(
                        blank=True,
                        default=None,
                        help_text="Vide : pas d'expiration périodique (défaut, P3). Ex. 90 pour la banque pilote.",
                        null=True,
                        verbose_name="expiration du mot de passe (jours)",
                    ),
                ),
                (
                    "tentatives_max",
                    models.SmallIntegerField(
                        default=5, verbose_name="essais avant verrouillage"
                    ),
                ),
                (
                    "verrouillage_min",
                    models.SmallIntegerField(
                        default=15, verbose_name="durée du verrouillage (min)"
                    ),
                ),
                (
                    "verrouillages_max_24h",
                    models.SmallIntegerField(
                        default=3,
                        verbose_name="verrouillages en 24 h avant déblocage par un administrateur",
                    ),
                ),
                (
                    "validite_invitation_h",
                    models.SmallIntegerField(
                        default=72, verbose_name="validité de l'invitation (h)"
                    ),
                ),
                (
                    "validite_reinit_mdp_min",
                    models.SmallIntegerField(
                        default=30,
                        verbose_name="validité du lien de réinitialisation (min)",
                    ),
                ),
                (
                    "retention_audit_annees",
                    models.SmallIntegerField(
                        default=10,
                        verbose_name="durée de conservation du journal (années)",
                    ),
                ),
                (
                    "modules_actifs",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(),
                        blank=True,
                        default=list,
                        size=None,
                    ),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(auto_now=True, verbose_name="modifié le"),
                ),
            ],
            options={
                "verbose_name": "paramètres de l'établissement",
                "verbose_name_plural": "paramètres des établissements",
                "db_table": "parametres_etablissement",
            },
        ),
        migrations.AddConstraint(
            model_name="etablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("code__regex", "^[a-z0-9-]+$")),
                name="etablissement_code_format",
            ),
        ),
        migrations.AddConstraint(
            model_name="etablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("type__in", ["BANQUE", "SFD", "PME"])),
                name="etablissement_type_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="etablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("statut__in", ["ACTIF", "LECTURE_SEULE", "SUSPENDU", "ARCHIVE"])
                ),
                name="etablissement_statut_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="etablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("pays__regex", "^[A-Z]{2}$")),
                name="etablissement_pays_format",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("inactivite_session_min__gte", 5),
                    ("inactivite_session_min__lte", 60),
                ),
                name="parametres_inactivite_5_60",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("duree_max_session_h__gte", 1), ("duree_max_session_h__lte", 24)
                ),
                name="parametres_duree_session_1_24",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("mdp_longueur_min__gte", 12)),
                name="parametres_mdp_longueur_min_12",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("mdp_historique__gte", 0)),
                name="parametres_mdp_historique_positif",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("mdp_expiration_jours__isnull", True),
                    ("mdp_expiration_jours__gte", 1),
                    _connector="OR",
                ),
                name="parametres_mdp_expiration_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("tentatives_max__gte", 1)),
                name="parametres_tentatives_positif",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("verrouillage_min__gte", 1)),
                name="parametres_verrouillage_positif",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("verrouillages_max_24h__gte", 1)),
                name="parametres_verrouillages_24h_positif",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("validite_invitation_h__gte", 1)),
                name="parametres_invitation_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("validite_reinit_mdp_min__gte", 1)),
                name="parametres_reinit_mdp_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="parametresetablissement",
            constraint=models.CheckConstraint(
                condition=models.Q(("retention_audit_annees__gte", 1)),
                name="parametres_retention_positive",
            ),
        ),
        rls.rls_etablissement(),
        rls.activer_rls("parametres_etablissement"),
    ]

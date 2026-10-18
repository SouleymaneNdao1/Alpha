# Générée par Django 5.2.18 le 18/10/2026, complétée à la main (tâche B8).
#
# Tables tenant « absence » et « delegation » : RLS activée et forcée dans la MÊME
# migration (§ 3.6), puis clés étrangères composites « même établissement ».
# La contrainte d'exclusion utilise btree_gist (créée par tenancy.0001).

import alpha.delegations.models
import django.contrib.postgres.constraints
import django.db.models.deletion
import django.db.models.functions.comparison
import uuid
from django.conf import settings
from django.db import migrations, models

from alpha.tenancy.coherence import cle_meme_etablissement
from alpha.tenancy.rls import activer_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("organisation", "0001_initial"),
        ("tenancy", "0003_parametres_email_controle_interne"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Absence",
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
                ("debut", models.DateTimeField(verbose_name="début")),
                ("fin", models.DateTimeField(verbose_name="fin")),
                (
                    "motif",
                    models.CharField(
                        choices=[
                            ("CONGE", "Congé"),
                            ("MISSION", "Mission"),
                            ("FORMATION", "Formation"),
                            ("MALADIE", "Maladie"),
                            ("AUTRE", "Autre"),
                        ],
                        max_length=12,
                        verbose_name="motif",
                    ),
                ),
                (
                    "commentaire",
                    models.TextField(
                        blank=True, default="", verbose_name="commentaire"
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("SOUMISE", "Soumise"),
                            ("VALIDEE", "Validée"),
                            ("REFUSEE", "Refusée"),
                            ("ANNULEE", "Annulée"),
                        ],
                        default="SOUMISE",
                        max_length=10,
                        verbose_name="statut",
                    ),
                ),
                (
                    "decide_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="décidée le"
                    ),
                ),
                (
                    "motif_refus",
                    models.TextField(
                        blank=True, default="", verbose_name="motif du refus"
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créée le"),
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
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="absences",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur absent",
                    ),
                ),
                (
                    "valideur",
                    models.ForeignKey(
                        blank=True,
                        help_text="Fixé à la soumission (responsable, sinon un administrateur) ; remplacé par l'auteur effectif de la décision.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="absences_a_valider",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="valideur",
                    ),
                ),
            ],
            options={
                "verbose_name": "absence",
                "verbose_name_plural": "absences",
                "db_table": "absence",
                "ordering": ["-debut"],
            },
        ),
        migrations.CreateModel(
            name="Delegation",
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
                    "origine",
                    models.CharField(
                        choices=[
                            ("ABSENCE", "Absence"),
                            ("POUVOIR", "Délégation de pouvoir"),
                        ],
                        default="ABSENCE",
                        max_length=10,
                        verbose_name="origine",
                    ),
                ),
                ("debut", models.DateTimeField(verbose_name="début")),
                ("fin", models.DateTimeField(verbose_name="fin")),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("EN_ATTENTE", "En attente"),
                            ("ACTIVE", "Active"),
                            ("TERMINEE", "Terminée"),
                            ("ANNULEE", "Annulée"),
                            ("REFUSEE", "Refusée"),
                        ],
                        default="EN_ATTENTE",
                        max_length=12,
                        verbose_name="statut",
                    ),
                ),
                (
                    "portee",
                    models.JSONField(blank=True, default=dict, verbose_name="portée"),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créée le"),
                ),
                (
                    "activee_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="entrée en vigueur le"
                    ),
                ),
                (
                    "terminee_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="terminée le"
                    ),
                ),
                (
                    "absence",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="delegations",
                        to="delegations.absence",
                        verbose_name="absence",
                    ),
                ),
                (
                    "delegant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="delegations_donnees",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="délégant",
                    ),
                ),
                (
                    "delegataire",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="delegations_recues",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="délégataire",
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
                    "role",
                    models.ForeignKey(
                        blank=True,
                        help_text="Vide : tous les rôles du délégant.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="organisation.role",
                        verbose_name="rôle délégué",
                    ),
                ),
            ],
            options={
                "verbose_name": "délégation",
                "verbose_name_plural": "délégations",
                "db_table": "delegation",
            },
        ),
        migrations.AddIndex(
            model_name="absence",
            index=models.Index(
                fields=["etablissement", "utilisateur", "debut"],
                name="absence_etab_util_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="absence",
            index=models.Index(
                condition=models.Q(("statut", "SOUMISE")),
                fields=["valideur"],
                name="absence_a_valider_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="absence",
            constraint=models.CheckConstraint(
                condition=models.Q(("fin__gt", models.F("debut"))),
                name="absence_fin_apres_debut",
            ),
        ),
        migrations.AddConstraint(
            model_name="absence",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("motif__in", ["CONGE", "MISSION", "FORMATION", "MALADIE", "AUTRE"])
                ),
                name="absence_motif_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="absence",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("statut__in", ["SOUMISE", "VALIDEE", "REFUSEE", "ANNULEE"])
                ),
                name="absence_statut_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="absence",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("valideur__isnull", True),
                    models.Q(("valideur", models.F("utilisateur")), _negated=True),
                    _connector="OR",
                ),
                name="absence_valideur_different",
            ),
        ),
        migrations.AddConstraint(
            model_name="absence",
            constraint=models.UniqueConstraint(
                fields=("id", "etablissement"), name="absence_id_etab_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="delegation",
            index=models.Index(
                condition=models.Q(("statut", "ACTIVE")),
                fields=["delegataire", "debut", "fin"],
                name="delegation_recue_active_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="delegation",
            index=models.Index(
                fields=["delegant", "statut"], name="delegation_delegant_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="delegation",
            constraint=models.CheckConstraint(
                condition=models.Q(("fin__gt", models.F("debut"))),
                name="delegation_fin_apres_debut",
            ),
        ),
        migrations.AddConstraint(
            model_name="delegation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("delegataire", models.F("delegant")), _negated=True
                ),
                name="delegation_delegataire_different",
            ),
        ),
        migrations.AddConstraint(
            model_name="delegation",
            constraint=models.CheckConstraint(
                condition=models.Q(("origine__in", ["ABSENCE", "POUVOIR"])),
                name="delegation_origine_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="delegation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "statut__in",
                        ["EN_ATTENTE", "ACTIVE", "TERMINEE", "ANNULEE", "REFUSEE"],
                    )
                ),
                name="delegation_statut_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="delegation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("origine", "ABSENCE"), _negated=True),
                    ("absence__isnull", False),
                    _connector="OR",
                ),
                name="delegation_absence_obligatoire",
            ),
        ),
        migrations.AddConstraint(
            model_name="delegation",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("statut__in", ("EN_ATTENTE", "ACTIVE"))),
                expressions=[
                    (models.F("delegant"), "="),
                    (
                        django.db.models.functions.comparison.Coalesce(
                            models.F("role"),
                            models.Value(
                                uuid.UUID("00000000-0000-0000-0000-000000000000")
                            ),
                        ),
                        "=",
                    ),
                    (
                        alpha.delegations.models.TsTzRange(
                            models.F("debut"), models.F("fin")
                        ),
                        "&&",
                    ),
                ],
                name="delegation_sans_chevauchement",
            ),
        ),
        activer_rls("absence"),
        activer_rls("delegation"),
        cle_meme_etablissement("absence", "utilisateur_id", "utilisateur"),
        cle_meme_etablissement("absence", "valideur_id", "utilisateur"),
        cle_meme_etablissement("delegation", "absence_id", "absence"),
        cle_meme_etablissement("delegation", "delegant_id", "utilisateur"),
        cle_meme_etablissement("delegation", "delegataire_id", "utilisateur"),
        cle_meme_etablissement("delegation", "role_id", "role"),
    ]

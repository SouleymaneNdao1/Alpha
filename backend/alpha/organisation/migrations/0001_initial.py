# Générée par Django 5.2.18 le 16/10/2026, complétée à la main (tâche B3).
#
# Tables tenant unite_organisationnelle, role, affectation_role : RLS activée
# et forcée dans la MÊME migration (§ 3.6), puis clés étrangères composites
# « même établissement » (alpha.tenancy.coherence) : une affectation ou une
# unité ne peut pas viser l'utilisateur, le rôle ou l'unité d'un autre établissement.

import alpha.organisation.codes_permission
import django.contrib.postgres.fields
import django.contrib.postgres.indexes
import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models

from alpha.tenancy.coherence import cle_meme_etablissement
from alpha.tenancy.rls import activer_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenancy", "0002_etablissement_cree_par"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Role",
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
                ("code", models.CharField(max_length=50, verbose_name="code")),
                ("libelle", models.CharField(max_length=100, verbose_name="libellé")),
                (
                    "description",
                    models.TextField(
                        blank=True, default="", verbose_name="description"
                    ),
                ),
                (
                    "permissions",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            choices=[
                                (
                                    "admin.utilisateurs",
                                    "Inviter, modifier, suspendre, déverrouiller les utilisateurs ; traiter « téléphone perdu »",
                                ),
                                (
                                    "admin.roles",
                                    "Gérer le catalogue des rôles et les habilitations",
                                ),
                                (
                                    "admin.organisation",
                                    "Gérer les unités et périmètres",
                                ),
                                (
                                    "admin.securite",
                                    "Régler les paramètres de sécurité de l'établissement",
                                ),
                                (
                                    "admin.absences",
                                    "Voir et valider toute absence (à défaut de responsable)",
                                ),
                                ("audit.lecture", "Consulter le journal d'audit"),
                                ("audit.export", "Exporter le journal d'audit (Excel)"),
                            ],
                            max_length=50,
                        ),
                        blank=True,
                        default=list,
                        size=None,
                        validators=[alpha.organisation.codes_permission.valider_codes],
                        verbose_name="permissions",
                    ),
                ),
                (
                    "est_systeme",
                    models.BooleanField(
                        default=False,
                        help_text="Non supprimable ; ses permissions ne peuvent pas être retirées.",
                        verbose_name="rôle système",
                    ),
                ),
                ("actif", models.BooleanField(default=True, verbose_name="actif")),
                (
                    "ordre",
                    models.SmallIntegerField(
                        default=0, verbose_name="ordre d'affichage"
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
                    "etablissement",
                    models.ForeignKey(
                        editable=False,
                        on_delete=django.db.models.deletion.RESTRICT,
                        to="tenancy.etablissement",
                    ),
                ),
            ],
            options={
                "verbose_name": "rôle",
                "verbose_name_plural": "rôles",
                "db_table": "role",
                "ordering": ["ordre", "libelle"],
            },
        ),
        migrations.CreateModel(
            name="UniteOrganisationnelle",
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
                    "type",
                    models.CharField(
                        choices=[
                            ("DIRECTION", "Direction"),
                            ("SERVICE", "Service"),
                            ("AGENCE", "Agence"),
                            ("COMITE", "Comité"),
                        ],
                        max_length=12,
                        verbose_name="type",
                    ),
                ),
                ("code", models.CharField(max_length=40, verbose_name="code")),
                ("libelle", models.CharField(max_length=150, verbose_name="libellé")),
                ("actif", models.BooleanField(default=True, verbose_name="active")),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créée le"),
                ),
                (
                    "modifie_le",
                    models.DateTimeField(auto_now=True, verbose_name="modifiée le"),
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
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="enfants",
                        to="organisation.uniteorganisationnelle",
                        verbose_name="unité parente",
                    ),
                ),
            ],
            options={
                "verbose_name": "unité organisationnelle",
                "verbose_name_plural": "unités organisationnelles",
                "db_table": "unite_organisationnelle",
            },
        ),
        migrations.CreateModel(
            name="AffectationRole",
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
                    "principal",
                    models.BooleanField(default=False, verbose_name="rôle principal"),
                ),
                (
                    "debut",
                    models.DateField(
                        default=django.utils.timezone.localdate, verbose_name="début"
                    ),
                ),
                (
                    "fin",
                    models.DateField(
                        blank=True,
                        help_text="Vide : en cours.",
                        null=True,
                        verbose_name="fin",
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créée le"),
                ),
                (
                    "cree_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="créée par",
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
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="affectations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="affectations",
                        to="organisation.role",
                        verbose_name="rôle",
                    ),
                ),
                (
                    "unite",
                    models.ForeignKey(
                        blank=True,
                        help_text="Vide : tout l'établissement.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="affectations",
                        to="organisation.uniteorganisationnelle",
                        verbose_name="unité",
                    ),
                ),
            ],
            options={
                "verbose_name": "affectation de rôle",
                "verbose_name_plural": "affectations de rôles",
                "db_table": "affectation_role",
            },
        ),
        migrations.AddIndex(
            model_name="role",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["permissions"], name="role_permissions_gin"
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.UniqueConstraint(
                fields=("etablissement", "code"), name="role_code_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.UniqueConstraint(
                models.F("etablissement"),
                django.db.models.functions.text.Lower("libelle"),
                name="role_libelle_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.UniqueConstraint(
                fields=("id", "etablissement"), name="role_id_etab_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.CheckConstraint(
                condition=models.Q(("code__regex", "^[a-z0-9]+(-[a-z0-9]+)*$")),
                name="role_code_format",
            ),
        ),
        migrations.AddConstraint(
            model_name="role",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "permissions__contained_by",
                        [
                            "admin.utilisateurs",
                            "admin.roles",
                            "admin.organisation",
                            "admin.securite",
                            "admin.absences",
                            "audit.lecture",
                            "audit.export",
                        ],
                    )
                ),
                name="role_permissions_connues",
            ),
        ),
        migrations.AddIndex(
            model_name="uniteorganisationnelle",
            index=models.Index(
                fields=["etablissement", "parent"], name="unite_etab_parent_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="uniteorganisationnelle",
            constraint=models.UniqueConstraint(
                fields=("etablissement", "code"), name="unite_code_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="uniteorganisationnelle",
            constraint=models.UniqueConstraint(
                fields=("id", "etablissement"), name="unite_id_etab_uniq"
            ),
        ),
        migrations.AddConstraint(
            model_name="uniteorganisationnelle",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("type__in", ["DIRECTION", "SERVICE", "AGENCE", "COMITE"])
                ),
                name="unite_type_valide",
            ),
        ),
        migrations.AddConstraint(
            model_name="uniteorganisationnelle",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("parent__isnull", True),
                    models.Q(("parent", models.F("id")), _negated=True),
                    _connector="OR",
                ),
                name="unite_parent_different",
            ),
        ),
        migrations.AddIndex(
            model_name="affectationrole",
            index=models.Index(
                condition=models.Q(("fin__isnull", True)),
                fields=["etablissement", "role"],
                name="affectation_titulaires_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="affectationrole",
            index=models.Index(
                fields=["utilisateur", "fin"], name="affectation_utilisateur_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="affectationrole",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fin__isnull", True), ("principal", True)),
                fields=("utilisateur",),
                name="affectation_principale_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="affectationrole",
            constraint=models.UniqueConstraint(
                condition=models.Q(("fin__isnull", True)),
                fields=("utilisateur", "role", "unite"),
                name="affectation_en_cours_unique",
                nulls_distinct=False,
            ),
        ),
        migrations.AddConstraint(
            model_name="affectationrole",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("fin__isnull", True),
                    ("fin__gte", models.F("debut")),
                    _connector="OR",
                ),
                name="affectation_fin_apres_debut",
            ),
        ),
        activer_rls("unite_organisationnelle"),
        activer_rls("role"),
        activer_rls("affectation_role"),
        cle_meme_etablissement("unite_organisationnelle", "parent_id", "unite_organisationnelle"),
        cle_meme_etablissement("affectation_role", "utilisateur_id", "utilisateur"),
        cle_meme_etablissement("affectation_role", "role_id", "role"),
        cle_meme_etablissement("affectation_role", "unite_id", "unite_organisationnelle"),
    ]

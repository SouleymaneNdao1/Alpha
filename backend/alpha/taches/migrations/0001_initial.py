# Générée par Django 5.2.18 le 18/10/2026, complétée à la main (tâche B8).
#
# Table tenant « tache » : RLS activée et forcée dans la MÊME migration (§ 3.6),
# puis clés étrangères composites « même établissement » (alpha.tenancy.coherence).

import django.db.models.deletion
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
            name="Tache",
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
                    "module",
                    models.CharField(
                        choices=[
                            ("COMPTE", "Mon compte"),
                            ("ADMINISTRATION", "Administration"),
                            ("CREDIT", "Crédit"),
                            ("INTERNE", "Décisions internes"),
                            ("RH", "Ressources humaines"),
                            ("TRESORERIE", "Trésorerie"),
                            ("CONTRATS", "Contrats"),
                            ("GOUVERNANCE", "Gouvernance"),
                            ("FISCAL", "Fiscalité"),
                            ("PME_FOURNISSEURS", "Fournisseurs"),
                            ("PME_BUDGET", "Budget"),
                            ("PME_COMMERCIAL", "Commercial"),
                        ],
                        max_length=20,
                        verbose_name="module",
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        help_text="« app.modele », ex. delegations.absence ; S2 : workflow.instance_etape.",
                        max_length=60,
                        verbose_name="type de l'objet source",
                    ),
                ),
                (
                    "source_id",
                    models.UUIDField(verbose_name="identifiant de l'objet source"),
                ),
                (
                    "reference",
                    models.CharField(
                        blank=True, default="", max_length=40, verbose_name="référence"
                    ),
                ),
                ("titre", models.CharField(max_length=200, verbose_name="titre")),
                (
                    "sous_titre",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=300,
                        verbose_name="sous-titre",
                    ),
                ),
                (
                    "montant",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=18,
                        null=True,
                        verbose_name="montant",
                    ),
                ),
                (
                    "devise",
                    models.CharField(
                        default="XOF", max_length=3, verbose_name="devise"
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("DECIDER", "Décider"),
                            ("SIGNER", "Signer"),
                            ("VALIDER", "Valider"),
                            ("COMPLETER", "Compléter"),
                            ("TRAITER", "Traiter"),
                        ],
                        max_length=12,
                        verbose_name="action",
                    ),
                ),
                (
                    "type_echeance",
                    models.CharField(
                        choices=[
                            ("AVANT", "Avant le"),
                            ("ECHEANCE", "Échéance le"),
                            ("EXECUTION", "Exécution le"),
                            ("PREAVIS", "Préavis avant le"),
                        ],
                        default="AVANT",
                        max_length=12,
                        verbose_name="type d'échéance",
                    ),
                ),
                (
                    "echeance",
                    models.DateTimeField(
                        blank=True,
                        help_text="Vide : plus tard.",
                        null=True,
                        verbose_name="échéance",
                    ),
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
                    "statut",
                    models.CharField(
                        choices=[
                            ("OUVERTE", "Ouverte"),
                            ("TERMINEE", "Terminée"),
                            ("ANNULEE", "Annulée"),
                        ],
                        default="OUVERTE",
                        max_length=10,
                        verbose_name="statut",
                    ),
                ),
                (
                    "resultat",
                    models.CharField(
                        blank=True, default="", max_length=30, verbose_name="résultat"
                    ),
                ),
                (
                    "cree_le",
                    models.DateTimeField(auto_now_add=True, verbose_name="créée le"),
                ),
                (
                    "terminee_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="fermée le"
                    ),
                ),
                (
                    "assigne_role",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="taches",
                        to="organisation.role",
                        verbose_name="assignée au rôle",
                    ),
                ),
                (
                    "assigne_unite",
                    models.ForeignKey(
                        blank=True,
                        help_text="Avec un rôle : titulaires du rôle sur cette unité ou une unité parente.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="taches",
                        to="organisation.uniteorganisationnelle",
                        verbose_name="périmètre (unité)",
                    ),
                ),
                (
                    "assigne_utilisateur",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="taches_assignees",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="assignée à l'utilisateur",
                    ),
                ),
                (
                    "demandeur",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="demandeur",
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
                    "pour_compte_de",
                    models.ForeignKey(
                        blank=True,
                        help_text="Délégant, si l'action a été faite par délégation.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="pour le compte de",
                    ),
                ),
                (
                    "terminee_par",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="fermée par",
                    ),
                ),
            ],
            options={
                "verbose_name": "tâche",
                "verbose_name_plural": "tâches",
                "db_table": "tache",
                "indexes": [
                    models.Index(
                        fields=["etablissement", "statut", "echeance"],
                        name="tache_etab_statut_idx",
                    ),
                    models.Index(
                        condition=models.Q(("statut", "OUVERTE")),
                        fields=["assigne_utilisateur"],
                        name="tache_ouverte_utilisateur_idx",
                    ),
                    models.Index(
                        condition=models.Q(("statut", "OUVERTE")),
                        fields=["assigne_role", "assigne_unite"],
                        name="tache_ouverte_role_idx",
                    ),
                    models.Index(
                        fields=["source_type", "source_id"], name="tache_source_idx"
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("assigne_utilisateur__isnull", False),
                            ("assigne_role__isnull", False),
                            _connector="OR",
                        ),
                        name="tache_destinataire_obligatoire",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("assigne_unite__isnull", True),
                            ("assigne_role__isnull", False),
                            _connector="OR",
                        ),
                        name="tache_unite_avec_role",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "module__in",
                                [
                                    "COMPTE",
                                    "ADMINISTRATION",
                                    "CREDIT",
                                    "INTERNE",
                                    "RH",
                                    "TRESORERIE",
                                    "CONTRATS",
                                    "GOUVERNANCE",
                                    "FISCAL",
                                    "PME_FOURNISSEURS",
                                    "PME_BUDGET",
                                    "PME_COMMERCIAL",
                                ],
                            )
                        ),
                        name="tache_module_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "action__in",
                                [
                                    "DECIDER",
                                    "SIGNER",
                                    "VALIDER",
                                    "COMPLETER",
                                    "TRAITER",
                                ],
                            )
                        ),
                        name="tache_action_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "type_echeance__in",
                                ["AVANT", "ECHEANCE", "EXECUTION", "PREAVIS"],
                            )
                        ),
                        name="tache_type_echeance_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("statut__in", ["OUVERTE", "TERMINEE", "ANNULEE"])
                        ),
                        name="tache_statut_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("statut", "OUVERTE"), ("terminee_le__isnull", True)
                            ),
                            models.Q(
                                models.Q(("statut", "OUVERTE"), _negated=True),
                                ("terminee_le__isnull", False),
                            ),
                            _connector="OR",
                        ),
                        name="tache_fermeture_datee",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("montant__isnull", True),
                            ("montant__gte", 0),
                            _connector="OR",
                        ),
                        name="tache_montant_positif",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("statut", "OUVERTE")),
                        fields=("etablissement", "source_type", "source_id", "action"),
                        name="tache_ouverte_unique",
                    ),
                ],
            },
        ),
        activer_rls("tache"),
        cle_meme_etablissement("tache", "assigne_utilisateur_id", "utilisateur"),
        cle_meme_etablissement("tache", "assigne_role_id", "role"),
        cle_meme_etablissement("tache", "assigne_unite_id", "unite_organisationnelle"),
        cle_meme_etablissement("tache", "demandeur_id", "utilisateur"),
        cle_meme_etablissement("tache", "terminee_par_id", "utilisateur"),
        cle_meme_etablissement("tache", "pour_compte_de_id", "utilisateur"),
    ]

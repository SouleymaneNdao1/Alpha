# Générée par Django 5.2.18 le 16/10/2026, complétée à la main (tâche B4).
#
# Ordre des opérations (architecture § 2.2, § 6.3) :
#   1. tables controle_integrite_audit et evenement_audit (contraintes, index) ;
#   2. evenement_audit.id en GENERATED ALWAYS AS IDENTITY ;
#   3. trigger de chaînage (audit_chainer, SECURITY DEFINER, verrou par chaîne) ;
#   4. triggers d'immutabilité (UPDATE, DELETE, TRUNCATE) et REVOKE ;
#   5. RLS des deux tables, dans la MÊME migration que leur création (§ 3.6).
# Toutes les opérations SQL sont réversibles (migrate audit zero).

import alpha.audit.models
import django.db.models.deletion
import django.db.models.functions.comparison
import uuid
from django.db import migrations, models

from alpha.audit import sql


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ControleIntegriteAudit",
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
                ("lance_le", models.DateTimeField(verbose_name="lancé le")),
                (
                    "termine_le",
                    models.DateTimeField(
                        blank=True, null=True, verbose_name="terminé le"
                    ),
                ),
                (
                    "declencheur",
                    models.CharField(
                        choices=[("PLANIFIE", "Planifié"), ("MANUEL", "Manuel")],
                        max_length=10,
                        verbose_name="déclencheur",
                    ),
                ),
                (
                    "statut",
                    models.CharField(
                        choices=[
                            ("EN_COURS", "En cours"),
                            ("INTACTE", "Intacte"),
                            ("ROMPUE", "Rompue"),
                            ("ERREUR", "Erreur"),
                        ],
                        default="EN_COURS",
                        max_length=10,
                        verbose_name="statut",
                    ),
                ),
                (
                    "nb_evenements",
                    models.BigIntegerField(
                        default=0, verbose_name="événements vérifiés"
                    ),
                ),
                (
                    "dernier_seq",
                    models.BigIntegerField(
                        blank=True, null=True, verbose_name="dernier rang"
                    ),
                ),
                (
                    "dernier_hash",
                    alpha.audit.models.CharFixe(
                        blank=True,
                        max_length=64,
                        null=True,
                        verbose_name="dernière empreinte",
                    ),
                ),
                (
                    "premier_seq_invalide",
                    models.BigIntegerField(
                        blank=True, null=True, verbose_name="premier rang invalide"
                    ),
                ),
                (
                    "message",
                    models.TextField(blank=True, default="", verbose_name="message"),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        help_text="NULL : chaîne de la plateforme.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="tenancy.etablissement",
                    ),
                ),
            ],
            options={
                "verbose_name": "contrôle d'intégrité du journal",
                "verbose_name_plural": "contrôles d'intégrité du journal",
                "db_table": "controle_integrite_audit",
                "indexes": [
                    models.Index(
                        fields=["etablissement", "-lance_le"],
                        name="ctrl_audit_etab_lance_idx",
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("declencheur__in", ["PLANIFIE", "MANUEL"])),
                        name="controle_audit_declencheur_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("statut__in", ["EN_COURS", "INTACTE", "ROMPUE", "ERREUR"])
                        ),
                        name="controle_audit_statut_valide",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EvenementAudit",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "seq",
                    models.BigIntegerField(
                        editable=False, verbose_name="rang dans la chaîne"
                    ),
                ),
                (
                    "horodatage",
                    models.DateTimeField(editable=False, verbose_name="horodatage"),
                ),
                (
                    "acteur_type",
                    models.CharField(
                        choices=[
                            ("UTILISATEUR", "Utilisateur"),
                            ("SUPER_ADMIN", "Super-administrateur FYXOP"),
                            ("SYSTEME", "Système"),
                            ("API", "API"),
                            ("IA", "IA"),
                            ("ANONYME", "Anonyme"),
                        ],
                        max_length=12,
                        verbose_name="type d'acteur",
                    ),
                ),
                (
                    "acteur_id",
                    models.UUIDField(
                        blank=True, null=True, verbose_name="identifiant de l'acteur"
                    ),
                ),
                (
                    "acteur_libelle",
                    models.CharField(max_length=150, verbose_name="acteur"),
                ),
                (
                    "categorie",
                    models.CharField(
                        choices=[
                            ("CONNEXION", "Connexion"),
                            ("DECISION", "Décision"),
                            ("MODIFICATION", "Modification"),
                            ("PARAMETRAGE", "Paramétrage"),
                            ("ACCES_API", "Accès API"),
                            ("SUPER_ADMIN", "Super-administration"),
                            ("SECURITE", "Sécurité"),
                            ("DOCUMENT", "Document"),
                            ("ENVOI_EXTERNE", "Envoi externe"),
                            ("IA", "IA"),
                        ],
                        max_length=15,
                        verbose_name="catégorie",
                    ),
                ),
                ("action", models.CharField(max_length=60, verbose_name="action")),
                (
                    "objet_type",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=60,
                        verbose_name="type d'objet",
                    ),
                ),
                (
                    "objet_id",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=64,
                        verbose_name="identifiant de l'objet",
                    ),
                ),
                (
                    "objet_libelle",
                    models.CharField(
                        blank=True, default="", max_length=200, verbose_name="objet"
                    ),
                ),
                (
                    "avant",
                    models.JSONField(blank=True, null=True, verbose_name="avant"),
                ),
                (
                    "apres",
                    models.JSONField(blank=True, null=True, verbose_name="après"),
                ),
                (
                    "detail",
                    models.TextField(blank=True, default="", verbose_name="détail"),
                ),
                (
                    "ip",
                    models.GenericIPAddressField(
                        blank=True, null=True, verbose_name="adresse IP"
                    ),
                ),
                (
                    "user_agent",
                    models.CharField(
                        blank=True,
                        default="",
                        max_length=300,
                        verbose_name="user agent",
                    ),
                ),
                (
                    "request_id",
                    models.UUIDField(
                        blank=True, null=True, verbose_name="identifiant de requête"
                    ),
                ),
                (
                    "payload_canonique",
                    models.TextField(editable=False, verbose_name="payload canonique"),
                ),
                (
                    "hash_precedent",
                    alpha.audit.models.CharFixe(
                        editable=False,
                        max_length=64,
                        verbose_name="empreinte précédente",
                    ),
                ),
                (
                    "hash",
                    alpha.audit.models.CharFixe(
                        editable=False, max_length=64, verbose_name="empreinte"
                    ),
                ),
                (
                    "etablissement",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        help_text="NULL : chaîne de la plateforme.",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="+",
                        to="tenancy.etablissement",
                    ),
                ),
            ],
            options={
                "verbose_name": "événement d'audit",
                "verbose_name_plural": "événements d'audit",
                "db_table": "evenement_audit",
                "indexes": [
                    models.Index(
                        fields=["etablissement", "-horodatage"],
                        name="evt_audit_etab_horo_idx",
                    ),
                    models.Index(
                        fields=["etablissement", "categorie", "-horodatage"],
                        name="evt_audit_etab_cat_horo_idx",
                    ),
                    models.Index(
                        fields=["etablissement", "acteur_id", "-horodatage"],
                        name="evt_audit_etab_acteur_idx",
                    ),
                    models.Index(
                        fields=["etablissement", "objet_type", "objet_id"],
                        name="evt_audit_etab_objet_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.comparison.Coalesce(
                            "etablissement",
                            models.Value(
                                uuid.UUID("00000000-0000-0000-0000-000000000000"),
                                output_field=models.UUIDField(),
                            ),
                        ),
                        models.F("seq"),
                        name="evenement_audit_chaine_seq_uniq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "acteur_type__in",
                                [
                                    "UTILISATEUR",
                                    "SUPER_ADMIN",
                                    "SYSTEME",
                                    "API",
                                    "IA",
                                    "ANONYME",
                                ],
                            )
                        ),
                        name="evenement_audit_acteur_type_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "categorie__in",
                                [
                                    "CONNEXION",
                                    "DECISION",
                                    "MODIFICATION",
                                    "PARAMETRAGE",
                                    "ACCES_API",
                                    "SUPER_ADMIN",
                                    "SECURITE",
                                    "DOCUMENT",
                                    "ENVOI_EXTERNE",
                                    "IA",
                                ],
                            )
                        ),
                        name="evenement_audit_categorie_valide",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("seq__gte", 1)),
                        name="evenement_audit_seq_positif",
                    ),
                ],
            },
        ),
        sql.identite_toujours(),
        sql.chainage(),
        sql.immutabilite(),
        sql.rls_evenement_audit(),
        sql.rls_controle_integrite(),
    ]


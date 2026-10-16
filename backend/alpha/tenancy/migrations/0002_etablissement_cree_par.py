# Générée par Django 5.2.18 le 16/10/2026 (tâche B3).
#
# etablissement.cree_par (§ 2.2) : super-administrateur FYXOP qui a provisionné
# l'établissement. Migration séparée de tenancy.0001 car utilisateur (comptes.0001)
# dépend lui-même d'etablissement.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="etablissement",
            name="cree_par",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.RESTRICT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="créé par",
            ),
        ),
    ]

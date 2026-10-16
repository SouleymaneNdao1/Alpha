# Générée par Django 5.2.18 le 16/10/2026 ; RLS ajoutée dans la même migration (§ 3.6).

import django.db.models.deletion
import uuid
from django.db import migrations, models

from alpha.tenancy.rls import activer_rls


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenancy", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NoteTest",
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
                ("texte", models.CharField(max_length=100)),
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
                "db_table": "note_test",
            },
        ),
        activer_rls("note_test"),
    ]

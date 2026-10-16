# Tâche B4 : destinataire « contrôle interne » de l'ancrage quotidien du journal
# d'audit (décision P7 du 15/10/2026, architecture § 10).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0002_etablissement_cree_par"),
    ]

    operations = [
        migrations.AddField(
            model_name="parametresetablissement",
            name="email_controle_interne",
            field=models.EmailField(
                blank=True,
                default="",
                help_text="Reçoit chaque jour la dernière empreinte de la chaîne d'audit. "
                "Vide : l'ancre n'est envoyée qu'à FYXOP.",
                max_length=254,
                verbose_name="adresse du contrôle interne (ancrage du journal d'audit)",
            ),
        ),
    ]

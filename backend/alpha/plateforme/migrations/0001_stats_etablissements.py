# Écrite à la main (tâche B10).
#
# Fonction SECURITY DEFINER alpha_stats_etablissements (§ 3.5, § 3.8) : statistiques
# agrégées de la console FYXOP, sans contenu. Aucune table : l'application « plateforme »
# ne possède pas de données propres (elle écrit dans etablissement, les tables tenant
# sous contexte_tenant et le journal d'audit). Réversible (migrate plateforme zero).

from django.db import migrations

from alpha.plateforme.sql import stats_etablissements


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0003_parametres_email_controle_interne"),
        ("comptes", "0003_telephone_perdu"),
        ("audit", "0001_initial"),
    ]

    operations = [stats_etablissements()]

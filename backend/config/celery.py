"""Application Celery d'ALPHA (architecture § 3.7, § 6.5).

Commandes (docker-compose.yml) :
    celery -A config worker -Q defaut,celery -c 2 -l info
    celery -A config beat -l info -s /tmp/celerybeat-schedule

Les réglages sont lus dans les settings Django, préfixe CELERY_ (files, fuseau
horaire, planification CELERY_BEAT_SCHEDULE). Les tâches sont découvertes dans
le module ``tasks`` de chaque application installée.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("alpha")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

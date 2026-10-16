"""Point d'entrée ASGI (non utilisé au sprint 1 : gunicorn sert l'application en WSGI)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

application = get_asgi_application()

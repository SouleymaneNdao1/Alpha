"""Projet Django ALPHA.

L'application Celery est chargée avec Django pour que ``@shared_task`` l'utilise.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)

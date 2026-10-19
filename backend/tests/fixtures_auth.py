"""Fixtures des tests d'authentification (tâche B5).

Chargées par ``pytest_plugins = ["tests.fixtures_auth"]`` dans les modules de test
B5 (pas de modification de ``tests/conftest.py``) :

- ``client_csrf`` : client de test qui APPLIQUE le contrôle CSRF ;
- ``vider_limites`` (autouse) : remet à zéro les compteurs de débit et le cache
  des sessions d'appareil (clés ``limite:*`` et ``sessapp:*`` uniquement).
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client

from tests.outils_auth import UA_CHROME_WIN


@pytest.fixture
def client_csrf() -> Client:
    return Client(enforce_csrf_checks=True, HTTP_USER_AGENT=UA_CHROME_WIN)


@pytest.fixture(autouse=True)
def vider_limites():
    """Compteurs de débit et cache des sessions : remis à zéro (clés B5 uniquement)."""
    cache.delete_pattern("limite:*")
    cache.delete_pattern("sessapp:*")
    yield
    cache.delete_pattern("limite:*")
    cache.delete_pattern("sessapp:*")

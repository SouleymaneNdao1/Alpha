"""Permissions de base de l'API.

Politique « fermé par défaut » : ``RefuserTout`` est la permission par défaut de
DRF. Chaque vue DOIT déclarer explicitement ses ``permission_classes``
(Anonyme, Session, Perm(x), StepUp, SuperAdmin : § 5 et tâches B5 à B10) ;
une vue qui l'oublie est inaccessible au lieu d'être ouverte.
"""

from rest_framework.permissions import BasePermission


class RefuserTout(BasePermission):
    """Refuse toute requête : 401 si non authentifié, 403 sinon."""

    message = "Accès refusé."

    def has_permission(self, request, view) -> bool:
        return False

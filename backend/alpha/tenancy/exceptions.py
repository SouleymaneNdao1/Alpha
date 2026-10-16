"""Erreurs de l'isolation multi-tenant (architecture § 3.4).

Ce sont des erreurs de PROGRAMMATION (vue sans contexte, écriture croisée) :
elles ne sont pas converties en réponse d'API et remontent en 500 journalisée.
Les cas « normaux » (super-admin sur une route tenant, objet d'un autre
établissement) sont traités en amont par les permissions DRF (403) et par le
filtrage des querysets (404).
"""


class ErreurTenant(RuntimeError):
    """Classe de base des erreurs d'isolation entre établissements."""


class TenantNonDefini(ErreurTenant):
    """Accès à une table tenant sans établissement courant (échec fermé)."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "Aucun établissement courant : accès aux données d'établissement refusé."
        )


class ViolationTenant(ErreurTenant):
    """Écriture d'une ligne appartenant à un autre établissement que le contexte courant."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "La ligne n'appartient pas à l'établissement courant : écriture refusée."
        )

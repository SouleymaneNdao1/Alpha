"""Description OpenAPI du format d'erreur unique ``{code, message, details}`` (§ 5 ; ajout B7)."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers


class ErreurSerializer(serializers.Serializer):
    """Corps de toute réponse d'erreur de l'API."""

    code = serializers.CharField(help_text="Constante stable, ex. « DERNIER_ADMINISTRATEUR ».")
    message = serializers.CharField(help_text="Message en français, affichable tel quel.")
    details = serializers.DictField(help_text="Détails ; validation : {champ: [messages]}.")


_DESCRIPTIONS = {
    400: "Données invalides (VALIDATION ou code métier).",
    401: "Non authentifié.",
    403: "Permission refusée (y compris super-administrateur FYXOP sur une route d'établissement).",
    404: "Inexistant ou appartenant à un autre établissement.",
    409: "Conflit métier.",
}


def erreurs(*statuts: int, **descriptions: str) -> dict[int, OpenApiResponse]:
    """Réponses d'erreur à fusionner dans ``extend_schema(responses=...)``.

    ``erreurs(400, 404, r409="DERNIER_ADMINISTRATEUR")`` ; 401 et 403 sont toujours ajoutés.
    """
    resultat = {}
    for statut in sorted({401, 403, *statuts}):
        texte = descriptions.get(f"r{statut}") or _DESCRIPTIONS.get(statut, "Erreur.")
        resultat[statut] = OpenApiResponse(ErreurSerializer, description=texte)
    return resultat

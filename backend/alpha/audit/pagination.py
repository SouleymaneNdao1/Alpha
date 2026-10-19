"""Pagination par curseur du journal d'audit (architecture § 5, § 5.6) : ``?curseur=``.

Réponse ``{next, results}`` ; ``next`` est l'URL de la page suivante (``null`` à la fin).
Tri : horodatage décroissant, puis identifiant décroissant.
"""

from __future__ import annotations

from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class PaginationCurseurJournal(CursorPagination):
    ordering = ("-horodatage", "-id")
    cursor_query_param = "curseur"
    cursor_query_description = "Curseur opaque renvoyé dans `next` par la page précédente."
    page_size = 50
    page_size_query_param = "taille"
    page_size_query_description = "Nombre d'événements par page (50 par défaut, 100 au plus)."
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        try:
            return super().paginate_queryset(queryset, request, view)
        except NotFound:
            raise ValidationError({self.cursor_query_param: ["Curseur invalide."]}) from None

    def get_paginated_response(self, data) -> Response:
        return Response({"next": self.get_next_link(), "results": data})

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "required": ["next", "results"],
            "properties": {
                "next": {
                    "type": "string",
                    "nullable": True,
                    "format": "uri",
                    "description": "URL de la page suivante ; null quand il n'y en a plus.",
                },
                "results": schema,
            },
        }

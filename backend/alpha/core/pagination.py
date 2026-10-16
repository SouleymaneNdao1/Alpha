"""Pagination par défaut de l'API (architecture § 5).

``?page=1&taille=25`` (maximum 100) -> ``{count, next, previous, results}``.
La pagination par curseur du journal d'audit (``?curseur=``) relève de la tâche B11.
"""

from rest_framework.pagination import PageNumberPagination


class PaginationPage(PageNumberPagination):
    page_query_param = "page"
    page_query_description = "Numéro de page (à partir de 1)."
    page_size = 25
    page_size_query_param = "taille"
    page_size_query_description = "Nombre d'éléments par page (25 par défaut, 100 au maximum)."
    max_page_size = 100
    invalid_page_message = "Page invalide."

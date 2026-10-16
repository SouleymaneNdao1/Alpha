"""Intégration du contexte de requête dans les journaux applicatifs."""

import logging

from alpha.core import contexte


class FiltreContexte(logging.Filter):
    """Ajoute ``request_id`` (ou « - ») à chaque enregistrement de journal."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = contexte.request_id() or "-"
        return True

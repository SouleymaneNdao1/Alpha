#!/usr/bin/env python
"""Utilitaire en ligne de commande de Django pour ALPHA."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django est introuvable. Activez l'environnement virtuel ou utilisez "
            "scripts/dev.sh (conteneurs Docker)."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

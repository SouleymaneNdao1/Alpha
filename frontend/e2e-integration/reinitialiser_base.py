"""Remet la base de la suite d'intégration à zéro (schéma « public » recréé).

Lancé par ``preparer.mjs`` avec ``DATABASE_URL_OWNER`` (alpha_owner, propriétaire de la base). Les
migrations rejouent ensuite extensions, droits et politiques RLS (architecture § 3.1).

Garde-fou : refuse de toucher une base dont le nom ne contient pas « e2e », sauf si
``ALPHA_E2E_BASE_JETABLE=1`` (poste de développement avec une base dédiée aux tests).
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

import psycopg


def main() -> int:
    url = os.environ.get("DATABASE_URL_OWNER", "")
    if not url:
        print("DATABASE_URL_OWNER est obligatoire.", file=sys.stderr)
        return 1
    nom_base = urlparse(url).path.lstrip("/")
    if "e2e" not in nom_base and os.environ.get("ALPHA_E2E_BASE_JETABLE") != "1":
        print(
            f"Refus : la base « {nom_base} » n'a pas « e2e » dans son nom. Si elle est bien dédiée "
            "aux tests et jetable, définissez ALPHA_E2E_BASE_JETABLE=1.",
            file=sys.stderr,
        )
        return 1
    with psycopg.connect(url, autocommit=True) as connexion:
        connexion.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connexion.execute("CREATE SCHEMA public")
    print(f"Base « {nom_base} » remise à zéro.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

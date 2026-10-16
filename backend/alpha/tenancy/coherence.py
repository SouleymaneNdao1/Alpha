"""Clés étrangères « même établissement » (complément de la RLS, tâche B3).

Les contrôles d'intégrité référentielle de PostgreSQL ignorent la RLS : en
``alpha_app``, une ligne de l'établissement A pourrait référencer l'identifiant
d'une ligne de B (rôle, unité, utilisateur) si l'identifiant était connu.
``cle_meme_etablissement`` ajoute une clé étrangère composite
``(colonne, etablissement_id) → cible(id, etablissement_id)`` qui l'interdit au
niveau SQL.

La table cible doit porter une contrainte ``UNIQUE (id, etablissement_id)``,
déclarée dans le ``Meta`` du modèle (``UniqueConstraint(fields=["id", "etablissement"])``).

``MATCH SIMPLE`` : si la colonne ou ``etablissement_id`` est NULL (référence
facultative, ligne du super-admin), la clé n'est pas contrôlée ; la clé
étrangère simple de Django reste en place dans tous les cas.
"""

from __future__ import annotations

from django.db import migrations

from .rls import _ident


def sql_cle_meme_etablissement(table: str, colonne: str, cible: str) -> tuple[str, str]:
    nom = _ident(f"{table}_{colonne}_meme_etab"[:63])
    t, c, ci = _ident(table), _ident(colonne), _ident(cible)
    avant = (
        f"ALTER TABLE {t} ADD CONSTRAINT {nom} "
        f"FOREIGN KEY ({c}, etablissement_id) REFERENCES {ci} (id, etablissement_id) "
        "MATCH SIMPLE DEFERRABLE INITIALLY DEFERRED;"
    )
    arriere = f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {nom};"
    return avant, arriere


def cle_meme_etablissement(table: str, colonne: str, cible: str) -> migrations.RunSQL:
    """``RunSQL`` réversible : ``table.colonne`` doit viser une ligne du même établissement."""
    avant, arriere = sql_cle_meme_etablissement(table, colonne, cible)
    return migrations.RunSQL(avant, arriere)

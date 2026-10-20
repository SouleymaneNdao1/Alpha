"""Recette (VPS, derrière Caddy en HTTPS) : comme la production, avec documentation de l'API."""

from .prod import *  # noqa: F403

ALPHA_DOC_API_ACTIVE = True
# Décision du client : schéma et documentation réservés aux utilisateurs connectés
# (en plus du mot de passe des outils de recette posé par Caddy).
ALPHA_DOC_API_RESERVEE_CONNECTES = True

# Jeu de démonstration : refusé par défaut ; à activer explicitement pour une recette
# (ALPHA_DEMO_AUTORISEE=true dans .env.recette), puis à retirer.
ALPHA_DEMO_AUTORISEE = env.bool("ALPHA_DEMO_AUTORISEE", default=False)  # noqa: F405

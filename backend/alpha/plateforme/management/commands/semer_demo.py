"""Jeu de démonstration : établissements, comptes avec MFA active, tâches, absence (tâche B12).

    python manage.py semer_demo                       # écrit ./demo-acces/ACCES.txt et les QR codes
    python manage.py semer_demo --sortie /chemin      # autre dossier de sortie
    python manage.py semer_demo --reinitialiser       # nouveaux mots de passe, secrets et codes

Refuse de s'exécuter si ``settings.ALPHA_DEMO_AUTORISEE`` n'est pas vrai (vrai en dev et en
test, faux en recette et en production). Idempotent : relancée, elle ne crée aucun doublon et
ne change aucun identifiant sans ``--reinitialiser``. Voir ``alpha.plateforme.demo``.

Les mots de passe, secrets TOTP et codes de secours sont affichés à la fin (une seule fois) et
écrits dans ``ACCES.txt`` ; ils ne sont ni journalisés ni enregistrés ailleurs qu'en base
(hachés ou chiffrés).
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from alpha.core.erreurs import ErreurApi
from alpha.plateforme import demo


class Command(BaseCommand):
    help = (
        "Sème le jeu de démonstration (Établissement démo, Sahel Distribution) avec des comptes "
        "prêts à se connecter (mot de passe, MFA, codes de secours, QR codes)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sortie",
            default=demo.DOSSIER_PAR_DEFAUT,
            help="Dossier des QR codes et de ACCES.txt (défaut : ./demo-acces).",
        )
        parser.add_argument(
            "--reinitialiser",
            action="store_true",
            help="Régénère mots de passe, secrets TOTP et codes de secours des comptes existants.",
        )

    def handle(self, *args, **options):
        sortie = Path(options["sortie"])
        try:
            demo.verifier_autorisation()
        except demo.DemoRefusee as erreur:
            raise CommandError(str(erreur)) from None
        try:
            resultat = demo.semer(
                sortie=sortie,
                reinitialiser=options["reinitialiser"],
                ecrire=lambda message: self.stdout.write(message),
            )
        except ErreurApi as erreur:
            raise CommandError(f"{erreur.code} : {erreur.message}") from None
        self._rapport(resultat, sortie)

    def _rapport(self, resultat: demo.Resultat, sortie: Path) -> None:
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Jeu de démonstration prêt : {resultat.etablissements_crees} établissement(s) "
                f"créé(s), {resultat.comptes_crees} compte(s) créé(s), "
                f"{resultat.comptes_existants} déjà présent(s), "
                f"{resultat.taches_ouvertes} tâche(s) ouverte(s)."
            )
        )
        if resultat.rien_de_nouveau:
            self.stdout.write(
                "Aucun identifiant généré : les comptes existants gardent leurs identifiants "
                f"(voir {sortie / demo.NOM_FICHIER_ACCES}). "
                "Utilisez --reinitialiser pour en générer de nouveaux."
            )
            return
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "IDENTIFIANTS (affichés une seule fois ; secrets et codes non récupérables) :"
            )
        )
        self.stdout.write("")
        self.stdout.write(demo.rendre_acces(resultat))
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(resultat.acces)} compte(s) équipé(s). Récapitulatif et QR codes : "
                f"{sortie.resolve()}"
            )
        )
        self.stdout.write(
            "Ajoutez chaque compte dans Google ou Microsoft Authenticator (scan du QR code "
            "ou saisie du secret), puis connectez-vous."
        )

"""Crée un super-administrateur FYXOP (architecture § 3.8, tâche B10).

    python manage.py creer_super_admin                       # interactif
    python manage.py creer_super_admin --email ops@fyxop.sn --prenom Awa --nom Ndiaye
    ALPHA_SUPER_ADMIN_EMAIL=… ALPHA_SUPER_ADMIN_PRENOM=… ALPHA_SUPER_ADMIN_NOM=… \\
    ALPHA_SUPER_ADMIN_MOT_DE_PASSE=… python manage.py creer_super_admin --no-input
    python manage.py creer_super_admin --nouveau-lien --email ops@fyxop.sn

Seul moyen de créer un super-administrateur (``create_superuser`` est désactivé). Le compte
est ACTIF, avec le mot de passe saisi, mais son application d'authentification est à
configurer au premier accès : la connexion répond ``REENROLEMENT_REQUIS`` et un lien de
configuration (parcours de réenrôlement, valable 24 h) part par e-mail. ``--nouveau-lien``
réémet ce lien pour un compte pas encore configuré.

Le mot de passe n'est JAMAIS passé en option (historique du shell) : saisie masquée, ou
variable d'environnement ``ALPHA_SUPER_ADMIN_MOT_DE_PASSE`` en mode non interactif. Il n'est
ni affiché ni journalisé. Le lien n'est affiché qu'avec ``--afficher-lien`` (recette sans
e-mail). S'exécute avec le rôle applicatif, en portée « platform ».
"""

from __future__ import annotations

import getpass
import os

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from alpha.core.erreurs import ErreurApi
from alpha.plateforme import services

VARIABLES = {
    "email": "ALPHA_SUPER_ADMIN_EMAIL",
    "prenom": "ALPHA_SUPER_ADMIN_PRENOM",
    "nom": "ALPHA_SUPER_ADMIN_NOM",
}
VARIABLE_MOT_DE_PASSE = "ALPHA_SUPER_ADMIN_MOT_DE_PASSE"
QUESTIONS = {"email": "Adresse e-mail", "prenom": "Prénom", "nom": "Nom"}
ESSAIS_MOT_DE_PASSE = 3


class Command(BaseCommand):
    help = (
        "Crée un super-administrateur FYXOP (MFA à configurer au premier accès). "
        "Interactif, ou --no-input avec les variables ALPHA_SUPER_ADMIN_*."
    )

    # Points d'injection (tests).
    saisir = staticmethod(input)
    saisir_secret = staticmethod(getpass.getpass)

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Adresse e-mail (sinon ALPHA_SUPER_ADMIN_EMAIL).")
        parser.add_argument("--prenom", help="Prénom (sinon ALPHA_SUPER_ADMIN_PRENOM).")
        parser.add_argument("--nom", help="Nom (sinon ALPHA_SUPER_ADMIN_NOM).")
        parser.add_argument(
            "--no-input",
            "--noinput",
            action="store_false",
            dest="interactif",
            help="Aucune question : tout vient des options et des variables d'environnement.",
        )
        parser.add_argument(
            "--nouveau-lien",
            action="store_true",
            help="Réémet le lien de configuration d'un super-administrateur pas encore configuré.",
        )
        parser.add_argument(
            "--afficher-lien",
            action="store_true",
            help="Affiche aussi le lien de configuration (sensible : à remettre en main propre).",
        )

    def handle(self, *args, **options):
        interactif = options["interactif"]
        email = self._valeur("email", options, interactif)
        try:
            if options["nouveau_lien"]:
                utilisateur, lien = services.nouveau_lien_super_admin(email=email)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Nouveau lien de configuration envoyé à {utilisateur.email}."
                    )
                )
            else:
                prenom = self._valeur("prenom", options, interactif)
                nom = self._valeur("nom", options, interactif)
                utilisateur, lien = self._creer(email, prenom, nom, interactif)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Super-administrateur créé : {utilisateur.email}. Un lien de "
                        "configuration de l'application d'authentification (valable 24 h) a été "
                        "envoyé par e-mail ; la MFA est exigée dès le premier accès."
                    )
                )
        except ErreurApi as erreur:
            raise CommandError(erreur.message) from None
        if options["afficher_lien"]:
            self.stdout.write(f"Lien de configuration (usage unique) : {lien}")

    # --- Saisie ---------------------------------------------------------------------------------

    def _valeur(self, champ: str, options: dict, interactif: bool) -> str:
        valeur = (options.get(champ) or os.environ.get(VARIABLES[champ], "")).strip()
        while not valeur and interactif:
            valeur = self.saisir(f"{QUESTIONS[champ]} : ").strip()
        if not valeur:
            raise CommandError(f"{QUESTIONS[champ]} manquant(e) : --{champ} ou {VARIABLES[champ]}.")
        return valeur

    def _mot_de_passe(self, interactif: bool) -> str:
        if not interactif:
            mot_de_passe = os.environ.get(VARIABLE_MOT_DE_PASSE, "")
            if not mot_de_passe:
                raise CommandError(f"Mot de passe manquant : variable {VARIABLE_MOT_DE_PASSE}.")
            return mot_de_passe
        while True:
            mot_de_passe = self.saisir_secret("Mot de passe : ")
            if mot_de_passe and mot_de_passe == self.saisir_secret("Confirmation : "):
                return mot_de_passe
            self.stderr.write("Les deux saisies sont vides ou différentes.")

    def _creer(self, email: str, prenom: str, nom: str, interactif: bool):
        essais = ESSAIS_MOT_DE_PASSE if interactif else 1
        for essai in range(1, essais + 1):
            mot_de_passe = self._mot_de_passe(interactif)
            try:
                return services.creer_super_admin(
                    email=email, prenom=prenom, nom=nom, mot_de_passe=mot_de_passe
                )
            except ValidationError as erreur:
                messages = " ".join(erreur.messages)
                if essai == essais:
                    raise CommandError(f"Mot de passe refusé : {messages}") from None
                self.stderr.write(f"Mot de passe refusé : {messages}")
        raise CommandError("Mot de passe refusé.")  # pragma: no cover

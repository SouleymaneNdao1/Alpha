"""Jeu de démonstration (``manage.py semer_demo``, architecture § 8, tâche B12).

Objectif : lancer l'application en local et SE CONNECTER tout de suite, la MFA étant obligatoire.
Pour chaque compte de démonstration (et pour un super-administrateur FYXOP) le semis :

- pose un mot de passe aléatoire conforme à la politique (12 caractères au moins) ;
- crée un Authenticator ACTIF dont le secret TOTP est aléatoire et chiffré comme partout
  (``alpha.comptes.mfa`` et ``alpha.comptes.chiffrement``) ;
- génère 10 codes de secours (affichés une seule fois) ;
- écrit un QR code SVG par compte et un récapitulatif ``ACCES.txt`` dans le dossier de sortie.

Le jeu contient deux établissements (« Établissement démo », banque, et « Sahel Distribution »,
PME) avec les utilisateurs et les tâches du prototype, une absence validée avec délégation
active et le journal d'audit que produisent les services (provisionnement, invitations,
activations, tâches, absence, délégation).

Tout passe par les services existants, sous le contexte tenant de chaque établissement :
``plateforme.services`` (provisionnement, super-administrateur), ``comptes.administration``
(invitations, affectations, suspension), ``organisation.services`` (unités),
``taches.services.ouvrir``, ``delegations.services`` (absence, validation) et
``audit.services.journaliser``. Aucune insertion SQL directe : la RLS et le chaînage du
journal restent ceux de l'application.

Garde-fous :
- refus si ``settings.ALPHA_DEMO_AUTORISEE`` n'est pas vrai (vrai en dev et en test, faux en
  recette et en production) ;
- idempotent : relancé, il ne crée aucun doublon ni ne change les identifiants existants
  (``reinitialiser=True`` régénère mots de passe, secrets et codes de secours) ;
- aucun e-mail n'est envoyé (invitation, configuration du super-administrateur) : les comptes
  de démonstration sont activés directement.
"""

from __future__ import annotations

import datetime
import secrets
import uuid
import zoneinfo
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pyotp
import segno
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from alpha.audit.models import Categorie, TypeActeur
from alpha.audit.services import Acteur, journaliser
from alpha.comptes import administration, emails, mfa, raccordements
from alpha.comptes.models import (
    JetonUsageUnique,
    StatutUtilisateur,
    Utilisateur,
)
from alpha.comptes.mots_de_passe import definir_mot_de_passe
from alpha.comptes.resolution import resoudre_connexion
from alpha.core import contexte
from alpha.delegations import services as delegations
from alpha.delegations.models import Absence, MotifAbsence, StatutAbsence
from alpha.organisation.models import AffectationRole, Role, UniteOrganisationnelle
from alpha.organisation.services import creer_unite
from alpha.taches import services as taches
from alpha.taches.models import Groupe, Tache
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement

from . import demo_donnees as donnees
from . import services as plateforme
from .demo_donnees import EtablissementDemo, TacheDemo, UtilisateurDemo

ACTEUR_DEMO = Acteur(TypeActeur.SYSTEME, None, "Jeu de démonstration")

#: Espace de noms des identifiants (déterministes) des objets sources des tâches de démonstration.
_ESPACE_SOURCES = uuid.UUID("5b0f4cde-7c63-4b8e-9d0b-6f2a3e1d9c10")
SOURCE_TYPE_TACHE = "demo.dossier"

NOM_FICHIER_ACCES = "ACCES.txt"
DOSSIER_PAR_DEFAUT = "demo-acces"
NB_ESSAIS_MOT_DE_PASSE = 50
_ALPHABET_MDP = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


class DemoRefusee(Exception):
    """Le jeu de démonstration n'est pas autorisé dans cet environnement."""


# --- Résultat ---------------------------------------------------------------------------------


@dataclass
class Acces:
    """Identifiants d'un compte de démonstration (affichés une seule fois)."""

    email: str
    nom: str
    role: str
    etablissement: str
    mot_de_passe: str
    secret: str
    uri: str
    codes_secours: list[str]
    fichier_qr: str = ""


@dataclass
class Resultat:
    acces: list[Acces] = field(default_factory=list)
    #: (e-mail, nom, rôle, état) : comptes volontairement sans accès (invité, suspendu).
    sans_acces: list[tuple[str, str, str, str]] = field(default_factory=list)
    etablissements_crees: int = 0
    comptes_crees: int = 0
    comptes_existants: int = 0
    taches_ouvertes: int = 0
    reinitialise: bool = False
    fichiers: list[Path] = field(default_factory=list)

    @property
    def rien_de_nouveau(self) -> bool:
        return not self.acces


# --- Outils -----------------------------------------------------------------------------------


@contextmanager
def _sans_envoi_d_email() -> Iterator[None]:
    """Aucun e-mail pour les comptes de démonstration (invitation, configuration FYXOP).

    Les comptes sont activés directement ; les adresses sont fictives. Les deux points d'envoi
    de ces services sont neutralisés le temps du semis.
    """
    with (
        mock.patch.object(raccordements, "envoyer_invitation"),
        mock.patch.object(emails, "programmer"),
    ):
        yield


def _portee(utilisateur: Utilisateur):
    """Contexte d'écriture d'un compte : « platform » pour le super-admin, sinon son tenant."""
    if utilisateur.est_super_admin:
        return contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=utilisateur.pk)
    return contexte_tenant(utilisateur.etablissement_id, utilisateur_id=utilisateur.pk)


def _etablissement_audit(utilisateur: Utilisateur):
    """Chaîne d'audit du compte : celle de la plateforme pour un super-administrateur."""
    return None if utilisateur.est_super_admin else utilisateur.etablissement_id


def generer_mot_de_passe() -> str:
    """Mot de passe lisible : 4 groupes de 4 caractères (19 au total), sans ambiguïté O/0, l/1."""
    return "-".join("".join(secrets.choice(_ALPHABET_MDP) for _ in range(4)) for _ in range(4))


def _poser_mot_de_passe(utilisateur: Utilisateur) -> str:
    """Définit un mot de passe aléatoire conforme à la politique (essais jusqu'à validation)."""
    for _ in range(NB_ESSAIS_MOT_DE_PASSE):
        candidat = generer_mot_de_passe()
        try:
            definir_mot_de_passe(utilisateur, candidat)
        except ValidationError:
            continue
        return candidat
    raise RuntimeError("Impossible de produire un mot de passe conforme à la politique.")


def _mot_de_passe_valide(utilisateur: Utilisateur) -> str:
    """Mot de passe conforme à la politique, sans l'enregistrer (création du super-admin)."""
    for _ in range(NB_ESSAIS_MOT_DE_PASSE):
        candidat = generer_mot_de_passe()
        try:
            validate_password(candidat, user=utilisateur)
        except ValidationError:
            continue
        return candidat
    raise RuntimeError("Impossible de produire un mot de passe conforme à la politique.")


def _uri_totp(secret: str, utilisateur: Utilisateur, emetteur: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=utilisateur.email, issuer_name=emetteur)


def _equiper_mfa(utilisateur: Utilisateur, emetteur: str) -> tuple[str, str, list[str]]:
    """Authenticator ACTIF (secret aléatoire chiffré) et 10 codes de secours.

    Renvoie (secret en clair, URI otpauth://, codes de secours). La confirmation se fait sur le
    pas précédent : le code courant reste utilisable à la première connexion (anti-rejeu).
    À appeler dans le contexte du compte.
    """
    authenticator, secret = mfa.creer_authenticator_en_attente(utilisateur, "Jeu de démonstration")
    precedent = pyotp.TOTP(secret).at(timezone.now() - datetime.timedelta(seconds=30))
    if not mfa.confirmer_authenticator(authenticator, precedent):  # pragma: no cover
        raise RuntimeError("Confirmation de l'Authenticator de démonstration impossible.")
    codes = mfa.generer_codes_secours(utilisateur)
    return secret, _uri_totp(secret, utilisateur, emetteur), codes


def _journaliser_securite(action: str, utilisateur: Utilisateur, detail: str, **apres) -> None:
    journaliser(
        action,
        Categorie.SECURITE,
        objet=("comptes.utilisateur", utilisateur.pk),
        objet_libelle=utilisateur.nom_complet,
        apres=apres or None,
        detail=detail,
        acteur=ACTEUR_DEMO,
        etablissement_id=_etablissement_audit(utilisateur),
    )


def _libelle_roles(utilisateur: Utilisateur) -> str:
    affectations = (
        AffectationRole.objects.en_cours()
        .filter(utilisateur_id=utilisateur.pk)
        .select_related("role")
        .order_by("-principal", "debut", "id")
    )
    libelles: list[str] = []
    for affectation in affectations:
        if affectation.role.libelle not in libelles:
            libelles.append(affectation.role.libelle)
    return " + ".join(libelles)


def _reinitialiser_acces(
    utilisateur: Utilisateur, emetteur: str
) -> tuple[str, str, str, list[str]]:
    """Nouveaux mot de passe, secret et codes d'un compte ACTIF existant (--reinitialiser)."""
    mot_de_passe = _poser_mot_de_passe(utilisateur)
    if administration.est_verrouille(utilisateur) or utilisateur.echecs_connexion:
        administration.deverrouiller(utilisateur, par=ACTEUR_DEMO)
    secret, uri, codes = _equiper_mfa(utilisateur, emetteur)
    raccordements.revoquer_sessions(utilisateur.id, motif="REVOCATION_ADMIN")
    _journaliser_securite(
        "auth.mdp.modifie", utilisateur, "Mot de passe régénéré par le jeu de démonstration"
    )
    _journaliser_securite(
        "mfa.reenrole",
        utilisateur,
        "Authenticator et codes de secours régénérés par le jeu de démonstration",
        codes_secours=len(codes),
    )
    return mot_de_passe, secret, uri, codes


# --- Fichiers de sortie -----------------------------------------------------------------------


def _nom_fichier_qr(email: str) -> str:
    return "qr-" + email.replace("@", "_") + ".svg"


def _ecrire_qr(sortie: Path, acces: Acces) -> Path:
    chemin = sortie / _nom_fichier_qr(acces.email)
    # Fond blanc explicite : lisible aussi dans un navigateur en thème sombre.
    segno.make(acces.uri, error="m").save(
        str(chemin), kind="svg", scale=6, border=4, dark="#000000", light="#ffffff"
    )
    acces.fichier_qr = chemin.name
    return chemin


def rendre_acces(resultat: Resultat, *, titre: str | None = None) -> str:
    """Texte du récapitulatif (``ACCES.txt`` et affichage final) : comptes générés ce jour."""
    lignes: list[str] = []
    if titre:
        lignes += [titre, "=" * len(titre), ""]
    for acces in resultat.acces:
        lignes += [
            f"Compte        : {acces.nom} ({acces.etablissement})",
            f"Rôle          : {acces.role}",
            f"E-mail        : {acces.email}",
            f"Mot de passe  : {acces.mot_de_passe}",
            f"Secret TOTP   : {acces.secret}",
            f"URI otpauth   : {acces.uri}",
            f"QR code       : {acces.fichier_qr}",
            "Codes de secours (usage unique) : " + "  ".join(acces.codes_secours),
            "",
        ]
    return "\n".join(lignes)


def _entete_acces() -> str:
    maintenant = timezone.localtime().strftime("%d/%m/%Y à %H:%M")
    return "\n".join(
        [
            "ALPHA · comptes de démonstration",
            f"Générés le {maintenant}",
            "",
            "CONFIDENTIEL : ce fichier contient des mots de passe, des secrets TOTP et des codes",
            "de secours. Il reste sur ce poste (le dossier est exclu de git) : ne le partagez pas.",
            "",
            f"Application : {settings.ALPHA_URL_FRONTEND}",
            "",
            "Se connecter :",
            "  1. Dans Google Authenticator ou Microsoft Authenticator, ajoutez le compte en",
            "     scannant le QR code du compte (fichier .svg de ce dossier, à ouvrir dans le",
            "     navigateur) ou en saisissant le secret TOTP à la main (type : basé sur l'heure).",
            "  2. Sur l'application : e-mail, mot de passe, puis le code à 6 chiffres de",
            "     l'application d'authentification.",
            "  3. Un code de secours remplace le code à 6 chiffres une seule fois.",
            "",
            "Pour tout régénérer : manage.py semer_demo --reinitialiser (nouveaux mots de passe,",
            "secrets et codes ; les anciens cessent de fonctionner).",
            "",
            "-" * 78,
            "",
        ]
    )


def _ecrire_acces(sortie: Path, resultat: Resultat, *, complement: bool) -> Path:
    """Écrit ``ACCES.txt`` ; en mode complément, ajoute les nouveaux comptes à la suite."""
    chemin = sortie / NOM_FICHIER_ACCES
    corps = rendre_acces(resultat)
    maintenant = timezone.localtime().strftime("%d/%m/%Y à %H:%M")
    if complement and chemin.exists():
        suite = f"\nComptes ajoutés le {maintenant}\n" + "-" * 78 + "\n\n" + corps
        with chemin.open("a", encoding="utf-8") as fichier:
            fichier.write(suite)
        return chemin
    texte = _entete_acces() + corps
    if resultat.sans_acces:
        texte += "\nComptes sans accès (état voulu pour la démonstration) :\n"
        for email, nom, role, etat in resultat.sans_acces:
            texte += f"  - {nom} <{email}> · {role} · {etat}\n"
    chemin.write_text(texte, encoding="utf-8")
    return chemin


# --- Super-administrateur FYXOP ----------------------------------------------------------------


def _super_admin(resultat: Resultat, reinitialiser: bool) -> Utilisateur:
    """Crée (ou retrouve) le super-administrateur de démonstration, MFA active."""
    email = donnees.SUPER_ADMIN_EMAIL
    emetteur = "ALPHA (FYXOP)"
    resolution = resoudre_connexion(email)
    if resolution is None:
        modele = Utilisateur(
            email=email, prenom=donnees.SUPER_ADMIN_PRENOM, nom=donnees.SUPER_ADMIN_NOM
        )
        with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM):
            mot_de_passe = _mot_de_passe_valide(modele)
        utilisateur, _ = plateforme.creer_super_admin(
            email=email,
            prenom=donnees.SUPER_ADMIN_PRENOM,
            nom=donnees.SUPER_ADMIN_NOM,
            mot_de_passe=mot_de_passe,
        )
        with _portee(utilisateur):
            # Comme un compte configuré : plus de réenrôlement à faire, lien annulé.
            utilisateur.mfa_a_reconfigurer = False
            utilisateur.save(update_fields=["mfa_a_reconfigurer", "modifie_le"])
            JetonUsageUnique.objects.filter(
                utilisateur=utilisateur, utilise_le__isnull=True, annule_le__isnull=True
            ).update(annule_le=timezone.now())
            secret, uri, codes = _equiper_mfa(utilisateur, emetteur)
            _journaliser_securite(
                "mfa.active",
                utilisateur,
                "Application d'authentification configurée par le jeu de démonstration",
                codes_secours=len(codes),
            )
        resultat.comptes_crees += 1
    else:
        with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM):
            utilisateur = Utilisateur.objects.get(pk=resolution.utilisateur_id)
        if not reinitialiser:
            resultat.comptes_existants += 1
            return utilisateur
        with _portee(utilisateur):
            mot_de_passe, secret, uri, codes = _reinitialiser_acces(utilisateur, emetteur)
    resultat.acces.append(
        Acces(
            email=email,
            nom=utilisateur.nom_complet,
            role=donnees.SUPER_ADMIN_ROLE,
            etablissement="console FYXOP",
            mot_de_passe=mot_de_passe,
            secret=secret,
            uri=uri,
            codes_secours=codes,
        )
    )
    return utilisateur


# --- Établissements -----------------------------------------------------------------------------


def _provisionner(
    spec: EtablissementDemo, super_admin: Utilisateur, resultat: Resultat
) -> tuple[Etablissement, Utilisateur]:
    """Établissement et administrateur (invité) : provisionnement de la console, B10."""
    email_admin = f"{spec.administrateur}@{spec.domaine}"
    nom_admin = next(u for u in spec.utilisateurs if u.cle == spec.administrateur)
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=super_admin.pk):
        etablissement = Etablissement.objects.filter(code=spec.code).first()
        if etablissement is None:
            etablissement, admin = plateforme.provisionner_etablissement(
                par=super_admin,
                code=spec.code,
                raison_sociale=spec.raison_sociale,
                type=spec.type,
                pays="SN",
                administrateur={
                    "email": email_admin,
                    "prenom": nom_admin.prenom,
                    "nom": nom_admin.nom,
                },
            )
            resultat.etablissements_crees += 1
            return etablissement, admin
    with contexte_tenant(etablissement.id):
        admin = Utilisateur.objects.filter(email=email_admin).first()
    if admin is None:
        raise RuntimeError(
            f"L'établissement « {spec.code} » existe mais son administrateur de démonstration "
            f"({email_admin}) est introuvable : base incohérente."
        )
    return etablissement, admin


def _unites(spec: EtablissementDemo, admin: Utilisateur) -> dict[str, UniteOrganisationnelle]:
    """Unités du jeu (créées si absentes) + l'unité racine du provisionnement."""
    existantes = {u.code: u for u in UniteOrganisationnelle.objects.all()}
    racine = existantes.get(plateforme.CODE_UNITE_RACINE)
    for unite in spec.unites:
        if unite.code in existantes:
            continue
        parent = existantes.get(unite.parent) if unite.parent else racine
        existantes[unite.code] = creer_unite(
            par=admin, type=unite.type, code=unite.code, libelle=unite.libelle, parent=parent
        )
    return existantes


def _activer(utilisateur: Utilisateur) -> None:
    """INVITE → ACTIF (le compte de démonstration n'a pas de lien d'invitation à suivre)."""
    maintenant = timezone.now()
    avant = {"statut": utilisateur.statut}
    utilisateur.statut = StatutUtilisateur.ACTIF
    utilisateur.active_le = maintenant
    utilisateur.save(update_fields=["statut", "active_le", "modifie_le"])
    JetonUsageUnique.objects.filter(
        utilisateur=utilisateur, utilise_le__isnull=True, annule_le__isnull=True
    ).update(utilise_le=maintenant)
    journaliser(
        "utilisateur.active",
        Categorie.MODIFICATION,
        objet=utilisateur,
        objet_libelle=utilisateur.email,
        avant=avant,
        apres={"statut": utilisateur.statut, "active_le": maintenant},
        detail="Compte activé par le jeu de démonstration",
        acteur=ACTEUR_DEMO,
    )


def _utilisateurs(
    spec: EtablissementDemo,
    etablissement: Etablissement,
    admin: Utilisateur,
    unites: dict[str, UniteOrganisationnelle],
    resultat: Resultat,
    reinitialiser: bool,
    neuf: bool,
) -> dict[str, Utilisateur]:
    """Crée, active et équipe (mot de passe, MFA, codes) les utilisateurs du jeu."""
    roles = {r.code: r for r in Role.objects.filter(actif=True)}
    emetteur = f"ALPHA ({etablissement.raison_sociale})"
    par_cle: dict[str, Utilisateur] = {}
    for definition in spec.utilisateurs:
        email = f"{definition.cle}@{spec.domaine}"
        utilisateur = Utilisateur.objects.filter(email=email).first()
        cree = utilisateur is None
        provisionne = definition.cle == spec.administrateur and neuf
        if cree:
            utilisateur = _creer_utilisateur(definition, email, admin, roles, unites, par_cle)
            resultat.comptes_crees += 1
        elif provisionne:
            resultat.comptes_crees += 1
        else:
            resultat.comptes_existants += 1
        par_cle[definition.cle] = utilisateur
        _habilitations_en_plus(spec, definition, utilisateur, admin, roles, unites)
        if definition.statut == StatutUtilisateur.INVITE:
            resultat.sans_acces.append(
                (
                    email,
                    utilisateur.nom_complet,
                    roles[definition.role].libelle,
                    "invité, jamais activé (lien d'invitation à renvoyer depuis l'administration)",
                )
            )
            continue
        if utilisateur.statut == StatutUtilisateur.SUSPENDU:
            resultat.sans_acces.append(
                (email, utilisateur.nom_complet, roles[definition.role].libelle, "compte suspendu")
            )
            continue
        if utilisateur.statut == StatutUtilisateur.INVITE:
            # Compte à activer (créé ici, ou administrateur invité par le provisionnement).
            mot_de_passe = _poser_mot_de_passe(utilisateur)
            secret, uri, codes = _equiper_mfa(utilisateur, emetteur)
            _activer(utilisateur)
            _journaliser_securite(
                "mfa.active",
                utilisateur,
                "Application d'authentification configurée par le jeu de démonstration",
                codes_secours=len(codes),
            )
        elif reinitialiser and utilisateur.statut == StatutUtilisateur.ACTIF:
            mot_de_passe, secret, uri, codes = _reinitialiser_acces(utilisateur, emetteur)
        else:
            continue
        if definition.statut == StatutUtilisateur.SUSPENDU:
            # État du prototype : compte activé puis suspendu (identifiants non conservés).
            administration.suspendre(
                utilisateur, par=admin, motif="Compte suspendu (jeu de démonstration)"
            )
            resultat.sans_acces.append(
                (email, utilisateur.nom_complet, roles[definition.role].libelle, "compte suspendu")
            )
            continue
        resultat.acces.append(
            Acces(
                email=email,
                nom=utilisateur.nom_complet,
                role=_libelle_roles(utilisateur),
                etablissement=etablissement.raison_sociale,
                mot_de_passe=mot_de_passe,
                secret=secret,
                uri=uri,
                codes_secours=codes,
            )
        )
    return par_cle


def _creer_utilisateur(
    definition: UtilisateurDemo,
    email: str,
    admin: Utilisateur,
    roles: dict[str, Role],
    unites: dict[str, UniteOrganisationnelle],
    par_cle: dict[str, Utilisateur],
) -> Utilisateur:
    if definition.cle == "":  # pragma: no cover - garde-fou de données
        raise ValueError("Clé d'utilisateur vide.")
    if definition.responsable and definition.responsable not in par_cle:
        raise ValueError(
            f"Le responsable « {definition.responsable} » doit être défini avant "
            f"« {definition.cle} » dans les données de démonstration."
        )
    return administration.inviter(
        par=admin,
        email=email,
        prenom=definition.prenom,
        nom=definition.nom,
        role_id=roles[definition.role].id,
        unite=unites[definition.unite] if definition.unite else None,
        responsable=par_cle[definition.responsable] if definition.responsable else None,
    )


def _habilitations_en_plus(
    spec: EtablissementDemo,
    definition: UtilisateurDemo,
    utilisateur: Utilisateur,
    admin: Utilisateur,
    roles: dict[str, Role],
    unites: dict[str, UniteOrganisationnelle],
) -> None:
    """Habilitations supplémentaires (suppléance du DAF, DG-administrateur de la PME)."""
    souhaitees: list[tuple[str, str | None, bool]] = [
        (role, unite, False) for role, unite in definition.en_plus
    ]
    if definition.cle == spec.administrateur and spec.administrateur_aussi:
        souhaitees.append((*spec.administrateur_aussi, True))
    for code_role, code_unite, principal in souhaitees:
        role = roles[code_role]
        unite = unites[code_unite] if code_unite else None
        deja = AffectationRole.objects.en_cours().filter(
            utilisateur=utilisateur, role=role, unite=unite
        )
        if not deja.exists():
            administration.ajouter_affectation(
                utilisateur, par=admin, role_id=role.id, unite=unite, principal=principal
            )


# --- Tâches ---------------------------------------------------------------------------------


def echeance_pour(
    urgence: str,
    *,
    maintenant: datetime.datetime,
    fuseau: datetime.tzinfo,
    retard_jours: int = 1,
) -> datetime.datetime:
    """Échéance qui place la tâche dans le groupe d'urgence demandé (fuseau de l'établissement).

    - EN_RETARD : ``retard_jours`` jours avant maintenant ;
    - AUJOURD'HUI : 23:00 locale (ou dans 15 minutes si l'heure est passée) ;
    - CETTE SEMAINE : dans 2 jours à midi, ramené au dimanche si besoin ; le dimanche, il ne
      reste aucun jour dans la semaine : la tâche tombe alors dans « Aujourd'hui » ;
    - PLUS TARD : dans 10 jours à midi.
    """
    local = maintenant.astimezone(fuseau)
    midi = datetime.time(12, 0)
    if urgence == Groupe.EN_RETARD:
        return maintenant - datetime.timedelta(days=retard_jours)
    if urgence == Groupe.AUJOURDHUI:
        fin = datetime.datetime.combine(local.date(), datetime.time(23, 0), fuseau)
        return fin if fin > maintenant else maintenant + datetime.timedelta(minutes=15)
    if urgence == Groupe.CETTE_SEMAINE:
        jours = min(2, 6 - local.weekday())
        if jours < 1:
            return echeance_pour(Groupe.AUJOURDHUI, maintenant=maintenant, fuseau=fuseau)
        return datetime.datetime.combine(
            local.date() + datetime.timedelta(days=jours), midi, fuseau
        )
    if urgence == Groupe.PLUS_TARD:
        return datetime.datetime.combine(local.date() + datetime.timedelta(days=10), midi, fuseau)
    raise ValueError(f"Urgence inconnue : {urgence!r}.")


def _taches(
    spec: EtablissementDemo,
    etablissement: Etablissement,
    par_cle: dict[str, Utilisateur],
    unites: dict[str, UniteOrganisationnelle],
    resultat: Resultat,
) -> None:
    roles = {r.code: r for r in Role.objects.filter(actif=True)}
    fuseau = zoneinfo.ZoneInfo(etablissement.fuseau_horaire)
    maintenant = timezone.now()
    for definition in spec.taches:
        source = (
            SOURCE_TYPE_TACHE,
            uuid.uuid5(_ESPACE_SOURCES, f"{etablissement.code}:{definition.cle}"),
        )
        # Une tâche déjà semée (même fermée depuis) n'est jamais rouverte : pas de doublon.
        if Tache.objects.filter(source_type=source[0], source_id=source[1]).exists():
            continue
        _ouvrir_tache(definition, source, par_cle, roles, unites, maintenant, fuseau)
        resultat.taches_ouvertes += 1


def _ouvrir_tache(
    definition: TacheDemo,
    source: tuple[str, uuid.UUID],
    par_cle: dict[str, Utilisateur],
    roles: dict[str, Role],
    unites: dict[str, UniteOrganisationnelle],
    maintenant: datetime.datetime,
    fuseau: datetime.tzinfo,
) -> Tache:
    return taches.ouvrir(
        source,
        module=definition.module,
        action=definition.action,
        titre=definition.titre,
        sous_titre=definition.sous_titre,
        reference=definition.reference,
        montant=Decimal(definition.montant) if definition.montant is not None else None,
        type_echeance=definition.type_echeance,
        echeance=echeance_pour(
            definition.urgence,
            maintenant=maintenant,
            fuseau=fuseau,
            retard_jours=definition.retard_jours,
        ),
        assigne_utilisateur=par_cle[definition.destinataire] if definition.destinataire else None,
        assigne_role=roles[definition.role] if definition.role else None,
        assigne_unite=unites[definition.unite] if definition.unite else None,
        demandeur=par_cle[definition.demandeur] if definition.demandeur else None,
        lien="/a-traiter",
        acteur=ACTEUR_DEMO,
    )


# --- Absence et délégation ---------------------------------------------------------------------


def _absence(spec: EtablissementDemo, par_cle: dict[str, Utilisateur], fuseau_nom: str) -> None:
    """Absence validée, délégation active (soumise par l'absent, validée par son responsable)."""
    definition = spec.absence
    if definition is None:
        return
    absent = par_cle[definition.absent]
    delegataire = par_cle[definition.delegataire]
    maintenant = timezone.now()
    en_cours = Absence.objects.filter(
        utilisateur=absent,
        statut__in=(StatutAbsence.SOUMISE, StatutAbsence.VALIDEE),
        fin__gt=maintenant,
    )
    if en_cours.exists():
        return
    fuseau = zoneinfo.ZoneInfo(fuseau_nom)
    # Début : minuit local du jour, pour que la délégation soit déjà en vigueur.
    debut = datetime.datetime.combine(maintenant.astimezone(fuseau).date(), datetime.time(), fuseau)
    fin = debut + datetime.timedelta(days=definition.duree_jours)
    absence = delegations.soumettre_absence(
        absent,
        debut=debut,
        fin=fin,
        motif=MotifAbsence.CONGE,
        delegataire_id=delegataire.pk,
        commentaire=definition.commentaire,
    )
    valideur = Utilisateur.objects.get(pk=absence.valideur_id)
    delegations.valider_absence(absence, valideur)


# --- Point d'entrée ---------------------------------------------------------------------------


def verifier_autorisation() -> None:
    if not getattr(settings, "ALPHA_DEMO_AUTORISEE", False):
        raise DemoRefusee(
            "Le jeu de démonstration est interdit dans cet environnement "
            "(ALPHA_DEMO_AUTORISEE n'est pas vrai). Il n'est autorisé qu'en développement "
            "et en test ; en recette, il faut l'activer explicitement (ALPHA_DEMO_AUTORISEE=true)."
        )


def semer(
    *,
    sortie: Path,
    reinitialiser: bool = False,
    ecrire: Callable[[str], None] = lambda _: None,
) -> Resultat:
    """Sème (ou complète) le jeu de démonstration ; écrit QR et ``ACCES.txt`` dans ``sortie``."""
    verifier_autorisation()
    resultat = Resultat(reinitialise=reinitialiser)
    with _sans_envoi_d_email():
        ecrire("Super-administrateur FYXOP de démonstration…")
        super_admin = _super_admin(resultat, reinitialiser)
        for spec in donnees.ETABLISSEMENTS:
            ecrire(f"{spec.raison_sociale}…")
            avant = resultat.etablissements_crees
            etablissement, admin = _provisionner(spec, super_admin, resultat)
            neuf = resultat.etablissements_crees > avant
            with contexte_tenant(etablissement.id, utilisateur_id=admin.pk):
                unites = _unites(spec, admin)
                par_cle = _utilisateurs(
                    spec, etablissement, admin, unites, resultat, reinitialiser, neuf
                )
                _taches(spec, etablissement, par_cle, unites, resultat)
                _absence(spec, par_cle, etablissement.fuseau_horaire)
    if resultat.acces:
        resultat.fichiers = _ecrire_sortie(sortie, resultat, complement=not reinitialiser)
    return resultat


def _ecrire_sortie(sortie: Path, resultat: Resultat, *, complement: bool) -> list[Path]:
    sortie.mkdir(parents=True, exist_ok=True)
    # Filet de sécurité : si le dossier est choisi dans le dépôt, git n'y voit rien.
    (sortie / ".gitignore").write_text("*\n", encoding="utf-8")
    fichiers = [_ecrire_qr(sortie, acces) for acces in resultat.acces]
    fichiers.append(_ecrire_acces(sortie, resultat, complement=complement))
    return fichiers

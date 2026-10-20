"""Jeu de démonstration ``manage.py semer_demo`` (tâche B12).

Critères : s'exécute sur une base vide puis une seconde fois sans doublon ; refusé quand
``ALPHA_DEMO_AUTORISEE`` est faux ; un compte de démonstration se connecte par l'API avec son
mot de passe et un vrai code TOTP (puis avec un code de secours) ; les tâches sont visibles dans
``/taches/`` ; la chaîne d'audit est intacte ; ``--reinitialiser`` remplace les identifiants.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pyotp
import pytest
from django.contrib.auth.hashers import check_password
from django.core.management import CommandError, call_command
from django.test import Client
from freezegun import freeze_time

from alpha.audit.models import EvenementAudit, StatutControle
from alpha.audit.verification import lancer_verification
from alpha.comptes import chiffrement
from alpha.comptes.models import (
    AuthenticatorTOTP,
    CodeSecours,
    StatutAuthenticator,
    StatutUtilisateur,
    Utilisateur,
)
from alpha.delegations.models import Absence, Delegation, StatutAbsence, StatutDelegation
from alpha.plateforme import demo, demo_donnees
from alpha.taches.models import Tache
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement
from tests.fabriques import contexte_plateforme
from tests.outils_auth import URL_CONNEXION, URL_MFA, poster, transactionnel

pytest_plugins = ["tests.fixtures_auth"]  # client_csrf, vider_limites

# Mercredi, en milieu de journée : les quatre groupes d'urgence sont représentables.
MERCREDI = "2026-11-04T10:00:00+00:00"

BANQUE = demo_donnees.BANQUE
PME = demo_donnees.PME


# --- Outils ---------------------------------------------------------------------------------


def _etablissement(code: str) -> Etablissement:
    with contexte_plateforme():
        return Etablissement.objects.get(code=code)


def _acces(resultat: demo.Resultat, email: str) -> demo.Acces:
    return next(a for a in resultat.acces if a.email == email)


def _compter(modele, etablissement_id=None) -> int:
    if etablissement_id is None:
        with contexte_plateforme():
            return modele.objects.count()
    with contexte_tenant(etablissement_id):
        return modele.objects.count()


def _empreintes() -> dict[str, int]:
    """Nombre de lignes par table du jeu (plateforme + chaque établissement)."""
    compteurs = {"etablissements": _compter(Etablissement)}
    with contexte_plateforme():
        compteurs["super_admin"] = Utilisateur.objects.filter(est_super_admin=True).count()
        compteurs["audit_plateforme"] = EvenementAudit.objects.filter(etablissement_id=None).count()
    for spec in (BANQUE, PME):
        etab = _etablissement(spec.code)
        for modele in (Utilisateur, Tache, Absence, Delegation, AuthenticatorTOTP, CodeSecours):
            compteurs[f"{spec.code}:{modele.__name__}"] = _compter(modele, etab.id)
        with contexte_tenant(etab.id):
            compteurs[f"{spec.code}:audit"] = EvenementAudit.objects.count()
    return compteurs


def _se_connecter(client: Client, email: str, mot_de_passe: str, **mfa):
    """Mot de passe puis MFA ; renvoie (réponse connexion, réponse MFA ou None)."""
    r = poster(client, URL_CONNEXION, {"email": email, "mot_de_passe": mot_de_passe})
    if r.status_code != 200:
        return r, None
    assert r.json()["etape"] == "MFA_REQUIS"
    return r, poster(client, URL_MFA, mfa)


def _connecte(email: str, acces: demo.Acces) -> Client:
    client = Client()
    _, r = _se_connecter(client, email, acces.mot_de_passe, code=pyotp.TOTP(acces.secret).now())
    assert r is not None and r.status_code == 200, r.content if r is not None else "pas de MFA"
    return client


def _chaines_intactes() -> None:
    for etab_id in (
        None,
        _etablissement(BANQUE.code).id,
        _etablissement(PME.code).id,
    ):
        controle = lancer_verification(etab_id)
        assert controle.statut == StatutControle.INTACTE, controle.message


# --- Base vide, puis idempotence --------------------------------------------------------------


@pytest.mark.django_db
def test_semis_complet_puis_idempotence(tmp_path):
    sortie = tmp_path / "demo-acces"
    premier = demo.semer(sortie=sortie)

    # Comptes : super-admin + (16 - invité - suspendu) + (10 - invité) = 24 accès.
    assert len(premier.acces) == 1 + 14 + 9
    assert {e for e, *_ in premier.sans_acces} == {
        "c.badiane@etablissement-demo.sn",
        "r.thiam@etablissement-demo.sn",
        "m.ndiaye@sahel-distribution.sn",
    }
    assert premier.etablissements_crees == 2
    assert premier.taches_ouvertes == len(BANQUE.taches) + len(PME.taches)
    for acces in premier.acces:
        assert len(acces.mot_de_passe) >= 12
        assert len(acces.secret) == 32
        assert acces.uri.startswith("otpauth://totp/") and acces.secret in acces.uri
        assert len(acces.codes_secours) == 10 and len(set(acces.codes_secours)) == 10
        assert (sortie / acces.fichier_qr).read_text(encoding="utf-8").startswith("<?xml")

    # Fichiers : QR par compte, récapitulatif, filet .gitignore.
    texte = (sortie / "ACCES.txt").read_text(encoding="utf-8")
    assert (sortie / ".gitignore").read_text() == "*\n"
    for acces in premier.acces:
        for valeur in (acces.email, acces.mot_de_passe, acces.secret, *acces.codes_secours):
            assert valeur in texte

    # Base : secret chiffré (jamais en clair), mot de passe haché, MFA active, 10 codes.
    for spec in (BANQUE, PME):
        etab = _etablissement(spec.code)
        with contexte_tenant(etab.id):
            admin = Utilisateur.objects.get(email=f"{spec.administrateur}@{spec.domaine}")
            assert admin.statut == StatutUtilisateur.ACTIF
            for acces in (a for a in premier.acces if a.etablissement == etab.raison_sociale):
                utilisateur = Utilisateur.objects.get(email=acces.email)
                assert utilisateur.statut == StatutUtilisateur.ACTIF
                assert check_password(acces.mot_de_passe, utilisateur.password)
                auth = AuthenticatorTOTP.objects.get(utilisateur=utilisateur)
                assert auth.statut == StatutAuthenticator.ACTIF
                assert acces.secret.encode() not in bytes(auth.secret_chiffre)
                assert chiffrement.dechiffrer(auth.secret_chiffre) == acces.secret
                assert (
                    CodeSecours.objects.filter(
                        utilisateur=utilisateur, utilise_le__isnull=True, invalide_le__isnull=True
                    ).count()
                    == 10
                )
            invite = Utilisateur.objects.filter(statut=StatutUtilisateur.INVITE)
            assert {u.email for u in invite} <= {
                "c.badiane@etablissement-demo.sn",
                "m.ndiaye@sahel-distribution.sn",
            }
    with contexte_plateforme():
        super_admin = Utilisateur.objects.get(email=demo_donnees.SUPER_ADMIN_EMAIL)
        assert super_admin.est_super_admin and not super_admin.mfa_a_reconfigurer
    with contexte_tenant(None, scope="platform", utilisateur_id=super_admin.pk):
        assert AuthenticatorTOTP.objects.get(utilisateur=super_admin).statut == "ACTIF"

    # Seconde exécution : rien de nouveau, rien de modifié.
    avant = _empreintes()
    empreinte_fichier = hashlib.sha256((sortie / "ACCES.txt").read_bytes()).hexdigest()
    second = demo.semer(sortie=sortie)
    assert second.rien_de_nouveau and second.acces == []
    assert second.etablissements_crees == second.comptes_crees == second.taches_ouvertes == 0
    assert _empreintes() == avant
    assert hashlib.sha256((sortie / "ACCES.txt").read_bytes()).hexdigest() == empreinte_fichier


@pytest.mark.django_db
def test_commande_affiche_les_identifiants(tmp_path, capsys):
    sortie = tmp_path / "acces"
    call_command("semer_demo", f"--sortie={sortie}")
    affichage = capsys.readouterr().out
    assert "IDENTIFIANTS" in affichage and "otpauth://totp/" in affichage
    assert "Codes de secours" in affichage
    assert (sortie / "ACCES.txt").exists()
    # Seconde exécution : aucun identifiant affiché.
    call_command("semer_demo", f"--sortie={sortie}")
    assert "Aucun identifiant généré" in capsys.readouterr().out


# --- Refus hors des environnements autorisés -----------------------------------------------------


@pytest.mark.django_db
def test_refus_quand_la_demo_n_est_pas_autorisee(settings, tmp_path):
    settings.ALPHA_DEMO_AUTORISEE = False
    sortie = tmp_path / "demo-acces"
    with pytest.raises(CommandError, match="ALPHA_DEMO_AUTORISEE"):
        call_command("semer_demo", f"--sortie={sortie}")
    with pytest.raises(demo.DemoRefusee):
        demo.semer(sortie=sortie)
    assert not sortie.exists()
    assert _compter(Etablissement) == 0


def _charger_reglages(module: str, monkeypatch, **env) -> object:
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "alpha.test")
    monkeypatch.delenv("ALPHA_DEMO_AUTORISEE", raising=False)
    for cle, valeur in env.items():
        monkeypatch.setenv(cle, valeur)
    for nom in ("config.settings.prod", "config.settings.recette", "config.settings.dev"):
        monkeypatch.delitem(sys.modules, nom, raising=False)
    return importlib.import_module(module)


def test_reglage_par_environnement(monkeypatch):
    """Vrai en dev ; faux en production et en recette, sauf activation explicite en recette."""
    assert _charger_reglages("config.settings.dev", monkeypatch).ALPHA_DEMO_AUTORISEE is True
    assert _charger_reglages("config.settings.prod", monkeypatch).ALPHA_DEMO_AUTORISEE is False
    assert _charger_reglages("config.settings.recette", monkeypatch).ALPHA_DEMO_AUTORISEE is False
    recette = _charger_reglages("config.settings.recette", monkeypatch, ALPHA_DEMO_AUTORISEE="true")
    assert recette.ALPHA_DEMO_AUTORISEE is True
    # Production : la variable d'environnement n'a aucun effet.
    prod = _charger_reglages("config.settings.prod", monkeypatch, ALPHA_DEMO_AUTORISEE="true")
    assert prod.ALPHA_DEMO_AUTORISEE is False


# --- Connexion réelle, tâches, absence, audit -----------------------------------------------------


@transactionnel
def test_connexion_totp_taches_absence_et_audit(tmp_path):
    with freeze_time(MERCREDI):
        resultat = demo.semer(sortie=tmp_path / "demo-acces")

        # 1. Connexion par l'API : mot de passe + vrai code TOTP (compte DAF de la banque).
        kane = _acces(resultat, "a.kane@etablissement-demo.sn")
        client = Client()
        r = poster(client, URL_CONNEXION, {"email": kane.email, "mot_de_passe": kane.mot_de_passe})
        assert r.status_code == 200 and r.json()["etape"] == "MFA_REQUIS"
        r = poster(client, URL_MFA, {"code": pyotp.TOTP(kane.secret).now()})
        assert r.status_code == 200, r.content
        moi = r.json()
        assert kane.email in json.dumps(moi)

        # Un mauvais mot de passe reste refusé.
        r = poster(Client(), URL_CONNEXION, {"email": kane.email, "mot_de_passe": "Faux-Mdp-1234"})
        assert r.status_code == 401

        # 2. Super-administrateur : même mécanisme, MFA configurée (pas de réenrôlement).
        sa = _acces(resultat, demo_donnees.SUPER_ADMIN_EMAIL)
        reponse_sa, mfa_sa = _se_connecter(
            Client(), sa.email, sa.mot_de_passe, code=pyotp.TOTP(sa.secret).now()
        )
        assert reponse_sa.json()["etape"] == "MFA_REQUIS"
        assert mfa_sa.status_code == 200, mfa_sa.content

        # 3. Un code de secours remplace le code TOTP, une seule fois.
        sy = _acces(resultat, "f.sy@etablissement-demo.sn")
        code = sy.codes_secours[0]
        _, r = _se_connecter(Client(), sy.email, sy.mot_de_passe, code_secours=code)
        assert r.status_code == 200, r.content
        _, r = _se_connecter(Client(), sy.email, sy.mot_de_passe, code_secours=code)
        assert r.status_code == 401

        # 4. Tâches du DAF : 9 tâches sur les 4 urgences (écran « À traiter » du prototype).
        compteurs = client.get("/api/v1/taches/compteurs").json()
        assert compteurs["total"] == 9
        assert compteurs["par_groupe"] == {
            "EN_RETARD": 1,
            "AUJOURDHUI": 3,
            "CETTE_SEMAINE": 3,
            "PLUS_TARD": 2,
        }
        assert set(compteurs["par_module"]) == {"INTERNE", "TRESORERIE", "FISCAL", "RH", "CONTRATS"}
        liste = client.get("/api/v1/taches").json()
        references = {t["reference"] for t in liste["results"]}
        assert {"ED-2026-0077", "PAY-2026-0412", "CTR-2026-0009"} <= references
        assert all(t["par_delegation_de"] is None for t in liste["results"])

        # 5. Absence validée, délégation active : le suppléant voit les tâches du DAF.
        faye = _acces(resultat, "o.faye@etablissement-demo.sn")
        suppleant = _connecte(faye.email, faye)
        taches = suppleant.get("/api/v1/taches?taille=100").json()["results"]
        par_delegation = [t for t in taches if t["par_delegation_de"]]
        assert len(par_delegation) == 9
        assert {t["par_delegation_de"]["nom"] for t in par_delegation} == {"Abdou Kane"}

        # 6. File commune du rôle « analyste crédit » : 3 tâches propres + 1 tâche de rôle.
        diop = _connecte(
            "a.diop@etablissement-demo.sn", _acces(resultat, "a.diop@etablissement-demo.sn")
        )
        assert diop.get("/api/v1/taches/compteurs").json()["total"] == 4
        seck = _connecte(
            "k.seck@etablissement-demo.sn", _acces(resultat, "k.seck@etablissement-demo.sn")
        )
        assert [t["reference"] for t in seck.get("/api/v1/taches").json()["results"]] == [
            "CR-2026-0425"
        ]

        # 7. Les 4 urgences et plusieurs modules, dans chaque établissement.
        etab = _etablissement(BANQUE.code)
        with contexte_tenant(etab.id):
            assert Tache.objects.values("module").distinct().count() >= 5
            absence = Absence.objects.get()
            delegation = Delegation.objects.get()
            assert absence.statut == StatutAbsence.VALIDEE
            assert delegation.statut == StatutDelegation.ACTIVE
            assert delegation.activee_le is not None
            assert delegation.delegant.email == "a.kane@etablissement-demo.sn"
            assert delegation.delegataire.email == "o.faye@etablissement-demo.sn"
            actions = set(EvenementAudit.objects.values_list("action", flat=True))
        assert {
            "utilisateur.invite",
            "utilisateur.active",
            "utilisateur.suspendu",
            "mfa.active",
            "affectation.creee",
            "unite.creee",
            "tache.ouverte",
            "absence.soumise",
            "absence.validee",
            "delegation.active",
            "auth.connexion.succes",
        } <= actions
        with contexte_plateforme():
            plateforme_actions = set(
                EvenementAudit.objects.filter(etablissement_id=None).values_list(
                    "action", flat=True
                )
            )
        assert {
            "plateforme.super_admin.cree",
            "plateforme.etablissement.cree",
        } <= plateforme_actions

        # 8. Aucun secret dans le journal ; chaînes intactes.
        secrets_a_chercher = [a.secret for a in resultat.acces] + [
            a.mot_de_passe for a in resultat.acces
        ]
        secrets_a_chercher += [c for a in resultat.acces for c in a.codes_secours]
        for spec in (BANQUE, PME):
            with contexte_tenant(_etablissement(spec.code).id):
                texte = json.dumps(
                    list(EvenementAudit.objects.values_list("payload_canonique", "detail")),
                    default=str,
                )
            assert not [s for s in secrets_a_chercher if s in texte]
        _chaines_intactes()


@transactionnel
def test_reinitialiser_remplace_les_identifiants(tmp_path):
    sortie = tmp_path / "demo-acces"
    with freeze_time(MERCREDI):
        premier = demo.semer(sortie=sortie)
        ancien = _acces(premier, "a.diop@etablissement-demo.sn")
        avant = _empreintes()

    with freeze_time("2026-11-04T10:05:00+00:00"):
        second = demo.semer(sortie=sortie, reinitialiser=True)
        assert second.reinitialise and len(second.acces) == len(premier.acces)
        nouveau = _acces(second, ancien.email)
        assert nouveau.mot_de_passe != ancien.mot_de_passe
        assert nouveau.secret != ancien.secret
        assert set(nouveau.codes_secours).isdisjoint(ancien.codes_secours)
        # Pas de doublon d'objets métier ; un seul Authenticator actif par compte.
        apres = _empreintes()
        for cle in ("etablissements", "super_admin"):
            assert apres[cle] == avant[cle]
        for spec in (BANQUE, PME):
            for modele in ("Utilisateur", "Tache", "Absence", "Delegation"):
                assert apres[f"{spec.code}:{modele}"] == avant[f"{spec.code}:{modele}"]
        with contexte_tenant(_etablissement(BANQUE.code).id):
            assert (
                AuthenticatorTOTP.objects.filter(
                    utilisateur__email=ancien.email, statut=StatutAuthenticator.ACTIF
                ).count()
                == 1
            )
        # L'ancien mot de passe est refusé, le nouveau (avec un code TOTP) fonctionne.
        r, _ = _se_connecter(Client(), ancien.email, ancien.mot_de_passe)
        assert r.status_code == 401
        _connecte(nouveau.email, nouveau)
        # Les anciens codes de secours sont invalidés.
        _, r = _se_connecter(
            Client(), nouveau.email, nouveau.mot_de_passe, code_secours=ancien.codes_secours[0]
        )
        assert r.status_code == 401
        # Le récapitulatif est entièrement remplacé.
        texte = (sortie / "ACCES.txt").read_text(encoding="utf-8")
        assert nouveau.mot_de_passe in texte and ancien.mot_de_passe not in texte
        _chaines_intactes()


# --- Échéances --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "groupe_attendu_cette_semaine"),
    [
        ("2026-11-02T08:00:00+00:00", "CETTE_SEMAINE"),  # lundi
        ("2026-11-04T10:00:00+00:00", "CETTE_SEMAINE"),  # mercredi
        ("2026-11-07T10:00:00+00:00", "CETTE_SEMAINE"),  # samedi : dimanche encore dans la semaine
        ("2026-11-08T10:00:00+00:00", "AUJOURDHUI"),  # dimanche : plus aucun jour dans la semaine
    ],
)
def test_echeances_dans_le_bon_groupe(instant, groupe_attendu_cette_semaine):
    import datetime
    import zoneinfo

    from alpha.taches.visibilite import bornes_urgence

    fuseau = zoneinfo.ZoneInfo("Africa/Dakar")
    maintenant = datetime.datetime.fromisoformat(instant)
    bornes = bornes_urgence(maintenant, fuseau)
    for urgence, attendu in (
        ("EN_RETARD", "EN_RETARD"),
        ("AUJOURDHUI", "AUJOURDHUI"),
        ("CETTE_SEMAINE", groupe_attendu_cette_semaine),
        ("PLUS_TARD", "PLUS_TARD"),
    ):
        echeance = demo.echeance_pour(urgence, maintenant=maintenant, fuseau=fuseau)
        assert bornes.groupe_de(echeance) == attendu, (instant, urgence)


def test_fichiers_de_sortie_par_defaut():
    """Dossier de sortie par défaut ``demo-acces`` (exclu de git)."""
    assert demo.DOSSIER_PAR_DEFAUT == "demo-acces"
    racine = Path(__file__).resolve().parents[2]
    lignes = (racine / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "demo-acces/" in lignes

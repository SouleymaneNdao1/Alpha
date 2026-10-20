"""``manage.py creer_super_admin`` et premier accès à la console (§ 3.8, tâche B10).

Le compte est créé ACTIF, MFA à configurer au premier accès : la connexion répond
``REENROLEMENT_REQUIS`` ; le lien reçu par e-mail ouvre le parcours de réenrôlement, au
terme duquel la session plateforme donne accès à la console (step-up TOTP réel).
"""

from __future__ import annotations

import io

import pyotp
import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from alpha.comptes.models import JetonUsageUnique, ObjetJeton, Utilisateur
from alpha.plateforme.management.commands import creer_super_admin as commande
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement
from tests.fabriques import UtilisateurFactory, contexte_plateforme
from tests.outils_auth import (
    MDP,
    URL_CONNEXION,
    evenements,
    jeton_csrf,
    poster,
    transactionnel,
)
from tests.outils_b6 import API_AUTH, code_precedent, lien_de, messages_pour, secret_de

# Fixtures client_csrf et vider_limites (autouse : compteurs de débit remis à zéro).
pytest_plugins = ["tests.fixtures_auth"]

EMAIL = "ops@fyxop.test"
SUJET = "Configurez l'accès à la console FYXOP"


@pytest.fixture
def variables(monkeypatch):
    monkeypatch.setenv("ALPHA_SUPER_ADMIN_EMAIL", EMAIL)
    monkeypatch.setenv("ALPHA_SUPER_ADMIN_PRENOM", "Mariama")
    monkeypatch.setenv("ALPHA_SUPER_ADMIN_NOM", "Ba")
    monkeypatch.setenv("ALPHA_SUPER_ADMIN_MOT_DE_PASSE", MDP)


def _relire(email: str = EMAIL) -> Utilisateur:
    with contexte_plateforme():
        return Utilisateur.objects.get(email=email)


def _executer(*args, capture, **options) -> str:
    sortie = io.StringIO()
    with capture(execute=True):
        call_command("creer_super_admin", *args, stdout=sortie, stderr=io.StringIO(), **options)
    return sortie.getvalue()


@pytest.mark.django_db
def test_creation_non_interactive(variables, django_capture_on_commit_callbacks):
    mail.outbox.clear()
    sortie = _executer("--no-input", capture=django_capture_on_commit_callbacks)
    assert "Super-administrateur créé" in sortie and "/reenrolement/" not in sortie
    u = _relire()
    assert u.est_super_admin and u.etablissement_id is None
    assert u.statut == "ACTIF" and u.mfa_a_reconfigurer and u.check_password(MDP)
    with contexte_tenant(None, scope="platform", utilisateur_id=u.id):
        assert JetonUsageUnique.objects.filter(
            utilisateur=u, objet=ObjetJeton.REENROLEMENT_MFA, utilise_le__isnull=True
        ).exists()
    (message,) = messages_pour(EMAIL, SUJET)
    assert "/reenrolement/" in message.body
    (evt,) = evenements(None, "plateforme.super_admin.cree")
    assert evt.acteur_type == "SYSTEME" and evt.categorie == "SUPER_ADMIN"
    assert MDP not in evt.payload_canonique
    assert lien_de(message, "/reenrolement/") not in evt.payload_canonique


@pytest.mark.django_db
def test_options_prioritaires_et_lien_affiche(variables, django_capture_on_commit_callbacks):
    sortie = _executer(
        "--no-input",
        "--afficher-lien",
        email="autre@fyxop.test",
        capture=django_capture_on_commit_callbacks,
    )
    assert "Lien de configuration (usage unique) : http" in sortie
    assert _relire("autre@fyxop.test").prenom == "Mariama"


@pytest.mark.django_db
def test_creation_interactive(monkeypatch, django_capture_on_commit_callbacks):
    reponses = iter([EMAIL, "Mariama", "Ba"])
    secrets = iter(["court", "court", "AutreSecret-Long!", "Different-Long-1!", MDP, MDP])
    monkeypatch.setattr(commande.Command, "saisir", staticmethod(lambda _q: next(reponses)))
    monkeypatch.setattr(commande.Command, "saisir_secret", staticmethod(lambda _q: next(secrets)))
    erreurs = io.StringIO()
    with django_capture_on_commit_callbacks(execute=True):
        call_command("creer_super_admin", stdout=io.StringIO(), stderr=erreurs)
    assert "Mot de passe refusé" in erreurs.getvalue()  # « court » refusé par la politique
    assert "différentes" in erreurs.getvalue()
    assert _relire().check_password(MDP)


@pytest.mark.django_db
def test_refus(variables, monkeypatch):
    UtilisateurFactory(super_admin=True, email=EMAIL)
    with pytest.raises(CommandError, match="déjà utilisée"):
        call_command("creer_super_admin", "--no-input", stdout=io.StringIO())
    monkeypatch.setenv("ALPHA_SUPER_ADMIN_MOT_DE_PASSE", "motdepassefaible")
    with pytest.raises(CommandError, match="Mot de passe refusé"):
        call_command(
            "creer_super_admin", "--no-input", email="neuf@fyxop.test", stdout=io.StringIO()
        )
    monkeypatch.delenv("ALPHA_SUPER_ADMIN_MOT_DE_PASSE")
    with pytest.raises(CommandError, match="ALPHA_SUPER_ADMIN_MOT_DE_PASSE"):
        call_command(
            "creer_super_admin", "--no-input", email="neuf@fyxop.test", stdout=io.StringIO()
        )
    monkeypatch.delenv("ALPHA_SUPER_ADMIN_NOM")
    with pytest.raises(CommandError, match="ALPHA_SUPER_ADMIN_NOM"):
        call_command(
            "creer_super_admin", "--no-input", email="neuf@fyxop.test", stdout=io.StringIO()
        )
    with contexte_plateforme():
        assert not Utilisateur.objects.filter(email="neuf@fyxop.test").exists()


@pytest.mark.django_db
def test_nouveau_lien(variables, django_capture_on_commit_callbacks):
    _executer("--no-input", capture=django_capture_on_commit_callbacks)
    mail.outbox.clear()
    sortie = _executer("--no-input", "--nouveau-lien", capture=django_capture_on_commit_callbacks)
    assert "Nouveau lien" in sortie
    assert len(messages_pour(EMAIL, SUJET)) == 1
    u = _relire()
    with contexte_tenant(None, scope="platform", utilisateur_id=u.id):
        jetons = JetonUsageUnique.objects.filter(utilisateur=u, objet=ObjetJeton.REENROLEMENT_MFA)
        assert jetons.count() == 2 and jetons.filter(annule_le__isnull=True).count() == 1
    assert evenements(None, "plateforme.super_admin.lien_renvoye")
    with pytest.raises(CommandError, match="Aucun super-administrateur"):
        call_command(
            "creer_super_admin",
            "--no-input",
            "--nouveau-lien",
            email="x@fyxop.test",
            stdout=io.StringIO(),
        )


@transactionnel
def test_premier_acces_puis_provisionnement_avec_un_vrai_code(variables, client_csrf):
    """Bout en bout : commande → connexion (réenrôlement requis) → configuration → console."""
    mail.outbox.clear()
    call_command("creer_super_admin", "--no-input", stdout=io.StringIO())
    client = client_csrf

    r = poster(client, URL_CONNEXION, {"email": EMAIL, "mot_de_passe": MDP})
    assert r.status_code == 200 and r.json()["etape"] == "REENROLEMENT_REQUIS"

    (message,) = messages_pour(EMAIL, SUJET)
    base = f"{API_AUTH}/reenrolement/{lien_de(message, '/reenrolement/')}"
    r = client.get(base)
    assert r.status_code == 200 and r.json()["etablissement"] == "FYXOP"
    assert poster(client, f"{base}/mot-de-passe", {"mot_de_passe": MDP}).status_code == 204
    secret = secret_de(poster(client, f"{base}/authenticator"))
    r = poster(client, f"{base}/authenticator/confirmer", {"code": code_precedent(secret)})
    assert r.status_code == 200 and len(r.json()["codes_secours"]) == 10
    r = poster(client, f"{base}/terminer", {"codes_conserves": True})
    assert r.status_code == 200, r.content
    assert r.json()["est_super_admin"] is True
    assert not _relire().mfa_a_reconfigurer

    # Session plateforme : la console répond, les routes d'établissement non.
    assert client.get("/api/v1/plateforme/moi").status_code == 200
    assert client.get("/api/v1/taches").status_code == 403

    corps = {
        "code": "pme-teranga",
        "raison_sociale": "Teranga Distribution",
        "type": "PME",
        "pays": "SN",
        "administrateur": {"email": "dg@teranga.test", "prenom": "Moussa", "nom": "Diallo"},
        "code_totp": "000000",
    }
    r = client.post(
        "/api/v1/plateforme/etablissements",
        corps,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=jeton_csrf(client),
    )
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    assert evenements(None, "auth.step_up.echec")  # refus journalisé, non annulé
    corps["code_totp"] = pyotp.TOTP(secret).now()
    r = client.post(
        "/api/v1/plateforme/etablissements",
        corps,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=jeton_csrf(client),
    )
    assert r.status_code == 201, r.content
    with contexte_plateforme():
        assert Etablissement.objects.filter(code="pme-teranga").exists()
    assert messages_pour("dg@teranga.test", "Activez votre compte")

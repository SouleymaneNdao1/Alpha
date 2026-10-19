"""Service ``journaliser`` (B4, § 6.1, § 6.2) : contexte, acteur, masquage, transactions."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connections, transaction
from django.test import RequestFactory, override_settings

from alpha.audit import canonique
from alpha.audit.masquage import MASQUE, extraire_champs, normaliser_json
from alpha.audit.models import Categorie, EvenementAudit, TypeActeur
from alpha.audit.services import Acteur, journaliser, resoudre_acteur
from alpha.core import contexte
from alpha.core.middleware import RequestIdMiddleware
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.exceptions import ViolationTenant
from tests.appli_test.models import NoteTest

from .bd import ALIAS_APP, ALIAS_AUDIT

UTILISATEUR = uuid.UUID("11111111-2222-4333-8444-555555555555")


def _contexte_de_la_chaine(etablissement_id):
    """Contexte qui peut LIRE une chaîne sous alpha_app (RLS ``audit_lecture``)."""
    if etablissement_id is None:
        return contexte_tenant(None, scope=contexte.SCOPE_PLATFORM)
    return contexte_tenant(etablissement_id)


def _relire(evenement) -> EvenementAudit:
    """Relit l'événement sous le contexte de sa chaîne. Sans pk (insertion sans RETURNING,
    ligne illisible sous le contexte d'écriture) : le dernier événement de la chaîne."""
    with _contexte_de_la_chaine(evenement.etablissement_id):
        if evenement.pk is None:
            return EvenementAudit.objects.filter(etablissement=None).order_by("-id").first()
        return EvenementAudit.objects.get(pk=evenement.pk)


# --- Contexte et acteur ------------------------------------------------------------------------


@pytest.mark.django_db
def test_acteur_ip_user_agent_et_request_id_lus_dans_le_contexte(etab_a):
    rid = uuid.uuid4()
    with (
        contexte.contexte(
            utilisateur=UTILISATEUR, ip="203.0.113.7", request_id=rid.hex, user_agent="Mozilla/5.0"
        ),
        contexte_tenant(etab_a.id),
    ):
        evenement = journaliser("role.modifie", Categorie.PARAMETRAGE, detail="essai")

    lu = _relire(evenement)
    assert lu.etablissement_id == etab_a.id
    assert (lu.acteur_type, lu.acteur_id) == (TypeActeur.UTILISATEUR, UTILISATEUR)
    assert lu.acteur_libelle == "utilisateur 11111111"  # libellé provisoire, avant B3
    assert (lu.ip, lu.user_agent, lu.request_id) == ("203.0.113.7", "Mozilla/5.0", rid)
    payload = json.loads(lu.payload_canonique)
    assert payload["v"] == 1
    assert payload["ip"] == "203.0.113.7"
    assert payload["request_id"] == str(rid)
    assert payload["horodatage"].endswith("Z") and len(payload["horodatage"]) == 27
    assert lu.payload_canonique == canonique.construire_payload(
        {c: getattr(lu, c) for c in canonique.CHAMPS_PAYLOAD}
    )
    assert lu.hash == canonique.empreinte(canonique.genese(etab_a.id), 1, lu.payload_canonique)


@pytest.mark.django_db
def test_sans_requete_acteur_systeme_et_chaine_plateforme():
    """Tâche Celery ou commande : aucun contexte de requête."""
    evenement = journaliser("audit.controle", Categorie.SECURITE)
    lu = _relire(evenement)
    assert lu.etablissement_id is None
    assert (lu.acteur_type, lu.acteur_id, lu.acteur_libelle) == ("SYSTEME", None, "Système ALPHA")
    assert (lu.ip, lu.user_agent, lu.request_id) == (None, "", None)


@pytest.mark.django_db
def test_requete_anonyme_par_le_middleware():
    vu = {}

    def vue(request):
        from django.http import HttpResponse

        vu["evenement"] = journaliser(
            "auth.connexion.echec", Categorie.CONNEXION, objet_libelle="m.sow@exemple.sn"
        )
        return HttpResponse("ok")

    requete = RequestFactory().get(
        "/",
        REMOTE_ADDR="10.0.0.5",
        HTTP_USER_AGENT="Navigateur de test",
        HTTP_X_REQUEST_ID="caddy-1234abcd",
    )
    RequestIdMiddleware(vue)(requete)
    lu = _relire(vu["evenement"])
    assert (lu.acteur_type, lu.acteur_libelle) == ("ANONYME", "inconnu")
    assert (lu.ip, lu.user_agent) == ("10.0.0.5", "Navigateur de test")
    # X-Request-ID non uuid : uuid5 déterministe (corrélation conservée).
    assert lu.request_id == uuid.uuid5(
        uuid.UUID("6f1c2d3e-4b5a-4c6d-8e7f-a1b2c3d4e5f6"), "caddy-1234abcd"
    )
    assert lu.objet_libelle == "m.sow@exemple.sn"


def test_acteur_explicite_ou_objet_utilisateur():
    super_admin = SimpleNamespace(
        pk=UTILISATEUR, est_super_admin=True, get_full_name=lambda: "Admin FYXOP"
    )
    assert resoudre_acteur(super_admin) == Acteur("SUPER_ADMIN", UTILISATEUR, "Admin FYXOP")
    awa = SimpleNamespace(pk=UTILISATEUR, get_full_name=lambda: "Awa Diop")
    assert resoudre_acteur(awa) == Acteur("UTILISATEUR", UTILISATEUR, "Awa Diop")
    assert resoudre_acteur(Acteur("IA", None, "x" * 300)).libelle == "x" * 150
    with pytest.raises(ValueError):
        resoudre_acteur(Acteur("PIRATE"))
    # Sans résolveur (B5 branche alpha.comptes.audit, qui lit la base) : type déduit de la portée.
    with (
        override_settings(ALPHA_AUDIT_RESOLVEUR_ACTEUR=None),
        contexte.contexte(utilisateur=UTILISATEUR, scope=contexte.SCOPE_PLATFORM),
    ):
        assert resoudre_acteur().type == "SUPER_ADMIN"


def _resolveur_test(utilisateur_id):
    return Acteur(TypeActeur.UTILISATEUR, utilisateur_id, "Awa Diop")


@override_settings(ALPHA_AUDIT_RESOLVEUR_ACTEUR="tests.test_audit_service._resolveur_test")
def test_resolveur_d_acteur_raccordable():
    with contexte.contexte(utilisateur=UTILISATEUR):
        assert resoudre_acteur().libelle == "Awa Diop"


@pytest.mark.django_db
def test_objet_modele_et_validation(etab_a):
    with contexte_tenant(etab_a.id):
        note = NoteTest.objects.create(texte="CR-2026-0412")
        lu = _relire(journaliser("note.creee", Categorie.MODIFICATION, objet=note))
        assert (lu.objet_type, lu.objet_id, lu.objet_libelle) == (
            "appli_test.notetest",
            str(note.pk),
            "CR-2026-0412",
        )
        with pytest.raises(ValueError, match="Catégorie"):
            journaliser("x", "INCONNUE")
        with pytest.raises(ValueError, match="action"):
            journaliser("a" * 61, Categorie.SECURITE)
        with pytest.raises(ViolationTenant):
            journaliser("x", Categorie.SECURITE, etablissement_id=uuid.uuid4())
        # Chaîne de la plateforme forcée sous un contexte tenant (double journalisation § 3.8).
        assert (
            journaliser("x", Categorie.SUPER_ADMIN, etablissement_id=None).etablissement_id is None
        )


# --- Masquage (§ 6.1) ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_champs_sensibles_masques_et_absents_du_payload():
    secrets = {
        "mot_de_passe": "Secret-Pass-123!",
        "nouveau_mdp": "Autre-Pass-456!",
        "totp_secret": "JBSWY3DPEHPK3PXP",
        "codes_secours": ["12345678", "87654321"],
        "jeton_hash": "a" * 64,
        "token": "tok-123",
    }
    apres = {
        "email": "awa@exemple.sn",
        "mdp_longueur_min": 14,
        "mdp_historique": 5,
        "profil": {"nom": "Diop", "cle_api": "cle-123", **secrets},
        "liste": [{"secret": "s"}],
        **secrets,
    }
    lu = _relire(journaliser("parametres.securite.modifies", Categorie.PARAMETRAGE, apres=apres))
    assert lu.apres["email"] == "awa@exemple.sn"
    assert lu.apres["mdp_longueur_min"] == 14 and lu.apres["mdp_historique"] == 5
    for cle in secrets:
        assert lu.apres[cle] == MASQUE
        assert lu.apres["profil"][cle] == MASQUE
    assert lu.apres["profil"]["cle_api"] == MASQUE
    assert lu.apres["liste"] == [{"secret": MASQUE}]
    for valeur in (
        "Secret-Pass-123!",
        "Autre-Pass-456!",
        "JBSWY3DPEHPK3PXP",
        "12345678",
        "tok-123",
    ):
        assert valeur not in lu.payload_canonique


class _ModeleFactice:
    AUDIT_CHAMPS = ("email", "statut", "secret_totp")

    def __init__(self):
        self.email = "awa@exemple.sn"
        self.statut = "ACTIF"
        self.secret_totp = "JBSWY3DPEHPK3PXP"
        self.mot_de_passe = "argon2$..."


def test_liste_blanche_audit_champs():
    instance = _ModeleFactice()
    assert extraire_champs(instance) == {
        "email": "awa@exemple.sn",
        "statut": "ACTIF",
        "secret_totp": MASQUE,  # même déclaré par erreur : masqué
    }
    assert extraire_champs(instance, ["statut"]) == {"statut": "ACTIF"}
    with pytest.raises(ValueError, match="mot_de_passe"):
        extraire_champs(instance, ["mot_de_passe"])
    with pytest.raises(ImproperlyConfigured, match="AUDIT_CHAMPS"):
        extraire_champs(SimpleNamespace(x=1))


def test_valeurs_json_simples():
    instant = dt.datetime(2026, 10, 10, 20, 31, 7, tzinfo=dt.UTC)
    assert normaliser_json(
        {"montant": Decimal("1500000.50"), "le": instant, "id": UTILISATEUR, "ok": True, "n": 3}
    ) == {
        "montant": "1500000.50",
        "le": "2026-10-10T20:31:07Z",
        "id": str(UTILISATEUR),
        "ok": True,
        "n": 3,
    }
    with pytest.raises(ValueError, match="flottante"):
        normaliser_json({"taux": 0.1})


# --- Transaction de l'action et mode indépendant ------------------------------------------------


@pytest.mark.django_db
def test_par_defaut_l_evenement_suit_la_transaction(etab_a):
    with pytest.raises(RuntimeError), contexte_tenant(etab_a.id):
        journaliser("role.modifie", Categorie.PARAMETRAGE)
        raise RuntimeError("action annulée")
    with contexte_tenant(etab_a.id):
        assert not EvenementAudit.objects.exists()


@pytest.mark.django_db(transaction=True, databases=[ALIAS_APP, ALIAS_AUDIT])
def test_hors_transaction_survit_a_l_annulation(etab_a):
    with pytest.raises(RuntimeError), contexte_tenant(etab_a.id, using=ALIAS_APP):
        evenement = journaliser("auth.connexion.echec", Categorie.CONNEXION, hors_transaction=True)
        assert evenement.seq == 1
        raise RuntimeError("vue annulée")
    with contexte_tenant(etab_a.id):
        lignes = list(EvenementAudit.objects.values_list("etablissement_id", "action"))
    assert lignes == [(etab_a.id, "auth.connexion.echec")]
    # La connexion indépendante est en alpha_app (soumise à la RLS), pas en propriétaire.
    with connections[ALIAS_AUDIT].cursor() as curseur:
        curseur.execute("SELECT current_user")
        assert curseur.fetchone()[0] == connections[ALIAS_APP].settings_dict["USER"]
    with transaction.atomic(using=ALIAS_AUDIT), connections[ALIAS_AUDIT].cursor() as curseur:
        curseur.execute("SELECT count(*) FROM evenement_audit")
        assert curseur.fetchone()[0] == 0  # sans contexte : rien de lisible


@pytest.mark.django_db(transaction=True, databases=[ALIAS_APP, ALIAS_AUDIT])
@override_settings(ROOT_URLCONF="tests.appli_test.vues")
def test_regle_des_vues_d_authentification(client):
    """§ 3.3 : une vue qui RETOURNE 401 garde l'événement ; une vue qui LÈVE le perd,
    sauf si l'événement est écrit hors transaction."""
    assert client.post("/audit/echec-401/").status_code == 401
    assert client.post("/audit/echec-exception/").status_code == 403
    assert client.post("/audit/echec-independant/").status_code == 403
    with _contexte_de_la_chaine(None):  # requêtes anonymes : chaîne de la plateforme
        conserves = set(EvenementAudit.objects.values_list("objet_libelle", flat=True))
    assert conserves == {"retour@test", "independant@test"}

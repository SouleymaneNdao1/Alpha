"""Console FYXOP (§ 5.7, § 3.8, décisions P4 et P6 ; tâche B10).

- provisionnement complet (établissement, paramètres, unité racine, rôles, invitation) ;
- double journalisation (chaîne de la plateforme ET chaîne de l'établissement, intactes) ;
- le super-admin ne lit aucun contenu : 403/404 sur TOUTES les routes d'établissement,
  statistiques réduites à des compteurs ;
- un utilisateur d'établissement reçoit 403 sur la console ;
- P4 par la console ; suspension / réactivation (réglage P6).
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from django.core import mail
from django.db import connection
from django.db.utils import ProgrammingError
from django.urls import URLPattern, URLResolver, get_resolver

from alpha.audit.models import EvenementAudit
from alpha.audit.verification import lancer_verification
from alpha.comptes import mfa
from alpha.comptes.models import (
    JetonUsageUnique,
    ObjetJeton,
    SessionAppareil,
    StatutUtilisateur,
    Utilisateur,
)
from alpha.core import contexte
from alpha.notifications.models import PreferencesNotification
from alpha.organisation.models import AffectationRole, Role, UniteOrganisationnelle
from alpha.organisation.roles_defaut import CODE_ADMINISTRATEUR, catalogue_par_defaut
from alpha.plateforme import services
from alpha.plateforme.sql import COLONNES_STATS
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import Etablissement, ParametresEtablissement
from tests.fabriques import BanqueFactory, UtilisateurFactory, contexte_plateforme
from tests.outils_admin import creer_admin
from tests.outils_auth import equiper, recharger

API = "/api/v1/plateforme"
CODE = "123456"
STATS = {
    "nb_utilisateurs_actifs",
    "nb_invites",
    "derniere_activite",
    "nb_evenements_audit_30j",
    "dernier_controle_statut",
}

pytestmark = pytest.mark.django_db


@pytest.fixture
def super_admin():
    return UtilisateurFactory(super_admin=True, email="ops@fyxop.test", prenom="Ops")


@pytest.fixture
def console(client_connecte, super_admin):
    return client_connecte(super_admin)


@pytest.fixture
def step_up_ok():
    with mock.patch.object(mfa, "verifier_step_up", return_value=(mfa.STEP_UP_OK, None)) as m:
        yield m


@pytest.fixture
def suspension_active(settings):
    settings.ALPHA_PLATEFORME_SUSPENSION_MANUELLE = True


def _corps(**champs):
    corps = {
        "code": "banque-sahel",
        "raison_sociale": "Banque du Sahel",
        "type": "BANQUE",
        "pays": "SN",
        "administrateur": {"email": "dg@sahel.test", "prenom": "Fatou", "nom": "Sarr"},
        "code_totp": CODE,
    }
    corps.update(champs)
    return corps


def _provisionner(console, capture, **champs):
    with capture(execute=True):
        r = console.post(f"{API}/etablissements", _corps(**champs), format="json")
    assert r.status_code == 201, r.content
    return r.json()


def _chaine(etablissement_id, action=None) -> list[EvenementAudit]:
    cm = contexte_plateforme() if etablissement_id is None else contexte_tenant(etablissement_id)
    with cm:
        qs = EvenementAudit.objects.filter(etablissement_id=etablissement_id).order_by("seq")
        if action:
            qs = qs.filter(action=action)
        return list(qs)


# --- Provisionnement ------------------------------------------------------------------------


def test_provisionnement_complet(
    console, super_admin, step_up_ok, django_capture_on_commit_callbacks
):
    mail.outbox.clear()
    corps = _provisionner(console, django_capture_on_commit_callbacks)
    step_up_ok.assert_called_once()
    assert step_up_ok.call_args.args == (super_admin, CODE)
    assert corps["code"] == "banque-sahel" and corps["statut"] == "ACTIF"
    assert corps["administrateur"]["statut"] == "INVITE"
    assert set(corps["stats"]) == STATS
    assert corps["stats"]["nb_invites"] == 1 and corps["stats"]["nb_utilisateurs_actifs"] == 0
    etab_id = uuid.UUID(corps["id"])

    with contexte_plateforme():
        etab = Etablissement.objects.get(pk=etab_id)
        assert etab.cree_par_id == super_admin.id and etab.type == "BANQUE"

    with contexte_tenant(etab_id):
        parametres = ParametresEtablissement.objects.get()
        assert parametres.inactivite_session_min == 15 and parametres.mdp_expiration_jours is None
        codes = set(Role.objects.values_list("code", flat=True))
        assert codes == {r.code for r in catalogue_par_defaut("BANQUE")}
        racine = UniteOrganisationnelle.objects.get()
        assert (racine.code, racine.type, racine.parent_id) == (
            services.CODE_UNITE_RACINE,
            "DIRECTION",
            None,
        )
        admin = Utilisateur.objects.get(email="dg@sahel.test")
        assert admin.statut == StatutUtilisateur.INVITE and not admin.est_super_admin
        affectation = AffectationRole.objects.get(utilisateur=admin)
        assert affectation.role.code == CODE_ADMINISTRATEUR and affectation.principal
        assert affectation.unite_id == racine.id
        assert PreferencesNotification.objects.filter(utilisateur=admin).exists()
        assert JetonUsageUnique.objects.filter(
            utilisateur=admin, objet=ObjetJeton.INVITATION, utilise_le__isnull=True
        ).exists()

    (invitation,) = [m for m in mail.outbox if "dg@sahel.test" in m.to]
    assert "Activez votre compte ALPHA" in invitation.subject


def test_double_journalisation_du_provisionnement(
    console, super_admin, step_up_ok, django_capture_on_commit_callbacks
):
    etab_id = uuid.UUID(_provisionner(console, django_capture_on_commit_callbacks)["id"])

    for action in ("plateforme.etablissement.cree", "plateforme.administrateur.invite"):
        (p,) = _chaine(None, action)
        (e,) = _chaine(etab_id, action)
        for evt in (p, e):
            assert evt.acteur_type == "SUPER_ADMIN" and evt.categorie == "SUPER_ADMIN"
            assert evt.acteur_id == super_admin.id
        assert p.apres["etablissement_code"] == "banque-sahel"
        assert p.apres["etablissement_id"] == str(etab_id)
        assert p.objet_id == e.objet_id
    actions = [evt.action for evt in _chaine(etab_id)]
    assert actions[0] == "plateforme.etablissement.cree"
    assert {"unite.creee", "utilisateur.invite"} <= set(actions)

    # Les deux chaînes restent intactes (trigger de chaînage, § 6.4).
    assert lancer_verification(None).statut == "INTACTE"
    assert lancer_verification(etab_id).statut == "INTACTE"


def test_provisionnement_conflits_avant_le_step_up(console, step_up_ok, banque):
    UtilisateurFactory(etablissement=banque, email="pris@banque.test")
    r = console.post(f"{API}/etablissements", _corps(code=banque.code), format="json")
    assert r.status_code == 409 and r.json()["code"] == "CODE_EXISTE"
    administrateur = {"email": "PRIS@banque.test", "prenom": "A", "nom": "B"}
    r = console.post(f"{API}/etablissements", _corps(administrateur=administrateur), format="json")
    assert r.status_code == 409 and r.json()["code"] == "EMAIL_EXISTE"
    step_up_ok.assert_not_called()
    with contexte_plateforme():
        assert not Etablissement.objects.filter(code="banque-sahel").exists()


@pytest.mark.parametrize(
    ("champs", "champ_en_erreur"),
    [
        ({"code": "Banque Sahel"}, "code"),
        ({"pays": "sn"}, "pays"),
        ({"type": "ASSURANCE"}, "type"),
        ({"code_totp": "12"}, "code_totp"),
        (
            {"administrateur": {"email": "pas-un-email", "prenom": "A", "nom": "B"}},
            "administrateur",
        ),
    ],
)
def test_provisionnement_validation(console, step_up_ok, champs, champ_en_erreur):
    r = console.post(f"{API}/etablissements", _corps(**champs), format="json")
    assert r.status_code == 400
    corps = r.json()
    assert corps["code"] == "VALIDATION" and champ_en_erreur in corps["details"]
    step_up_ok.assert_not_called()


def test_step_up_refuse_rien_n_est_cree(console, super_admin):
    # Super-admin sans Authenticator : le vrai verifier_step_up refuse le code.
    with mock.patch.object(mfa, "verifier_step_up", return_value=(mfa.STEP_UP_CODE_INVALIDE, None)):
        r = console.post(f"{API}/etablissements", _corps(), format="json")
    assert r.status_code == 401 and r.json()["code"] == "CODE_INVALIDE"
    with mock.patch.object(
        mfa, "verifier_step_up", return_value=(mfa.STEP_UP_TROP_DE_REQUETES, 42)
    ):
        r = console.post(f"{API}/etablissements", _corps(), format="json")
    assert r.status_code == 429 and r.json()["details"] == {"reessayer_dans_s": 42}
    with contexte_plateforme():
        assert not Etablissement.objects.filter(code="banque-sahel").exists()
    assert _chaine(None, "plateforme.etablissement.cree") == []


# --- Aucun accès au contenu -----------------------------------------------------------------


def _routes(motif_inclus) -> list[tuple[str, str]]:
    """(méthode, chemin) de toutes les routes de l'API dont le chemin vérifie le motif."""
    resultat = []

    def parcourir(motifs, prefixe=""):
        for motif in motifs:
            chemin = prefixe + str(motif.pattern)
            if isinstance(motif, URLResolver):
                parcourir(motif.url_patterns, chemin)
            elif isinstance(motif, URLPattern):
                vue = getattr(motif.callback, "view_class", None)
                if vue is None or not motif_inclus(chemin):
                    continue
                concret = "/" + chemin
                for nom, convertisseur in motif.pattern.converters.items():
                    valeur = str(uuid.uuid4()) if "UUID" in type(convertisseur).__name__ else "x"
                    concret = concret.replace(f"<{_type(convertisseur)}:{nom}>", valeur)
                    concret = concret.replace(f"<{nom}>", valeur)
                for methode in ("get", "post", "put", "patch", "delete"):
                    if hasattr(vue, methode):
                        resultat.append((methode, concret))

    parcourir(get_resolver().url_patterns)
    return resultat


def _type(convertisseur) -> str:
    return {
        "UUIDConverter": "uuid",
        "IntConverter": "int",
        "StringConverter": "str",
        "SlugConverter": "slug",
        "PathConverter": "path",
    }.get(type(convertisseur).__name__, "str")


def _route_d_etablissement(chemin: str) -> bool:
    return chemin.startswith("api/v1/") and not chemin.startswith(
        ("api/v1/plateforme/", "api/v1/auth/", "api/v1/sante/", "api/v1/schema", "api/v1/docs")
    )


ROUTES_ETABLISSEMENT = _routes(_route_d_etablissement)
ROUTES_CONSOLE = _routes(lambda c: c.startswith("api/v1/plateforme/"))


def test_les_routes_sont_bien_enumerees():
    chemins = {c for _, c in ROUTES_ETABLISSEMENT}
    for attendu in ("/api/v1/taches/", "/api/v1/moi/absences/", "/api/v1/admin/utilisateurs"):
        assert attendu in chemins, sorted(chemins)
    assert "/api/v1/audit/evenements" in chemins
    assert len(ROUTES_CONSOLE) == 8


@pytest.mark.parametrize(("methode", "chemin"), ROUTES_ETABLISSEMENT)
def test_super_admin_refuse_sur_toute_route_d_etablissement(console, methode, chemin, step_up_ok):
    r = getattr(console, methode)(chemin, {"code": CODE}, format="json")
    assert r.status_code in (403, 404), (chemin, r.status_code, r.content[:200])
    assert r.json()["code"] in ("PERMISSION_REFUSEE", "INTROUVABLE")


@pytest.mark.parametrize(("methode", "chemin"), ROUTES_CONSOLE)
def test_utilisateur_d_etablissement_refuse_sur_la_console(
    client_connecte, admin, methode, chemin, step_up_ok
):
    # Même un administrateur (toutes les permissions d'administration) est refusé.
    r = getattr(client_connecte(admin), methode)(chemin, _corps(), format="json")
    assert r.status_code == 403 and r.json()["code"] == "PERMISSION_REFUSEE"
    step_up_ok.assert_not_called()


@pytest.mark.parametrize(("methode", "chemin"), ROUTES_CONSOLE)
def test_anonyme_refuse_sur_la_console(client_api, methode, chemin):
    r = getattr(client_api, methode)(chemin, {}, format="json")
    assert r.status_code == 401 and r.json()["code"] == "NON_AUTHENTIFIE"


def test_detail_sans_contenu(console, banque, utilisateur_a):
    r = console.get(f"{API}/etablissements/{banque.id}")
    assert r.status_code == 200
    assert set(r.json()) == {
        "id",
        "code",
        "raison_sociale",
        "type",
        "statut",
        "cree_le",
        "stats",
        "pays",
        "fuseau_horaire",
        "modifie_le",
        "suspension_manuelle_disponible",
    }
    assert r.json()["suspension_manuelle_disponible"] is False
    assert console.get(f"{API}/etablissements/{uuid.uuid4()}").status_code == 404


# --- Statistiques ---------------------------------------------------------------------------


def test_statistiques_ne_renvoient_que_des_compteurs(console, banque, super_admin):
    UtilisateurFactory(etablissement=banque, email="a@banque.test")
    UtilisateurFactory(etablissement=banque, email="b@banque.test")
    UtilisateurFactory(etablissement=banque, email="c@banque.test", statut="INVITE")
    autre = BanqueFactory()
    lancer_verification(banque.id)

    r = console.get(f"{API}/etablissements")
    assert r.status_code == 200
    lignes = {ligne["code"]: ligne for ligne in r.json()}
    assert set(lignes) >= {banque.code, autre.code}
    for ligne in lignes.values():
        assert set(ligne) == {"id", "code", "raison_sociale", "type", "statut", "cree_le", "stats"}
        assert set(ligne["stats"]) == STATS
    stats = lignes[banque.code]["stats"]
    assert (stats["nb_utilisateurs_actifs"], stats["nb_invites"]) == (2, 1)
    assert stats["dernier_controle_statut"] == "INTACTE"
    assert lignes[autre.code]["stats"]["nb_utilisateurs_actifs"] == 0

    # Filtres
    assert [e["code"] for e in console.get(f"{API}/etablissements?q={autre.code}").json()] == [
        autre.code
    ]
    assert console.get(f"{API}/etablissements?statut=SUSPENDU").json() == []
    r = console.get(f"{API}/etablissements?statut=INCONNU")
    assert r.status_code == 400 and r.json()["code"] == "VALIDATION"

    # La fonction SQL elle-même : colonnes figées (aucune colonne de contenu).
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT pg_get_function_result('alpha_stats_etablissements(uuid)'::regprocedure)"
        )
        resultat = curseur.fetchone()[0]
    noms = [colonne.strip().split(" ")[0] for colonne in resultat[len("TABLE(") : -1].split(",")]
    assert tuple(noms) == COLONNES_STATS


@pytest.mark.parametrize("portee", ["tenant", "worker", "plateforme_sans_super_admin"])
def test_fonction_stats_reservee_au_super_admin(banque, utilisateur_a, portee):
    if portee == "tenant":
        cm = contexte_tenant(banque.id, utilisateur_id=utilisateur_a.id)
    elif portee == "worker":
        cm = contexte_tenant(None, scope=contexte.SCOPE_WORKER)
    else:
        cm = contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=uuid.uuid4())
    with pytest.raises(ProgrammingError, match="réservée au super-administrateur"), cm:
        services.statistiques()


def test_super_admin_ne_lit_aucune_table_d_etablissement(super_admin, banque, utilisateur_a):
    """Seconde barrière : même en contournant l'ORM, la RLS ne renvoie rien en portée platform."""
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=super_admin.id):
        assert not Utilisateur.objets_globaux.filter(etablissement_id=banque.id).exists()
        assert not Role.objets_globaux.exists()
        assert not ParametresEtablissement.objets_globaux.exists()
        assert not EvenementAudit.objects.filter(etablissement_id=banque.id).exists()


# --- Modification, administrateurs, journal, profil -------------------------------------------


def test_modifier_raison_sociale_double_journalisation(console, banque, step_up_ok):
    r = console.patch(
        f"{API}/etablissements/{banque.id}",
        {"raison_sociale": "Banque Nouvelle", "code": CODE},
        format="json",
    )
    assert r.status_code == 200 and r.json()["raison_sociale"] == "Banque Nouvelle"
    (p,) = _chaine(None, "plateforme.etablissement.modifie")
    (e,) = _chaine(banque.id, "plateforme.etablissement.modifie")
    assert p.avant == e.avant == {"raison_sociale": f"Banque {banque.code}"}
    assert e.apres == {"raison_sociale": "Banque Nouvelle"}
    r = console.patch(f"{API}/etablissements/{banque.id}", {"code": CODE}, format="json")
    assert r.status_code == 400


def test_inviter_un_administrateur(console, banque, step_up_ok, django_capture_on_commit_callbacks):
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        r = console.post(
            f"{API}/etablissements/{banque.id}/administrateurs",
            {"email": "nouveau@banque.test", "prenom": "Ndeye", "nom": "Fall", "code": CODE},
            format="json",
        )
    assert r.status_code == 201, r.content
    assert r.json()["statut"] == "INVITE"
    with contexte_tenant(banque.id):
        u = Utilisateur.objects.get(email="nouveau@banque.test")
        assert AffectationRole.objects.get(utilisateur=u).role.code == CODE_ADMINISTRATEUR
    assert _chaine(None, "plateforme.administrateur.invite")
    assert _chaine(banque.id, "plateforme.administrateur.invite")
    assert [m for m in mail.outbox if "nouveau@banque.test" in m.to]
    r = console.post(
        f"{API}/etablissements/{uuid.uuid4()}/administrateurs",
        {"email": "x@y.test", "prenom": "X", "nom": "Y", "code": CODE},
        format="json",
    )
    assert r.status_code == 404


def test_journal_de_la_plateforme_seulement(
    console, step_up_ok, django_capture_on_commit_callbacks
):
    _provisionner(console, django_capture_on_commit_callbacks)
    r = console.get(f"{API}/audit")
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()["results"]}
    assert "plateforme.etablissement.cree" in actions
    assert "unite.creee" not in actions and "utilisateur.invite" not in actions
    r = console.get(f"{API}/audit?action=plateforme.administrateur.*")
    assert {e["action"] for e in r.json()["results"]} == {"plateforme.administrateur.invite"}
    assert console.get(f"{API}/audit?periode=hier").status_code == 400


def test_profil_du_super_admin(console, super_admin):
    r = console.get(f"{API}/moi")
    assert r.status_code == 200
    assert r.json()["est_super_admin"] is True and r.json()["modules"] == ["CONSOLE"]
    assert r.json()["etablissement"] is None


# --- Décision P4 par la console ---------------------------------------------------------------


def test_p4_reinitialisation_par_la_console(
    console, banque, super_admin, step_up_ok, django_capture_on_commit_callbacks
):
    seul = equiper(creer_admin(banque, email="seul@banque.test"))
    creer_admin(banque, email="collegue@banque.test")  # administrateur sans téléphone actif
    simple = UtilisateurFactory(etablissement=banque, email="simple@banque.test")
    url = f"{API}/etablissements/{banque.id}/reinitialisation-authenticator"
    corps = {"reference_demande": "DG/2026/114", "commentaire": "Visio avec CNI", "code": CODE}

    r = console.post(url, {**corps, "email": simple.email}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "PAS_ADMINISTRATEUR"
    autre = creer_admin(BanqueFactory(roles_defaut=True), email="admin@autre.test")
    r = console.post(url, {**corps, "email": autre.email}, format="json")
    assert r.status_code == 404
    r = console.post(
        url, {**corps, "email": "seul@banque.test", "reference_demande": "  "}, format="json"
    )
    assert r.status_code == 400

    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        r = console.post(url, {**corps, "email": "SEUL@banque.test"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["statut"] == "REINITIALISE"
    assert recharger(seul.utilisateur).mfa_a_reconfigurer
    (e,) = _chaine(banque.id, "telephone.reinitialise")
    assert e.acteur_type == "SUPER_ADMIN" and e.apres["reference_demande"] == "DG/2026/114"
    (p,) = _chaine(None, "plateforme.telephone.reinitialise")
    assert p.categorie == "SUPER_ADMIN" and p.acteur_id == super_admin.id
    assert [m for m in mail.outbox if "collegue@banque.test" in m.to]
    assert [m for m in mail.outbox if "seul@banque.test" in m.to]


# --- Suspension manuelle (P6) -----------------------------------------------------------------


def test_suspension_desactivee_par_defaut(console, banque, step_up_ok):
    r = console.patch(
        f"{API}/etablissements/{banque.id}",
        {"statut": "SUSPENDU", "motif": "Impayé", "code": CODE},
        format="json",
    )
    assert r.status_code == 403 and r.json()["code"] == "SUSPENSION_MANUELLE_DESACTIVEE"
    step_up_ok.assert_not_called()
    with contexte_plateforme():
        assert Etablissement.objects.get(pk=banque.id).statut == "ACTIF"


def test_suspension_puis_reactivation(
    console, client_connecte, banque, admin, step_up_ok, suspension_active
):
    client_tenant = client_connecte(admin)
    assert client_tenant.get("/api/v1/moi").status_code == 200
    url = f"{API}/etablissements/{banque.id}"

    r = console.patch(url, {"statut": "SUSPENDU", "code": CODE}, format="json")
    assert r.status_code == 400 and "motif" in r.json()["details"]
    r = console.patch(url, {"statut": "ARCHIVE", "motif": "x", "code": CODE}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "STATUT_INVALIDE"

    r = console.patch(url, {"statut": "SUSPENDU", "motif": "Impayé", "code": CODE}, format="json")
    assert r.status_code == 200 and r.json()["statut"] == "SUSPENDU"
    assert r.json()["suspension_manuelle_disponible"] is True
    with contexte_tenant(banque.id):
        assert not SessionAppareil.objects.filter(revoque_le__isnull=True).exists()
    assert client_tenant.get("/api/v1/moi").status_code in (401, 403)
    assert client_connecte(admin).get("/api/v1/moi").json()["code"] == "ETABLISSEMENT_SUSPENDU"
    (p,) = _chaine(None, "plateforme.etablissement.statut")
    (e,) = _chaine(banque.id, "plateforme.etablissement.statut")
    assert e.avant == {"statut": "ACTIF"}
    assert e.apres == {"statut": "SUSPENDU", "motif": "Impayé", "sessions_revoquees": 1}
    assert p.apres["etablissement_code"] == banque.code

    r = console.patch(url, {"statut": "ACTIF", "motif": "Régularisé", "code": CODE}, format="json")
    assert r.status_code == 200 and r.json()["statut"] == "ACTIF"
    assert client_connecte(admin).get("/api/v1/moi").status_code == 200
    assert len(_chaine(banque.id, "plateforme.etablissement.statut")) == 2
    assert len(_chaine(None, "plateforme.etablissement.statut")) == 2


def test_services_refusent_hors_portee_plateforme(banque, admin):
    from alpha.core.erreurs import ErreurApi

    with contexte_tenant(banque.id, utilisateur_id=admin.id), pytest.raises(ErreurApi) as erreur:
        services.modifier_etablissement(banque.id, par=admin, raison_sociale="X")
    assert erreur.value.status_code == 403

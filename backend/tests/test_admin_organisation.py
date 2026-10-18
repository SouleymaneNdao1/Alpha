"""API d'administration : catalogue des rôles, habilitations, unités (tâche B7, § 5.5)."""

from __future__ import annotations

import pytest

from alpha.organisation.codes_permission import CodePermission
from alpha.organisation.models import Role, UniteOrganisationnelle
from alpha.organisation.roles_defaut import CODE_ADMINISTRATEUR

from .fabriques import AffectationRoleFactory, UniteOrganisationnelleFactory, UtilisateurFactory
from .outils_admin import API, avec_permissions, evenements, relire, role

pytestmark = pytest.mark.django_db


# --- Rôles --------------------------------------------------------------------------------------


def test_catalogue_des_roles(client_admin, banque, admin):
    reponse = client_admin.get(f"{API}/roles")
    assert reponse.status_code == 200
    roles = reponse.json()
    assert roles[0]["code"] == CODE_ADMINISTRATEUR
    assert roles[0]["est_systeme"] is True
    assert roles[0]["nb_titulaires"] == 1 and roles[0]["vacant"] is False
    analyste = next(r for r in roles if r["code"] == "analyste-credit")
    assert analyste["permissions"] == [] and analyste["vacant"] is True
    assert set(analyste) == {
        "id", "code", "libelle", "description", "permissions", "est_systeme",
        "actif", "ordre", "nb_titulaires", "vacant",
    }  # fmt: skip

    juriste = role(banque, "juriste")
    client_admin.post(f"{API}/roles/{juriste.id}/desactiver")
    actifs = client_admin.get(f"{API}/roles?actif=true").json()
    inactifs = client_admin.get(f"{API}/roles?actif=false").json()
    assert "juriste" not in [r["code"] for r in actifs]
    assert [r["code"] for r in inactifs] == ["juriste"]
    assert client_admin.get(f"{API}/roles?actif=peut-etre").status_code == 400


def test_lecture_des_roles_ouverte_a_admin_utilisateurs(client_connecte, banque):
    gestionnaire = avec_permissions(banque, CodePermission.ADMIN_UTILISATEURS)
    client = client_connecte(gestionnaire)
    assert client.get(f"{API}/roles").status_code == 200
    assert client.post(f"{API}/roles", {"libelle": "X"}, format="json").status_code == 403
    assert client.get(f"{API}/permissions").status_code == 403
    assert client.get(f"{API}/unites").status_code == 200
    assert client.post(f"{API}/unites", {}, format="json").status_code == 403


def test_creer_role_et_audit(client_admin, banque):
    reponse = client_admin.post(
        f"{API}/roles",
        {
            "libelle": "Chargé de conformité",
            "description": "Contrôle de conformité",
            "permissions": ["audit.lecture"],
            "ordre": 40,
        },
        format="json",
    )
    assert reponse.status_code == 201, reponse.json()
    corps = reponse.json()
    assert corps["code"] == "charge-de-conformite"
    assert corps["permissions"] == ["audit.lecture"] and corps["est_systeme"] is False
    (evt,) = evenements(banque, "role.cree")
    assert evt.categorie == "PARAMETRAGE"
    assert evt.apres["libelle"] == "Chargé de conformité"
    assert evt.apres["permissions"] == ["audit.lecture"]


def test_creer_role_conflits_et_validation(client_admin):
    doublon = client_admin.post(f"{API}/roles", {"libelle": "analyste CRÉDIT"}, format="json")
    assert doublon.status_code == 409 and doublon.json()["code"] == "LIBELLE_EXISTE"
    code = client_admin.post(f"{API}/roles", {"libelle": "Autre", "code": "daf"}, format="json")
    assert code.status_code == 409 and code.json()["code"] == "CODE_EXISTE"
    inconnue = client_admin.post(
        f"{API}/roles", {"libelle": "Y", "permissions": ["admin.tout"]}, format="json"
    )
    assert inconnue.status_code == 400 and "permissions" in inconnue.json()["details"]
    mauvais_code = client_admin.post(
        f"{API}/roles", {"libelle": "Z", "code": "Pas Bon"}, format="json"
    )
    assert mauvais_code.status_code == 400


def test_modifier_role_habilitations(client_admin, banque):
    daf = role(banque, "daf")
    reponse = client_admin.patch(
        f"{API}/roles/{daf.id}",
        {"permissions": ["audit.lecture", "audit.export"], "libelle": "Directeur financier"},
        format="json",
    )
    assert reponse.status_code == 200
    assert reponse.json()["permissions"] == ["audit.export", "audit.lecture"]
    (evt,) = evenements(banque, "role.modifie")
    assert evt.avant == {"libelle": "DAF", "permissions": []}
    assert evt.apres == {
        "libelle": "Directeur financier",
        "permissions": ["audit.export", "audit.lecture"],
    }
    # Aucun changement : pas d'événement.
    client_admin.patch(f"{API}/roles/{daf.id}", {"libelle": "Directeur financier"}, format="json")
    assert len(evenements(banque, "role.modifie")) == 1
    conflit = client_admin.patch(f"{API}/roles/{daf.id}", {"libelle": "juriste"}, format="json")
    assert conflit.status_code == 409


def test_role_systeme_protege(client_admin, banque):
    systeme = role(banque, CODE_ADMINISTRATEUR)
    retrait = client_admin.patch(
        f"{API}/roles/{systeme.id}", {"permissions": ["admin.roles"]}, format="json"
    )
    assert retrait.status_code == 409 and retrait.json()["code"] == "ROLE_SYSTEME"
    assert client_admin.post(f"{API}/roles/{systeme.id}/desactiver").json()["code"] == (
        "ROLE_SYSTEME"
    )
    # Ajouter une permission ou renommer reste possible.
    ajout = client_admin.patch(
        f"{API}/roles/{systeme.id}",
        {"permissions": [*systeme.permissions, "audit.lecture"], "libelle": "Administrateur"},
        format="json",
    )
    assert ajout.status_code == 200
    assert relire(Role, banque, id=systeme.id).permissions.count("audit.lecture") == 1


def test_desactiver_puis_activer_role(client_admin, banque):
    juriste = role(banque, "juriste")
    reponse = client_admin.post(f"{API}/roles/{juriste.id}/desactiver")
    assert reponse.status_code == 200 and reponse.json()["actif"] is False
    reponse = client_admin.post(f"{API}/roles/{juriste.id}/activer")
    assert reponse.status_code == 200 and reponse.json()["actif"] is True
    assert [e.action for e in evenements(banque) if e.action.startswith("role.")] == [
        "role.desactive",
        "role.active",
    ]


def test_role_desactive_n_ouvre_plus_de_droits(client_connecte, client_admin, banque):
    auditeur = avec_permissions(banque, CodePermission.ADMIN_ROLES)
    client = client_connecte(auditeur)
    assert client.get(f"{API}/permissions").status_code == 200
    son_role = relire(Role, banque, affectations__utilisateur=auditeur)
    client_admin.post(f"{API}/roles/{son_role.id}/desactiver")
    assert client.get(f"{API}/permissions").status_code == 403


def test_liste_des_permissions(client_admin):
    reponse = client_admin.get(f"{API}/permissions")
    assert reponse.status_code == 200
    codes = [p["code"] for p in reponse.json()]
    assert codes == list(CodePermission.values)
    premiere = reponse.json()[0]
    assert premiere["libelle"] == "Utilisateurs" and premiere["description"]


# --- Unités ------------------------------------------------------------------------------------


def test_arbre_des_unites(client_admin, banque):
    direction = UniteOrganisationnelleFactory(
        etablissement=banque, type="DIRECTION", code="DE", libelle="Direction des engagements"
    )
    UniteOrganisationnelleFactory(
        etablissement=banque, code="CP", libelle="Crédit particuliers", parent=direction
    )
    UniteOrganisationnelleFactory(etablissement=banque, type="AGENCE", libelle="Agence Thiès")

    reponse = client_admin.get(f"{API}/unites")
    assert reponse.status_code == 200
    arbre = reponse.json()
    assert [n["libelle"] for n in arbre] == ["Agence Thiès", "Direction des engagements"]
    enfants = arbre[1]["enfants"]
    assert [e["code"] for e in enfants] == ["CP"] and enfants[0]["enfants"] == []
    assert enfants[0]["parent_id"] == str(direction.id)


def test_creer_et_modifier_unite(client_admin, banque):
    reponse = client_admin.post(
        f"{API}/unites",
        {"type": "DIRECTION", "code": "DAF", "libelle": "Direction administrative et financière"},
        format="json",
    )
    assert reponse.status_code == 201
    direction_id = reponse.json()["id"]
    reponse = client_admin.post(
        f"{API}/unites",
        {"type": "SERVICE", "code": "COMPTA", "libelle": "Comptabilité", "parent_id": direction_id},
        format="json",
    )
    assert reponse.status_code == 201 and reponse.json()["parent_id"] == direction_id
    service_id = reponse.json()["id"]

    doublon = client_admin.post(
        f"{API}/unites", {"type": "SERVICE", "code": "COMPTA", "libelle": "X"}, format="json"
    )
    assert doublon.status_code == 409 and doublon.json()["code"] == "CODE_EXISTE"

    reponse = client_admin.patch(
        f"{API}/unites/{service_id}",
        {"libelle": "Comptabilité générale", "actif": False},
        format="json",
    )
    assert reponse.status_code == 200 and reponse.json()["actif"] is False
    # Cycle : la direction ne peut pas devenir l'enfant de son propre service.
    cycle = client_admin.patch(
        f"{API}/unites/{direction_id}", {"parent_id": service_id}, format="json"
    )
    assert cycle.status_code == 400 and "parent_id" in cycle.json()["details"]
    lui_meme = client_admin.patch(
        f"{API}/unites/{direction_id}", {"parent_id": direction_id}, format="json"
    )
    assert lui_meme.status_code == 400

    assert len(evenements(banque, "unite.creee")) == 2
    (evt,) = evenements(banque, "unite.modifiee")
    assert evt.avant == {"libelle": "Comptabilité", "actif": True}
    assert evt.apres == {"libelle": "Comptabilité générale", "actif": False}
    assert relire(UniteOrganisationnelle, banque, id=service_id).actif is False


def test_unite_desactivee_refusee_pour_une_affectation(client_admin, banque):
    unite = UniteOrganisationnelleFactory(etablissement=banque, actif=False)
    awa = UtilisateurFactory(etablissement=banque)
    AffectationRoleFactory(utilisateur=awa, role=role(banque, "daf"), principal=True)
    reponse = client_admin.post(
        f"{API}/utilisateurs/{awa.id}/affectations",
        {"role_id": str(role(banque, "juriste").id), "unite_id": str(unite.id)},
        format="json",
    )
    assert reponse.status_code == 400 and "unite_id" in reponse.json()["details"]


def test_validation_unite(client_admin):
    reponse = client_admin.post(
        f"{API}/unites", {"type": "BUREAU", "code": " ", "libelle": "X"}, format="json"
    )
    assert reponse.status_code == 400
    assert {"type", "code"} <= set(reponse.json()["details"])

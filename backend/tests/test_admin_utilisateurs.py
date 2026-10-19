"""API d'administration des comptes (tâche B7, § 4.3, § 5.5)."""

from __future__ import annotations

import datetime
from unittest import mock

import pytest
from django.utils import timezone

from alpha.comptes import raccordements
from alpha.comptes.models import JetonUsageUnique, ObjetJeton, StatutUtilisateur, Utilisateur
from alpha.comptes.resolution import empreinte_jeton
from alpha.organisation.models import AffectationRole
from alpha.organisation.roles_defaut import CODE_ADMINISTRATEUR
from alpha.tenancy.contexte import contexte_tenant

from .fabriques import (
    AffectationRoleFactory,
    UniteOrganisationnelleFactory,
    UtilisateurFactory,
)
from .outils_admin import API, creer_admin, evenements, relire, role

pytestmark = pytest.mark.django_db


def _invitation(banque, **champs):
    corps = {
        "email": "c.badiane@banque.test",
        "prenom": "Cheikh",
        "nom": "Badiane",
        "role_id": str(role(banque, "analyste-credit").id),
    }
    corps.update(champs)
    return corps


# --- Liste et fiche -------------------------------------------------------------------------


def test_liste_utilisateurs_format_et_filtres(client_admin, banque, admin):
    unite = UniteOrganisationnelleFactory(etablissement=banque, libelle="Dakar-Plateau")
    awa = UtilisateurFactory(etablissement=banque, prenom="Awa", nom="Diop", email="a.diop@b.test")
    AffectationRoleFactory(
        utilisateur=awa, role=role(banque, "analyste-credit"), unite=unite, principal=True
    )
    UtilisateurFactory(etablissement=banque, prenom="Moussa", nom="Sow", statut="SUSPENDU")

    reponse = client_admin.get(f"{API}/utilisateurs")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["count"] == 3
    assert set(corps) == {"count", "next", "previous", "results"}
    ligne = next(r for r in corps["results"] if r["email"] == "a.diop@b.test")
    assert ligne == {
        "id": str(awa.id),
        "prenom": "Awa",
        "nom": "Diop",
        "initiales": "AD",
        "email": "a.diop@b.test",
        "role_principal": "Analyste crédit",
        "perimetre": "Dakar-Plateau",
        "authenticator": "NON_CONFIGUREE",
        "derniere_connexion": None,
        "statut": "ACTIF",
        "verrouille": False,
    }
    ligne_admin = next(r for r in corps["results"] if r["id"] == str(admin.id))
    assert ligne_admin["perimetre"] == "Tout l'établissement"

    assert client_admin.get(f"{API}/utilisateurs?q=dio").json()["count"] == 1
    assert client_admin.get(f"{API}/utilisateurs?statut=SUSPENDU").json()["count"] == 1
    role_id = role(banque, "analyste-credit").id
    filtre = client_admin.get(f"{API}/utilisateurs?role_id={role_id}").json()
    assert [r["id"] for r in filtre["results"]] == [str(awa.id)]
    pagine = client_admin.get(f"{API}/utilisateurs?taille=2&page=2").json()
    assert len(pagine["results"]) == 1 and pagine["previous"]
    assert client_admin.get(f"{API}/utilisateurs?statut=XX").json()["code"] == "VALIDATION"
    assert client_admin.get(f"{API}/utilisateurs?role_id=abc").status_code == 400


def test_fiche_utilisateur(client_admin, admin):
    reponse = client_admin.get(f"{API}/utilisateurs/{admin.id}")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["email"] == admin.email
    assert corps["affectations"][0]["role"]["libelle"] == "Administrateur ALPHA"
    assert corps["affectations"][0]["unite"] is None
    # B5 : la session ouverte par client_admin (session d'appareil réelle) est listée.
    (session,) = corps["sessions_actives"]
    assert session["methode_mfa"] == "TOTP" and session["ip"] == "127.0.0.1"
    assert corps["signalement"] is None


def test_super_admin_exclu_de_la_liste(client_admin):
    UtilisateurFactory(super_admin=True)
    emails = [r["email"] for r in client_admin.get(f"{API}/utilisateurs").json()["results"]]
    assert not any(e.endswith("@fyxop.test") for e in emails)


# --- Invitation -----------------------------------------------------------------------------


def test_invitation_cree_compte_affectation_jeton_et_audit(
    client_admin, banque, admin, django_capture_on_commit_callbacks
):
    unite = UniteOrganisationnelleFactory(etablissement=banque)
    with (
        mock.patch.object(raccordements, "envoyer_invitation") as envoi,
        django_capture_on_commit_callbacks(execute=True),
    ):
        reponse = client_admin.post(
            f"{API}/utilisateurs",
            _invitation(
                banque,
                unite_id=str(unite.id),
                responsable_id=str(admin.id),
                telephone_mobile="+221770000001",
            ),
            format="json",
        )
    assert reponse.status_code == 201, reponse.json()
    corps = reponse.json()
    assert corps["statut"] == "INVITE"
    assert corps["role_principal"] == "Analyste crédit"
    assert corps["responsable"] == {"id": str(admin.id), "nom": "Abdou Kane"}

    with contexte_tenant(banque.id):
        invite = Utilisateur.objects.get(id=corps["id"])
        assert not invite.has_usable_password()
        assert invite.cree_par_id == admin.id
        affectation = AffectationRole.objects.get(utilisateur=invite)
        assert affectation.principal and affectation.unite_id == unite.id
        jeton = JetonUsageUnique.objects.get(utilisateur=invite)
        assert jeton.objet == ObjetJeton.INVITATION
        delai = jeton.expire_le - timezone.now()
        assert datetime.timedelta(hours=71) < delai <= datetime.timedelta(hours=72)

    # L'e-mail (B6) reçoit le jeton en clair, après le commit ; seule l'empreinte est en base.
    envoi.assert_called_once()
    etab_id, utilisateur_id, clair, _expire_le = envoi.call_args.args
    assert (etab_id, utilisateur_id) == (banque.id, invite.id)
    assert empreinte_jeton(clair) == jeton.jeton_hash
    assert clair not in str(corps)

    (evt,) = evenements(banque, "utilisateur.invite")
    assert evt.acteur_id == admin.id and evt.acteur_libelle == "Abdou Kane"
    assert evt.categorie == "PARAMETRAGE"
    assert evt.apres["email"] == "c.badiane@banque.test"
    assert evt.apres["statut"] == "INVITE"
    assert evt.apres["affectation"]["role"] == str(affectation.role_id)
    assert clair not in evt.payload_canonique


def test_invitation_role_hors_catalogue(client_admin, banque, autre_banque):
    role_b = role(autre_banque, "analyste-credit")
    reponse = client_admin.post(
        f"{API}/utilisateurs", _invitation(banque, role_id=str(role_b.id)), format="json"
    )
    assert reponse.status_code == 400
    assert reponse.json()["code"] == "ROLE_HORS_CATALOGUE"

    inactif = role(banque, "juriste")
    with contexte_tenant(banque.id):
        inactif.actif = False
        inactif.save()
    reponse = client_admin.post(
        f"{API}/utilisateurs", _invitation(banque, role_id=str(inactif.id)), format="json"
    )
    assert reponse.json()["code"] == "ROLE_HORS_CATALOGUE"


def test_invitation_email_deja_utilise_meme_dans_un_autre_etablissement(
    client_admin, banque, autre_banque
):
    UtilisateurFactory(etablissement=autre_banque, email="pris@ailleurs.test")
    reponse = client_admin.post(
        f"{API}/utilisateurs", _invitation(banque, email="PRIS@ailleurs.test"), format="json"
    )
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "EMAIL_EXISTE"


def test_invitation_validation(client_admin, banque, autre_banque):
    unite_b = UniteOrganisationnelleFactory(etablissement=autre_banque)
    reponse = client_admin.post(
        f"{API}/utilisateurs",
        _invitation(banque, email="pas-un-email", telephone_mobile="770000000"),
        format="json",
    )
    assert reponse.status_code == 400
    details = reponse.json()["details"]
    assert {"email", "telephone_mobile"} <= set(details)
    reponse = client_admin.post(
        f"{API}/utilisateurs", _invitation(banque, unite_id=str(unite_b.id)), format="json"
    )
    assert reponse.json()["details"] == {"unite_id": ["Unité inconnue."]}
    assert evenements(banque, "utilisateur.invite") == []


def test_validite_invitation_selon_parametres(client_admin, banque):
    from alpha.tenancy.models import ParametresEtablissement

    with contexte_tenant(banque.id):
        ParametresEtablissement.objects.update(validite_invitation_h=24)
    reponse = client_admin.post(f"{API}/utilisateurs", _invitation(banque), format="json")
    jeton = relire(JetonUsageUnique, banque, utilisateur_id=reponse.json()["id"])
    assert jeton.expire_le - timezone.now() <= datetime.timedelta(hours=24)


def test_renvoyer_invitation(client_admin, banque):
    invite_id = client_admin.post(f"{API}/utilisateurs", _invitation(banque), format="json").json()[
        "id"
    ]
    ancien = relire(JetonUsageUnique, banque, utilisateur_id=invite_id)

    reponse = client_admin.post(f"{API}/utilisateurs/{invite_id}/renvoyer-invitation")
    assert reponse.status_code == 202
    with contexte_tenant(banque.id):
        jetons = JetonUsageUnique.objects.filter(utilisateur_id=invite_id)
        assert jetons.count() == 2
        assert jetons.get(id=ancien.id).annule_le is not None
        assert jetons.filter(annule_le__isnull=True).count() == 1
    assert len(evenements(banque, "utilisateur.invite")) == 2


def test_renvoyer_invitation_refusee_si_compte_actif(client_admin, admin):
    reponse = client_admin.post(f"{API}/utilisateurs/{admin.id}/renvoyer-invitation")
    assert reponse.status_code == 409
    assert reponse.json()["code"] == "UTILISATEUR_NON_INVITE"


# --- Modification -----------------------------------------------------------------------------


def test_modifier_utilisateur_et_audit(client_admin, banque, admin):
    awa = UtilisateurFactory(etablissement=banque, prenom="Awa", nom="Diop")
    reponse = client_admin.patch(
        f"{API}/utilisateurs/{awa.id}",
        {
            "nom": "Diop-Ndiaye",
            "telephone_mobile": "+221771234567",
            "responsable_id": str(admin.id),
        },
        format="json",
    )
    assert reponse.status_code == 200
    assert reponse.json()["nom"] == "Diop-Ndiaye"
    (evt,) = evenements(banque, "utilisateur.modifie")
    assert evt.avant == {"nom": "Diop", "telephone_mobile": None, "responsable": None}
    assert evt.apres == {
        "nom": "Diop-Ndiaye",
        "telephone_mobile": "+221771234567",
        "responsable": str(admin.id),
    }


def test_modifier_refuse_email_et_responsable_invalide(client_admin, banque, autre_banque, admin):
    b = UtilisateurFactory(etablissement=autre_banque)
    reponse = client_admin.patch(
        f"{API}/utilisateurs/{admin.id}", {"responsable_id": str(admin.id)}, format="json"
    )
    assert reponse.status_code == 400
    reponse = client_admin.patch(
        f"{API}/utilisateurs/{admin.id}", {"responsable_id": str(b.id)}, format="json"
    )
    assert reponse.json()["details"] == {"responsable_id": ["Utilisateur inconnu."]}
    # L'e-mail n'est pas modifiable : champ ignoré.
    client_admin.patch(f"{API}/utilisateurs/{admin.id}", {"email": "x@y.test"}, format="json")
    assert relire(Utilisateur, banque, id=admin.id).email == admin.email


# --- Affectations -----------------------------------------------------------------------------


def test_ajouter_affectation_principale_et_terminer(client_admin, banque, admin):
    awa = UtilisateurFactory(etablissement=banque)
    AffectationRoleFactory(utilisateur=awa, role=role(banque, "agent-saisie"), principal=True)
    daf = role(banque, "daf")

    reponse = client_admin.post(
        f"{API}/utilisateurs/{awa.id}/affectations",
        {"role_id": str(daf.id), "principal": True},
        format="json",
    )
    assert reponse.status_code == 201
    affectation_id = reponse.json()["id"]
    fiche = client_admin.get(f"{API}/utilisateurs/{awa.id}").json()
    assert fiche["role_principal"] == "DAF"
    assert [a["principal"] for a in fiche["affectations"]] == [True, False]

    doublon = client_admin.post(
        f"{API}/utilisateurs/{awa.id}/affectations", {"role_id": str(daf.id)}, format="json"
    )
    assert doublon.status_code == 409 and doublon.json()["code"] == "AFFECTATION_EXISTE"

    reponse = client_admin.post(f"{API}/affectations/{affectation_id}/terminer")
    assert reponse.status_code == 200
    assert reponse.json()["fin"] == timezone.localdate().isoformat()
    fiche = client_admin.get(f"{API}/utilisateurs/{awa.id}").json()
    assert [a["role"]["libelle"] for a in fiche["affectations"]] == ["Agent de saisie"]
    deja = client_admin.post(f"{API}/affectations/{affectation_id}/terminer")
    assert deja.status_code == 409

    assert len(evenements(banque, "affectation.creee")) == 1
    (fin,) = evenements(banque, "affectation.terminee")
    assert fin.avant["fin"] is None and fin.apres["fin"] == timezone.localdate().isoformat()


def test_affectation_terminee_retire_les_droits_aussitot(client_connecte, client_admin, banque):
    second = creer_admin(banque, email="second@banque.test")
    client_second = client_connecte(second)
    assert client_second.get(f"{API}/utilisateurs").status_code == 200
    with contexte_tenant(banque.id):
        affectation = AffectationRole.objects.get(utilisateur=second)
    assert client_admin.post(f"{API}/affectations/{affectation.id}/terminer").status_code == 200
    assert client_second.get(f"{API}/utilisateurs").status_code == 403


# --- Suspension, réactivation, déverrouillage, sessions -----------------------------------------


def test_suspendre_puis_reactiver(client_admin, banque):
    awa = UtilisateurFactory(etablissement=banque)
    with contexte_tenant(banque.id):
        JetonUsageUnique.objects.create(
            utilisateur=awa,
            objet=ObjetJeton.REINIT_MDP,
            jeton_hash="a" * 64,
            expire_le=timezone.now() + datetime.timedelta(minutes=30),
        )
    with mock.patch.object(raccordements, "revoquer_sessions", return_value=2) as revocation:
        reponse = client_admin.post(
            f"{API}/utilisateurs/{awa.id}/suspendre", {"motif": "Départ"}, format="json"
        )
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "SUSPENDU"
    assert reponse.json()["sessions_revoquees"] == 2
    revocation.assert_called_once_with(awa.id, motif="REVOCATION_ADMIN")
    assert relire(JetonUsageUnique, banque, utilisateur=awa).annule_le is not None
    (evt,) = evenements(banque, "utilisateur.suspendu")
    assert evt.categorie == "SECURITE" and evt.detail == "Motif : Départ"
    assert (evt.avant, evt.apres) == ({"statut": "ACTIF"}, {"statut": "SUSPENDU"})

    deja = client_admin.post(
        f"{API}/utilisateurs/{awa.id}/suspendre", {"motif": "x"}, format="json"
    )
    assert deja.status_code == 409 and deja.json()["code"] == "STATUT_INVALIDE"

    reponse = client_admin.post(f"{API}/utilisateurs/{awa.id}/reactiver")
    assert reponse.status_code == 200 and reponse.json()["statut"] == "ACTIF"
    assert len(evenements(banque, "utilisateur.reactive")) == 1
    assert client_admin.post(f"{API}/utilisateurs/{awa.id}/reactiver").status_code == 409


def test_suspension_exige_un_motif(client_admin, banque):
    awa = UtilisateurFactory(etablissement=banque)
    reponse = client_admin.post(f"{API}/utilisateurs/{awa.id}/suspendre", {}, format="json")
    assert reponse.status_code == 400 and "motif" in reponse.json()["details"]


def test_utilisateur_suspendu_perd_l_acces(client_connecte, client_admin, banque):
    second = creer_admin(banque, email="second@banque.test")
    client_second = client_connecte(second)
    client_admin.post(f"{API}/utilisateurs/{second.id}/suspendre", {"motif": "x"}, format="json")
    assert client_second.get(f"{API}/utilisateurs").status_code in (401, 403)


def test_deverrouiller(client_admin, banque):
    awa = UtilisateurFactory(
        etablissement=banque,
        echecs_connexion=5,
        verrouille_jusqua=timezone.now() + datetime.timedelta(minutes=10),
        verrouillages_24h=3,
        bloque_par_admin=True,
    )
    ligne = client_admin.get(f"{API}/utilisateurs?q={awa.email}").json()["results"][0]
    assert ligne["verrouille"] is True

    reponse = client_admin.post(f"{API}/utilisateurs/{awa.id}/deverrouiller")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["verrouille"] is False
    assert (corps["echecs_connexion"], corps["bloque_par_admin"]) == (0, False)
    relu = relire(Utilisateur, banque, id=awa.id)
    assert (relu.verrouille_jusqua, relu.verrouillages_24h) == (None, 0)
    (evt,) = evenements(banque, "utilisateur.deverrouille")
    assert evt.avant["bloque_par_admin"] is True and evt.apres["verrouillages_24h"] == 0


def test_revoquer_sessions(client_admin, banque):
    awa = UtilisateurFactory(etablissement=banque)
    with mock.patch.object(raccordements, "revoquer_sessions", return_value=3):
        reponse = client_admin.post(f"{API}/utilisateurs/{awa.id}/sessions/revoquer")
    assert reponse.status_code == 200 and reponse.json() == {"revoquees": 3}
    (evt,) = evenements(banque, "auth.session.revoquee")
    assert evt.apres == {"revoquees": 3}


# --- Historique ---------------------------------------------------------------------------------


def test_historique_des_actions_sur_les_comptes(client_admin, banque):
    awa = UtilisateurFactory(etablissement=banque)
    client_admin.post(f"{API}/utilisateurs/{awa.id}/deverrouiller")
    client_admin.patch(f"{API}/utilisateurs/{awa.id}", {"prenom": "Aïssatou"}, format="json")
    client_admin.post(f"{API}/utilisateurs/{awa.id}/suspendre", {"motif": "x"}, format="json")
    client_admin.post(f"{API}/roles", {"libelle": "Hors historique"}, format="json")

    reponse = client_admin.get(f"{API}/utilisateurs/historique")
    assert reponse.status_code == 200
    actions = [e["action"] for e in reponse.json()]
    assert actions == ["utilisateur.suspendu", "utilisateur.modifie", "utilisateur.deverrouille"]
    premier = reponse.json()[0]
    assert premier["action_libelle"] == "Suspension"
    assert premier["acteur_libelle"] == "Abdou Kane"
    assert len(premier["hash"]) == 64 and premier["hash_court"] == (
        f"{premier['hash'][:4]}…{premier['hash'][-4:]}"
    )
    assert len(client_admin.get(f"{API}/utilisateurs/historique?limite=1").json()) == 1
    assert client_admin.get(f"{API}/utilisateurs/historique?limite=0").status_code == 400


# --- Fermé par défaut ----------------------------------------------------------------------------


def test_utilisateur_invite_est_cree_sans_acces(client_admin, banque, client_connecte):
    corps = _invitation(banque, role_id=str(role(banque, CODE_ADMINISTRATEUR).id))
    invite_id = client_admin.post(f"{API}/utilisateurs", corps, format="json").json()["id"]
    invite = relire(Utilisateur, banque, id=invite_id)
    assert invite.statut == StatutUtilisateur.INVITE
    # Même titulaire du rôle administrateur, un compte non activé n'a aucun droit.
    reponse = client_connecte(invite).get(f"{API}/utilisateurs")
    assert reponse.status_code in (401, 403)

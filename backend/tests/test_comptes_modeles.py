"""Modèles et contraintes des comptes et de l'organisation (tâche B3).

Connexion ``default`` (alpha_app, montage T1) : on vérifie ici les contraintes SQL et
la première barrière (managers, ``save``), sous le contexte de l'établissement concerné ;
la RLS elle-même est vérifiée dans ``test_comptes_rls.py``. Une contrainte que la RLS
masque (elle refuse avant) est vérifiée en plus par l'alias ``proprietaire``.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, ProgrammingError, connection, transaction

from alpha.comptes.models import StatutUtilisateur, Utilisateur
from alpha.core import contexte
from alpha.organisation.codes_permission import (
    PERMISSIONS_ADMIN,
    PERMISSIONS_AUDIT,
    CodePermission,
    codes_inconnus,
    valider_codes,
)
from alpha.organisation.models import AffectationRole, Role, UniteOrganisationnelle
from alpha.organisation.pouvoirs import Pouvoirs, parents_des_unites
from alpha.organisation.roles_defaut import (
    CODE_ADMINISTRATEUR,
    CODE_AUDITEUR,
    semer_roles_par_defaut,
)
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.exceptions import TenantNonDefini, ViolationTenant
from alpha.tenancy.models import Etablissement

from .bd import ALIAS_PROPRIETAIRE, BASES_PROPRIETAIRE
from .conftest import creer_etablissement
from .outils_comptes import creer_jeton, creer_super_admin, creer_utilisateur

pytestmark = pytest.mark.django_db


def _immediat():
    """Les clés « même établissement » sont différées : on les contrôle tout de suite."""
    with connection.cursor() as curseur:
        curseur.execute("SET CONSTRAINTS ALL IMMEDIATE")


def _echoue(motif: str):
    return pytest.raises(IntegrityError, match=motif)


# --- Utilisateur ------------------------------------------------------------------------


def test_modele_utilisateur_configure():
    assert settings.AUTH_USER_MODEL == "comptes.Utilisateur"
    assert get_user_model() is Utilisateur
    assert Utilisateur.USERNAME_FIELD == "email"
    with connection.cursor() as curseur:
        curseur.execute(
            "SELECT data_type, udt_name FROM information_schema.columns "
            "WHERE table_name = 'utilisateur' AND column_name = 'email'"
        )
        assert curseur.fetchone()[1] == "citext"


def test_mot_de_passe_argon2_et_invite_inutilisable(etab_a):
    invite = creer_utilisateur(etab_a, "invite@banque-a.test", statut=StatutUtilisateur.INVITE)
    assert not invite.has_usable_password()
    assert not invite.is_active
    actif = creer_utilisateur(etab_a, "actif@banque-a.test", password="Tr3s-l0ng-secret!")
    assert actif.password.startswith("argon2$argon2id$")
    assert actif.check_password("Tr3s-l0ng-secret!")
    assert actif.is_active


def test_email_unique_insensible_a_la_casse_meme_etablissement(etab_a):
    creer_utilisateur(etab_a, "m.sow@banque-a.test")
    with _echoue("utilisateur_email_key"), transaction.atomic():
        creer_utilisateur(etab_a, "M.Sow@Banque-A.test")


def test_email_unique_sur_toute_la_plateforme(etab_a, etab_b):
    # P1 : une même adresse ne peut pas exister dans deux établissements.
    creer_utilisateur(etab_a, "m.sow@exemple.test")
    with _echoue("utilisateur_email_key"), transaction.atomic():
        creer_utilisateur(etab_b, "M.SOW@exemple.test")
    with _echoue("utilisateur_email_key"), transaction.atomic():
        creer_super_admin("m.sow@EXEMPLE.test")


def test_recherche_par_email_insensible_a_la_casse(etab_a):
    u = creer_utilisateur(etab_a, "Awa.Diop@banque-a.test")
    with contexte_tenant(etab_a.id):
        assert Utilisateur.objects.get(email="awa.diop@BANQUE-A.TEST") == u
        assert Utilisateur.objects.get_by_natural_key("AWA.DIOP@banque-a.test") == u


def test_un_seul_etablissement_par_utilisateur(etab_a, etab_b):
    u = creer_utilisateur(etab_a, "a@banque-a.test")
    # Le contexte B ne voit pas l'utilisateur de A et ne peut pas l'écrire.
    with contexte_tenant(etab_b.id):
        assert not Utilisateur.objects.filter(pk=u.pk).exists()
        with pytest.raises(ViolationTenant):
            u.save()
    # Un utilisateur d'établissement a toujours un établissement, un super-admin jamais.
    with _echoue("utilisateur_super_admin_sans_etab"), contexte_tenant(etab_a.id):
        Utilisateur.objets_globaux.filter(pk=u.pk).update(est_super_admin=True)
    # Retirer l'établissement : la RLS refuse avant même la contrainte…
    with (
        pytest.raises(ProgrammingError, match="row-level security"),
        contexte_tenant(etab_a.id),
    ):
        Utilisateur.objets_globaux.filter(pk=u.pk).update(etablissement=None)


@pytest.mark.django_db(transaction=True, databases=BASES_PROPRIETAIRE)
def test_contrainte_super_admin_sans_etablissement_hors_rls(etab_a):
    # … et la contrainte SQL tient seule, même pour le propriétaire (BYPASSRLS).
    u = creer_utilisateur(etab_a, "a@banque-a.test")
    with _echoue("utilisateur_super_admin_sans_etab"), transaction.atomic(using=ALIAS_PROPRIETAIRE):
        Utilisateur.objets_globaux.using(ALIAS_PROPRIETAIRE).filter(pk=u.pk).update(
            etablissement=None
        )


def test_manager_utilisateur_echoue_ferme_sans_contexte(etab_a):
    creer_utilisateur(etab_a, "a@banque-a.test")
    with pytest.raises(TenantNonDefini):
        list(Utilisateur.objects.all())
    with pytest.raises(TenantNonDefini):
        Utilisateur(email="x@x.test", prenom="X", nom="Y").save()


def test_portee_plateforme_ne_voit_que_les_super_admins(etab_a):
    creer_utilisateur(etab_a, "a@banque-a.test")
    sa = creer_super_admin()
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM):
        assert list(Utilisateur.objects.all()) == [sa]
    with contexte_tenant(etab_a.id):
        assert not Utilisateur.objects.filter(pk=sa.pk).exists()


def test_super_admin_ne_s_ecrit_qu_en_portee_plateforme(etab_a):
    with contexte_tenant(etab_a.id), pytest.raises(ViolationTenant):
        Utilisateur(email="sa@fyxop.test", prenom="S", nom="A", est_super_admin=True).save()
    with pytest.raises(NotImplementedError):
        Utilisateur.objects.create_superuser("sa@fyxop.test", "S", "A")


def test_responsable_du_meme_etablissement(etab_a, etab_b):
    chef_a = creer_utilisateur(etab_a, "chef@banque-a.test")
    chef_b = creer_utilisateur(etab_b, "chef@sfd-b.test")
    creer_utilisateur(etab_a, "collab@banque-a.test", responsable=chef_a)
    with _echoue("utilisateur_responsable_id_meme_etab"), transaction.atomic():
        creer_utilisateur(etab_a, "collab2@banque-a.test", responsable_id=chef_b.id)
        _immediat()


def test_contraintes_utilisateur(etab_a):
    with _echoue("utilisateur_telephone_e164"), transaction.atomic():
        creer_utilisateur(etab_a, "t@banque-a.test", telephone_mobile="77 123 45 67")
    with _echoue("utilisateur_statut_valide"), transaction.atomic():
        creer_utilisateur(etab_a, "s@banque-a.test", statut="INCONNU")
    u = creer_utilisateur(etab_a, "ok@banque-a.test", telephone_mobile="+221771234567")
    with _echoue("utilisateur_responsable_different"), contexte_tenant(etab_a.id):
        Utilisateur.objets_globaux.filter(pk=u.pk).update(responsable=u)


def test_cree_par_etablissement(etab_a):
    sa = creer_super_admin()
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM):
        Etablissement.objects.filter(pk=etab_a.pk).update(cree_par=sa)
    with contexte_tenant(etab_a.id):
        etab_a.refresh_from_db()
    assert etab_a.cree_par_id == sa.id


# --- Jetons ------------------------------------------------------------------------------


def test_jeton_empreinte_et_contexte(etab_a, etab_b):
    u = creer_utilisateur(etab_a, "a@banque-a.test")
    _, jeton = creer_jeton(u)
    assert jeton.etablissement_id == etab_a.id
    assert len(jeton.jeton_hash) == 64
    with contexte_tenant(etab_b.id):
        assert not type(jeton).objects.filter(pk=jeton.pk).exists()
    with _echoue("jeton_hash_format"), contexte_tenant(etab_a.id):
        type(jeton).objets_globaux.filter(pk=jeton.pk).update(jeton_hash="Z" * 64)


def test_jeton_d_un_utilisateur_d_un_autre_etablissement_refuse(etab_a, etab_b):
    u_b = creer_utilisateur(etab_b, "b@sfd-b.test")
    from alpha.comptes.models import JetonUsageUnique

    with (
        _echoue("jeton_usage_unique_utilisateur_id_meme_etab"),
        transaction.atomic(),
        contexte_tenant(etab_a.id),
    ):
        JetonUsageUnique.objects.create(
            utilisateur_id=u_b.id,
            objet="INVITATION",
            jeton_hash="a" * 64,
            expire_le=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
        )
        _immediat()


def test_jeton_super_admin_en_portee_plateforme():
    sa = creer_super_admin()
    _, jeton = creer_jeton(sa)
    assert jeton.etablissement_id is None
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=sa.id):
        assert type(jeton).objects.get() == jeton
    with contexte_tenant(None, scope=contexte.SCOPE_PLATFORM, utilisateur_id=uuid.uuid4()):
        assert not type(jeton).objects.exists()


# --- Codes de permission -----------------------------------------------------------------


def test_codes_de_permission_du_document():
    assert set(CodePermission.values) == {
        "admin.utilisateurs",
        "admin.roles",
        "admin.organisation",
        "admin.securite",
        "admin.absences",
        "audit.lecture",
        "audit.export",
    }
    assert set(PERMISSIONS_ADMIN) == {c for c in CodePermission.values if c.startswith("admin.")}
    assert set(PERMISSIONS_AUDIT) == {"audit.lecture", "audit.export"}
    assert codes_inconnus(["audit.lecture", "workflow.signer"]) == ["workflow.signer"]
    valider_codes(PERMISSIONS_ADMIN)


def test_code_de_permission_inconnu_refuse_en_base(etab_a):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        valider_codes(["admin.tout"])
    with contexte_tenant(etab_a.id):
        with _echoue("role_permissions_connues"), transaction.atomic():
            Role.objects.create(code="pirate", libelle="Pirate", permissions=["admin.tout"])
        role = Role(code="pirate", libelle="Pirate", permissions=["admin.tout"])
        with pytest.raises(ValidationError):
            role.full_clean()


def test_role_libelle_unique_insensible_a_la_casse(etab_a, etab_b):
    with contexte_tenant(etab_a.id):
        Role.objects.create(code="caissier", libelle="Caissier")
        with _echoue("role_libelle_uniq"), transaction.atomic():
            Role.objects.create(code="caissier-2", libelle="CAISSIER")
        with _echoue("role_code_uniq"), transaction.atomic():
            Role.objects.create(code="caissier", libelle="Autre")
        with _echoue("role_code_format"), transaction.atomic():
            Role.objects.create(code="Code Invalide", libelle="Invalide")
    with contexte_tenant(etab_b.id):  # même code et libellé dans un autre établissement
        Role.objects.create(code="caissier", libelle="Caissier")


# --- Rôles par défaut --------------------------------------------------------------------


def _roles(etab) -> dict[str, Role]:
    with contexte_tenant(etab.id):
        semer_roles_par_defaut(etab)
        return {r.code: r for r in Role.objects.all()}


def test_roles_par_defaut_banque():
    etab = creer_etablissement("banque-x", type="BANQUE")
    roles = _roles(etab)
    assert len(roles) == 16
    admin, auditeur = roles[CODE_ADMINISTRATEUR], roles[CODE_AUDITEUR]
    assert admin.libelle == "Administrateur ALPHA" and admin.est_systeme
    assert set(admin.permissions) == set(PERMISSIONS_ADMIN)
    assert auditeur.libelle == "Auditeur interne"
    assert set(auditeur.permissions) == {"audit.lecture", "audit.export"}
    for code in ("analyste-credit", "membre-comite", "juriste", "directeur-general"):
        assert roles[code].permissions == [] and not roles[code].est_systeme
    assert "directrice-commerciale" not in roles
    assert [r.code for r in sorted(roles.values(), key=lambda r: r.ordre)][:2] == [
        CODE_ADMINISTRATEUR,
        CODE_AUDITEUR,
    ]


def test_roles_par_defaut_pme_et_sfd():
    pme = _roles(creer_etablissement("pme-x", type="PME"))
    assert len(pme) == 12
    assert {"directrice-commerciale", "comptable-fournisseurs", "controleur-gestion"} <= set(pme)
    assert "analyste-credit" not in pme and "juriste" not in pme
    assert pme[CODE_ADMINISTRATEUR].est_systeme
    sfd = _roles(creer_etablissement("sfd-x", type="SFD"))
    assert "analyste-credit" in sfd and len(sfd) == 16


def test_roles_par_defaut_idempotents_et_sous_contexte(etab_a, etab_b):
    with contexte_tenant(etab_a.id):
        assert len(semer_roles_par_defaut(etab_a)) == 16
        assert semer_roles_par_defaut(etab_a) == []
        with pytest.raises(ViolationTenant):
            semer_roles_par_defaut(etab_b)


# --- Unités, affectations, pouvoirs (P5) ------------------------------------------------


@pytest.fixture
def organisation_a(etab_a):
    awa = creer_utilisateur(etab_a, "awa@banque-a.test")
    moussa = creer_utilisateur(etab_a, "moussa@banque-a.test", prenom="Moussa", nom="Sow")
    with contexte_tenant(etab_a.id):
        semer_roles_par_defaut(etab_a)
        roles = {r.code: r for r in Role.objects.all()}
        direction = UniteOrganisationnelle.objects.create(
            type="DIRECTION", code="dir-engagements", libelle="Direction des engagements"
        )
        agence = UniteOrganisationnelle.objects.create(
            type="AGENCE", code="dakar-plateau", libelle="Dakar-Plateau", parent=direction
        )
    return awa, moussa, roles, direction, agence


def test_affectations_contraintes(etab_a, etab_b, organisation_a):
    awa, _, roles, direction, agence = organisation_a
    with contexte_tenant(etab_a.id):
        AffectationRole.objects.create(
            utilisateur=awa, role=roles["analyste-credit"], principal=True
        )
        with _echoue("affectation_principale_unique"), transaction.atomic():
            AffectationRole.objects.create(utilisateur=awa, role=roles["juriste"], principal=True)
        with _echoue("affectation_en_cours_unique"), transaction.atomic():
            AffectationRole.objects.create(utilisateur=awa, role=roles["analyste-credit"])
        # Cumul autorisé (ex. DAF et membre du comité), et même rôle sur une autre unité.
        AffectationRole.objects.create(utilisateur=awa, role=roles["membre-comite"])
        AffectationRole.objects.create(utilisateur=awa, role=roles["analyste-credit"], unite=agence)
        with _echoue("affectation_fin_apres_debut"), transaction.atomic():
            AffectationRole.objects.create(
                utilisateur=awa,
                role=roles["juriste"],
                debut=datetime.date(2026, 10, 1),
                fin=datetime.date(2026, 9, 1),
            )
    with contexte_tenant(etab_b.id):
        role_b = Role.objects.create(code="intrus", libelle="Intrus")
    with contexte_tenant(etab_a.id):
        with _echoue("affectation_role_role_id_meme_etab"), transaction.atomic():
            AffectationRole.objects.create(utilisateur=awa, role_id=role_b.id)
            _immediat()
        with _echoue("unite_parent_different"), transaction.atomic():
            UniteOrganisationnelle.objects.filter(pk=direction.pk).update(parent=direction)


def test_affectations_actives(etab_a, organisation_a):
    awa, _, roles, _, _ = organisation_a
    with contexte_tenant(etab_a.id):
        AffectationRole.objects.create(
            utilisateur=awa,
            role=roles["juriste"],
            debut=datetime.date(2026, 1, 1),
            fin=datetime.date(2026, 6, 30),
        )
        AffectationRole.objects.create(
            utilisateur=awa, role=roles["daf"], debut=datetime.date(2026, 1, 1)
        )
        assert {
            a.role.code for a in AffectationRole.objects.actives(datetime.date(2026, 3, 1))
        } == {
            "juriste",
            "daf",
        }
        assert {
            a.role.code for a in AffectationRole.objects.actives(datetime.date(2026, 7, 1))
        } == {"daf"}


def test_pouvoirs_comparables_p5(etab_a, organisation_a):
    awa, moussa, roles, direction, agence = organisation_a
    with contexte_tenant(etab_a.id):
        AffectationRole.objects.create(utilisateur=awa, role=roles["analyste-credit"], unite=agence)
        AffectationRole.objects.create(utilisateur=awa, role=roles[CODE_AUDITEUR])
        parents = parents_des_unites()

        p_awa = Pouvoirs.de(awa.id)
        assert p_awa.permissions == {"audit.lecture", "audit.export"}
        # Moussa sans rôle ne couvre pas Awa.
        assert not Pouvoirs.de(moussa.id).couvre(p_awa, parents)

        # Même rôle sur l'unité parente : couvre l'agence ; mais pas les permissions d'audit.
        AffectationRole.objects.create(
            utilisateur=moussa, role=roles["analyste-credit"], unite=direction
        )
        assert not Pouvoirs.de(moussa.id).couvre(p_awa, parents)
        AffectationRole.objects.create(utilisateur=moussa, role=roles[CODE_AUDITEUR])
        p_moussa = Pouvoirs.de(moussa.id)
        assert p_moussa.couvre(p_awa, parents)
        # L'inverse est faux : l'agence ne couvre pas toute la direction.
        assert not p_awa.couvre(p_moussa, parents)
        # Délégation limitée à un rôle.
        assert Pouvoirs.de(awa.id, role_id=roles["analyste-credit"].id).habilitations == {
            (roles["analyste-credit"].id, agence.id)
        }
        # Un rôle désactivé ne donne plus de pouvoir.
        Role.objects.filter(pk=roles[CODE_AUDITEUR].pk).update(actif=False)
        assert Pouvoirs.de(moussa.id).permissions == frozenset()

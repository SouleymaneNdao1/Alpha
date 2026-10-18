"""Factories factory-boy (tâche T1) : chaque objet est créé dans SON contexte tenant.

Les tests tournent sous alpha_app (RLS active) : une ligne d'établissement ne peut
être écrite que sous ``contexte_tenant(etablissement.id)``, un établissement ou un
super-administrateur que sous la portée « platform ». Les factories posent ce
contexte elles-mêmes, comme le ferait le provisionnement (B10) :

    banque = BanqueFactory()          # + ses ParametresEtablissement (idem PMEFactory, SFDFactory)
    pme = PMEFactory(parametres__inactivite_session_min=30)
    admin = UtilisateurFactory(etablissement=banque, password="Tr3s-l0ng-secret!")
    role = RoleFactory(etablissement=banque, permissions=["admin.utilisateurs"])
    AffectationRoleFactory(utilisateur=admin, role=role, principal=True)

L'objet renvoyé est utilisable hors contexte (attributs déjà chargés) ; toute
nouvelle requête ORM sur un modèle tenant exige de reposer le contexte.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from alpha.comptes.models import StatutUtilisateur, Utilisateur
from alpha.core import contexte
from alpha.organisation.models import AffectationRole, Role, TypeUnite, UniteOrganisationnelle
from alpha.organisation.roles_defaut import semer_roles_par_defaut
from alpha.tenancy.contexte import contexte_tenant
from alpha.tenancy.models import (
    Etablissement,
    ParametresEtablissement,
    TypeEtablissement,
)

MOT_DE_PASSE_TEST = "Tr3s-l0ng-secret!"


def contexte_plateforme():
    """Portée « platform » (super-admin FYXOP) : établissements et super-administrateurs."""
    return contexte_tenant(None, scope=contexte.SCOPE_PLATFORM)


class _FactoryTenant(DjangoModelFactory):
    """Base : création sous ``contexte_tenant(etablissement.id)``."""

    class Meta:
        abstract = True

    etablissement = factory.SubFactory("tests.fabriques.EtablissementFactory")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        etablissement = kwargs["etablissement"]
        with contexte_tenant(etablissement.id):
            return model_class.objects.create(*args, **kwargs)


# --- Établissements -----------------------------------------------------------------------


class ParametresEtablissementFactory(_FactoryTenant):
    """Réglages d'un établissement (valeurs par défaut validées, P2 et P3)."""

    class Meta:
        model = ParametresEtablissement

    etablissement = factory.SubFactory("tests.fabriques.EtablissementFactory", parametres=False)


class EtablissementFactory(DjangoModelFactory):
    """Établissement créé en portée « platform », avec ses paramètres.

    - ``parametres=False`` : pas de ``ParametresEtablissement`` ;
    - ``parametres__<champ>=valeur`` : réglage particulier ;
    - ``roles_defaut=True`` : catalogue de rôles par défaut semé (§ 2.3).
    """

    class Meta:
        model = Etablissement
        # Pas de save() hors contexte après les post_generation.
        skip_postgeneration_save = True

    code = factory.Sequence(lambda n: f"etab-{n}")
    raison_sociale = factory.LazyAttribute(lambda o: f"Établissement {o.code}")
    type = TypeEtablissement.BANQUE

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        with contexte_plateforme():
            return model_class.objects.create(*args, **kwargs)

    @factory.post_generation
    def parametres(obj, create, extracted, **kwargs):
        if not create or extracted is False:
            return
        ParametresEtablissementFactory(etablissement=obj, **kwargs)

    @factory.post_generation
    def roles_defaut(obj, create, extracted, **kwargs):
        if create and extracted:
            with contexte_tenant(obj.id):
                semer_roles_par_defaut(obj)


class BanqueFactory(EtablissementFactory):
    code = factory.Sequence(lambda n: f"banque-{n}")
    raison_sociale = factory.LazyAttribute(lambda o: f"Banque {o.code}")
    type = TypeEtablissement.BANQUE


class PMEFactory(EtablissementFactory):
    code = factory.Sequence(lambda n: f"pme-{n}")
    raison_sociale = factory.LazyAttribute(lambda o: f"PME {o.code}")
    type = TypeEtablissement.PME


class SFDFactory(EtablissementFactory):
    code = factory.Sequence(lambda n: f"sfd-{n}")
    raison_sociale = factory.LazyAttribute(lambda o: f"SFD {o.code}")
    type = TypeEtablissement.SFD


# --- Comptes --------------------------------------------------------------------------------


class UtilisateurFactory(DjangoModelFactory):
    """Utilisateur ACTIF d'un établissement (mot de passe inutilisable par défaut).

    ``password=MOT_DE_PASSE_TEST`` pour un compte qui peut se connecter ;
    ``UtilisateurFactory(super_admin=True)`` pour un super-administrateur FYXOP.
    """

    class Meta:
        model = Utilisateur

    class Params:
        super_admin = factory.Trait(
            etablissement=None,
            est_super_admin=True,
            email=factory.Sequence(lambda n: f"admin{n}@fyxop.test"),
            prenom="Admin",
            nom="FYXOP",
        )

    etablissement = factory.SubFactory(EtablissementFactory)
    email = factory.LazyAttributeSequence(
        lambda o, n: f"utilisateur{n}@{o.etablissement.code if o.etablissement else 'fyxop'}.test"
    )
    prenom = "Awa"
    nom = "Diop"
    statut = StatutUtilisateur.ACTIF
    password = None

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        etablissement = kwargs.get("etablissement")
        if kwargs.get("est_super_admin"):
            cm = contexte_tenant(None, scope=contexte.SCOPE_PLATFORM)
        else:
            cm = contexte_tenant(etablissement.id)
        with cm:
            return model_class.objects.create_user(*args, **kwargs)


# --- Organisation ---------------------------------------------------------------------------


class UniteOrganisationnelleFactory(_FactoryTenant):
    class Meta:
        model = UniteOrganisationnelle

    type = TypeUnite.SERVICE
    code = factory.Sequence(lambda n: f"unite-{n}")
    libelle = factory.LazyAttribute(lambda o: f"Service {o.code}")
    parent = None


class RoleFactory(_FactoryTenant):
    class Meta:
        model = Role

    code = factory.Sequence(lambda n: f"role-{n}")
    libelle = factory.LazyAttribute(lambda o: f"Rôle {o.code}")
    permissions = factory.LazyFunction(list)


class AffectationRoleFactory(_FactoryTenant):
    """Habilitation ; utilisateur et rôle sont créés dans le MÊME établissement."""

    class Meta:
        model = AffectationRole

    etablissement = factory.LazyAttribute(lambda o: o.utilisateur.etablissement)
    utilisateur = factory.SubFactory(UtilisateurFactory)
    role = factory.SubFactory(RoleFactory, etablissement=factory.SelfAttribute("..etablissement"))
    unite = None

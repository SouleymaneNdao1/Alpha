"""Libellés français des actions du journal d'audit (architecture § 5.1, § 6.1).

Un code inconnu (action ajoutée plus tard) s'affiche tel quel : le journal n'est jamais
tronqué faute de libellé.
"""

from __future__ import annotations

LIBELLES_ACTIONS: dict[str, str] = {
    "auth.connexion.succes": "Connexion",
    "auth.connexion.echec": "Échec de connexion",
    "auth.verrouillage": "Verrouillage du compte",
    "auth.deconnexion": "Déconnexion",
    "auth.session.expiree": "Session expirée",
    "auth.session.revoquee": "Révocation des sessions",
    "auth.step_up.echec": "Échec de confirmation par code",
    "auth.mdp.oubli_demande": "Mot de passe oublié (demande)",
    "auth.mdp.reinitialise": "Réinitialisation du mot de passe",
    "auth.mdp.modifie": "Modification du mot de passe",
    "mfa.active": "Activation de l'Authenticator",
    "mfa.change": "Changement d'Authenticator",
    "mfa.reenrole": "Réenrôlement de l'Authenticator",
    "mfa.codes_regeneres": "Nouveaux codes de secours",
    "mfa.code_secours_utilise": "Code de secours utilisé",
    "securite.connexion_inhabituelle": "Connexion inhabituelle",
    "telephone.signale": "Téléphone perdu (signalement)",
    "telephone.reinitialise": "Téléphone perdu (réinitialisation)",
    "telephone.annule": "Téléphone perdu (signalement annulé)",
    "utilisateur.invite": "Invitation",
    "utilisateur.active": "Activation du compte",
    "utilisateur.modifie": "Modification du compte",
    "utilisateur.suspendu": "Suspension",
    "utilisateur.reactive": "Réactivation",
    "utilisateur.deverrouille": "Déverrouillage",
    "affectation.creee": "Attribution d'un rôle",
    "affectation.terminee": "Retrait d'un rôle",
    "role.cree": "Création d'un rôle",
    "role.modifie": "Modification d'un rôle",
    "role.desactive": "Désactivation d'un rôle",
    "role.active": "Activation d'un rôle",
    "unite.creee": "Création d'une unité",
    "unite.modifiee": "Modification d'une unité",
    "absence.soumise": "Absence soumise",
    "absence.validee": "Absence validée",
    "absence.refusee": "Absence refusée",
    "absence.annulee": "Absence annulée",
    "delegation.active": "Délégation activée",
    "delegation.terminee": "Délégation terminée",
    "delegation.revoquee": "Délégation révoquée",
    "tache.ouverte": "Tâche ouverte",
    "tache.reassignee": "Tâche réassignée",
    "tache.terminee": "Tâche terminée",
    "tache.annulee": "Tâche annulée",
    "parametres.securite.modifies": "Modification des paramètres de sécurité",
    "audit.export": "Export du journal",
    "audit.controle": "Contrôle d'intégrité lancé",
    "audit.chaine_rompue": "Chaîne d'audit rompue",
    "plateforme.etablissement.cree": "Création de l'établissement",
    "plateforme.etablissement.modifie": "Modification de l'établissement",
    "plateforme.etablissement.statut": "Changement de statut de l'établissement",
    "plateforme.administrateur.invite": "Invitation d'un administrateur",
    "plateforme.telephone.reinitialise": "Réinitialisation de l'Authenticator par FYXOP",
    "plateforme.super_admin.cree": "Création d'un super-administrateur",
    "plateforme.super_admin.lien_renvoye": "Nouveau lien de configuration (super-administrateur)",
}

#: Actions comptées dans « Actions d'administration » (indicateurs, § 5.6) : comptes,
#: affectations, rôles, unités, paramètres de sécurité et téléphones perdus.
PREFIXES_ADMINISTRATION = (
    "utilisateur.",
    "affectation.",
    "role.",
    "unite.",
    "parametres.",
    "telephone.",
)


def libelle_action(action: str) -> str:
    return LIBELLES_ACTIONS.get(action, action)

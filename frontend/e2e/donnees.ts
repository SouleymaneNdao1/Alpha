import type { Page, Route } from "@playwright/test";
import { json, MOI, ouvrirSession, simulerApi, type Gestionnaire } from "./aide";

/** Moi complet d'un utilisateur d'établissement (rôle DAF), personnalisable. */
export function moiAvec(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { ...MOI, ...extra };
}

export const MODULES_TOUS = ["COMPTE", "ADMINISTRATION", "AUDIT"];
export const PERMISSIONS_TOUTES = ["admin.utilisateurs", "admin.roles", "audit.lecture", "audit.export"];

export const MOI_COMPLET = moiAvec({ modules: MODULES_TOUS, permissions: PERMISSIONS_TOUTES });

export const MOI_SUPER_ADMIN = moiAvec({
  etablissement: null,
  role_principal: null,
  modules: ["CONSOLE"],
  est_super_admin: true,
});

/** Ouvre la session et simule `/auth/session` + compteurs ; `autres` complète ou remplace. */
export async function ouvrirEtSimuler(page: Page, moi: unknown, autres: Record<string, Gestionnaire> = {}) {
  await ouvrirSession(page);
  return simulerApi(page, {
    "GET /auth/session": (_a, route) => json(route, moi),
    "GET /taches/compteurs": (_a, route) => json(route, COMPTEURS),
    ...autres,
  });
}

export const COMPTEURS = {
  total: 9,
  par_groupe: { EN_RETARD: 1, AUJOURDHUI: 3, CETTE_SEMAINE: 3, PLUS_TARD: 2 },
  par_module: { INTERNE: 3, CREDIT: 4, RH: 2 },
};

export function tache(id: number, groupe: string, module: string, extra: Record<string, unknown> = {}) {
  const libelles: Record<string, string> = { INTERNE: "Décisions internes", CREDIT: "Crédit", RH: "Ressources humaines" };
  return {
    id: `00000000-0000-4000-8000-${String(id).padStart(12, "0")}`,
    module,
    module_libelle: libelles[module] ?? module,
    reference: `REF-${id}`,
    titre: `Dossier numéro ${id}`,
    sous_titre: `Sous-titre ${id}`,
    montant: null,
    devise: "XOF",
    action: "DECIDER",
    action_libelle: "Décider",
    type_echeance: "ECHEANCE",
    echeance: "2026-10-20T10:00:00Z",
    groupe,
    retard_jours: groupe === "EN_RETARD" ? 1 : null,
    lien: `/dossiers/${id}`,
    par_delegation_de: null,
    cree_le: "2026-10-10T08:00:00Z",
    ...extra,
  };
}

export const TACHES = [
  tache(1, "EN_RETARD", "CREDIT", { montant: "14600000.00", titre: "Demande de crédit Sow & Fils", echeance: "2026-10-18T10:00:00Z" }),
  tache(2, "AUJOURDHUI", "INTERNE", { action: "SIGNER", action_libelle: "Signer", par_delegation_de: { id: "u1", nom: "Awa Diop" } }),
  tache(3, "AUJOURDHUI", "RH", { action: "VALIDER", action_libelle: "Valider" }),
  tache(4, "CETTE_SEMAINE", "CREDIT"),
  tache(5, "PLUS_TARD", "INTERNE", { action: "TRAITER", action_libelle: "Traiter", echeance: null }),
];

export function page(results: unknown[], next: string | null = null) {
  return { count: results.length, next, previous: null, results };
}

export function paramsDe(route: Route): URLSearchParams {
  return new URL(route.request().url()).searchParams;
}

export function evenement(seq: number, extra: Record<string, unknown> = {}) {
  return {
    seq,
    horodatage: "2026-10-10T20:31:07Z",
    acteur_type: "UTILISATEUR",
    acteur_libelle: `Utilisateur ${seq}`,
    categorie: "CONNEXION",
    action: "auth.connexion.succes",
    action_libelle: "Connexion",
    objet_type: "utilisateur",
    objet_id: String(seq),
    objet_libelle: `Objet ${seq}`,
    avant: null,
    apres: null,
    detail: `Détail ${seq}`,
    ip: "10.0.0.1",
    hash: `a41f${String(seq).padStart(8, "0")}9c2e`,
    hash_court: "a41f…9c2e",
    ...extra,
  };
}

export const INDICATEURS = {
  evenements_aujourdhui: 128,
  connexions_echouees_24h: 4,
  actions_administration_24h: 7,
  dernier_controle: {
    id: "c1",
    statut: "INTACTE",
    lance_le: "2026-10-18T02:00:00Z",
    termine_le: "2026-10-18T02:01:00Z",
    dernier_seq: 500,
    premier_seq_invalide: null,
    message: "",
  },
  controle_en_cours: false,
};

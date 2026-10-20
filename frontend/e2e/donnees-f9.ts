import type { Route } from "@playwright/test";
import { json } from "./aide";
import { MOI_SUPER_ADMIN, ouvrirEtSimuler } from "./donnees";
import type { Page } from "@playwright/test";
import type { Gestionnaire } from "./aide";

export { MOI_SUPER_ADMIN };

export function stats(extra: Record<string, unknown> = {}) {
  return {
    nb_utilisateurs_actifs: 12,
    nb_invites: 1,
    derniere_activite: "2026-10-18T15:42:00Z",
    nb_evenements_audit_30j: 840,
    dernier_controle_statut: "INTACTE",
    ...extra,
  };
}

export function etablissement(n: number, extra: Record<string, unknown> = {}) {
  return {
    id: `aaaaaaaa-0000-4000-8000-${String(n).padStart(12, "0")}`,
    code: `etab-${n}`,
    raison_sociale: `Établissement ${n}`,
    type: "BANQUE",
    statut: "ACTIF",
    cree_le: "2026-09-01T09:00:00Z",
    stats: stats(),
    ...extra,
  };
}

export function detail(n: number, extra: Record<string, unknown> = {}) {
  return {
    ...etablissement(n),
    pays: "SN",
    fuseau_horaire: "Africa/Dakar",
    modifie_le: "2026-10-01T10:00:00Z",
    suspension_manuelle_disponible: false,
    ...extra,
  };
}

export const ETABLISSEMENTS = [
  etablissement(1, { code: "banque-atlantique-sn", raison_sociale: "Banque Atlantique Sénégal", stats: stats({ nb_utilisateurs_actifs: 48, nb_invites: 2 }) }),
  etablissement(2, {
    code: "sfd-kaolack",
    raison_sociale: "SFD Kaolack Épargne",
    type: "SFD",
    statut: "LECTURE_SEULE",
    stats: stats({ nb_utilisateurs_actifs: 9, nb_invites: 0, dernier_controle_statut: "ROMPUE" }),
  }),
  etablissement(3, {
    code: "pme-sow-fils",
    raison_sociale: "Sow & Fils SARL",
    type: "PME",
    stats: stats({ nb_utilisateurs_actifs: 0, nb_invites: 1, derniere_activite: null, dernier_controle_statut: null }),
  }),
];

/** Ouvre une session de super-administrateur et simule la liste des établissements (filtrée par `q`). */
export async function ouvrirConsole(page: Page, autres: Record<string, Gestionnaire> = {}, moi: unknown = MOI_SUPER_ADMIN) {
  return ouvrirEtSimuler(page, moi, {
    "GET /plateforme/etablissements": (_a, route) => {
      const q = (new URL(route.request().url()).searchParams.get("q") ?? "").toLowerCase();
      return json(route, ETABLISSEMENTS.filter((e) => !q || e.code.includes(q) || e.raison_sociale.toLowerCase().includes(q)));
    },
    ...autres,
  });
}

export const repondre = (corps: unknown, status = 200) => (_a: unknown, route: Route) => json(route, corps, status);

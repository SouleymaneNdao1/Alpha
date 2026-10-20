import { absence } from "./donnees-f67";

/** Données simulées de l'écran F7 « Délégations » (B13). */

export const ID_ABS = "cccccccc-0000-4000-8000-000000000001";
export const ID_DEL = "eeeeeeee-0000-4000-8000-000000000001";
export const AWA = { id: "aaaaaaaa-1111-4000-8000-000000000001", nom: "Awa Diop", role_principal: "Analyste crédit", pouvoirs_suffisants: null };
export const CHEIKH = { id: "aaaaaaaa-1111-4000-8000-000000000002", nom: "Cheikh Badiane", role_principal: "Analyste crédit", pouvoirs_suffisants: true };
export const FATOU = { id: "aaaaaaaa-1111-4000-8000-000000000003", nom: "Fatou Ndiaye", role_principal: null, pouvoirs_suffisants: false };

export function absenceAdmin(statut: string, extra: Record<string, unknown> = {}) {
  return { ...absence(statut), demandeur: { id: AWA.id, nom: "Awa Diop" }, valideur: { id: "v1", nom: "Mamadou Sow" }, peut_decider: statut === "SOUMISE", ...extra };
}

export function delegation(statut: string, extra: Record<string, unknown> = {}) {
  return {
    id: ID_DEL,
    origine: "ABSENCE",
    absence_id: ID_ABS,
    delegant: { id: AWA.id, nom: "Awa Diop" },
    delegataire: { id: CHEIKH.id, nom: "Cheikh Badiane" },
    role: null,
    debut: "2026-11-02T00:00:00Z",
    fin: "2026-11-06T23:59:00Z",
    statut,
    effective: false,
    activee_le: null,
    terminee_le: null,
    cree_le: "2026-10-19T08:00:00Z",
    ...extra,
  };
}


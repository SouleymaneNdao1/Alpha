import { Badge } from "@/components/ui";
import type { StatsEtablissement, StatutEtablissement, TypeEtablissement } from "@/lib/api/hooks/plateforme";

export const TYPES_ETABLISSEMENT: ReadonlyArray<{ valeur: TypeEtablissement; libelle: string }> = [
  { valeur: "BANQUE", libelle: "Banque" },
  { valeur: "SFD", libelle: "SFD" },
  { valeur: "PME", libelle: "PME" },
];

export const libelleType = (t: string) => TYPES_ETABLISSEMENT.find((x) => x.valeur === t)?.libelle ?? t;

export function BadgeStatutEtablissement({ statut }: { statut: StatutEtablissement }) {
  switch (statut) {
    case "ACTIF":
      return <Badge ton="vert" point>Actif</Badge>;
    case "LECTURE_SEULE":
      return <Badge ton="ambre" point>Lecture seule</Badge>;
    case "SUSPENDU":
      return <Badge ton="rouge" point>Suspendu</Badge>;
    default:
      return <Badge ton="gris" point>Archivé</Badge>;
  }
}

export function BadgeIntegrite({ statut }: { statut: StatsEtablissement["dernier_controle_statut"] }) {
  if (statut === "INTACTE") return <Badge ton="vert">Intacte</Badge>;
  if (statut === "ROMPUE") return <Badge ton="rouge">Rompue</Badge>;
  if (statut === "ERREUR") return <Badge ton="ambre">Contrôle en erreur</Badge>;
  return <Badge ton="gris">Non contrôlée</Badge>;
}

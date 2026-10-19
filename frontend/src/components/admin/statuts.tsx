import { Badge } from "@/components/ui";
import type { UtilisateurListe } from "@/lib/api/hooks/admin";

export function BadgeStatutUtilisateur({ u }: { u: Pick<UtilisateurListe, "statut" | "verrouille"> }) {
  if (u.statut === "ACTIF" && u.verrouille) return <Badge ton="ambre" point>Verrouillé</Badge>;
  switch (u.statut) {
    case "ACTIF":
      return <Badge ton="vert" point>Actif</Badge>;
    case "INVITE":
      return <Badge ton="bleu" point>Invité</Badge>;
    case "SUSPENDU":
      return <Badge ton="rouge" point>Suspendu</Badge>;
    default:
      return <Badge ton="gris" point>Désactivé</Badge>;
  }
}

export function BadgeAuthenticator({ etat }: { etat: UtilisateurListe["authenticator"] }) {
  if (etat === "ACTIVE") return <Badge ton="vert">Activée</Badge>;
  if (etat === "SUSPENDUE") return <Badge ton="rouge">Suspendue</Badge>;
  return <Badge ton="gris">Non configurée</Badge>;
}

export function Pastille({ initiales }: { initiales: string }) {
  return (
    <span aria-hidden="true" className="inline-flex h-8 w-8 flex-none items-center justify-center rounded-full bg-badge-bleu-fond text-[12px] font-semibold text-badge-bleu-texte">
      {initiales}
    </span>
  );
}

import { Badge } from "@/components/ui";

/**
 * Bandeau permanent de la console (écran 18) : FYXOP n'a accès qu'à des métadonnées d'établissement
 * et à des compteurs techniques, jamais au contenu des dossiers.
 */
export function BandeauConsole() {
  return (
    <aside
      aria-label="Périmètre de la console"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-carte border border-badge-ambre-fond bg-badge-ambre-fond px-4 py-2.5"
    >
      <Badge ton="ambre" className="bg-surface">
        Console FYXOP
      </Badge>
      <p className="m-0 min-w-0 flex-1 basis-[260px] text-[13px] text-badge-ambre-texte">
        <strong>Aucun accès au contenu des dossiers.</strong> FYXOP ne voit que des compteurs techniques (utilisateurs, événements, intégrité du journal) :
        ni dossier, ni client, ni montant.
      </p>
    </aside>
  );
}

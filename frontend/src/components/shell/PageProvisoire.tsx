import { Card } from "@/components/ui";

/** Page d'attente d'un écran livré plus tard (F6 : Mon compte, F7 : administration). */
export function PageProvisoire({ titre, tache, description }: { titre: string; tache: string; description: string }) {
  return (
    <div className="flex flex-col gap-5">
      <h1 className="m-0 text-titre-page">{titre}</h1>
      <Card>
        <p className="m-0 text-[15px] text-texte-2" role="status">
          {description}
        </p>
        <p className="m-0 mt-2 text-[13px] text-texte-attenue">Écran prévu dans la tâche {tache}.</p>
      </Card>
    </div>
  );
}

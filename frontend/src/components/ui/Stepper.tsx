import { cn } from "@/lib/cn";

export interface StepperProps {
  /** Libellés des étapes (ex. « Mot de passe », « Téléphone », « Vérification »). */
  etapes: readonly string[];
  /** Index de l'étape en cours (0 = première). */
  courante: number;
  label?: string;
  className?: string;
}

/**
 * Indicateur d'étapes (écran 01b) : barres de 6 px, bleu marque pour les étapes
 * faites et en cours, gris au-delà. L'état de chaque étape est aussi donné en
 * texte aux lecteurs d'écran, et l'étape en cours porte `aria-current="step"`.
 */
export function Stepper({ etapes, courante, label = "Étapes", className }: StepperProps) {
  return (
    <ol
      aria-label={label}
      className={cn("m-0 grid list-none gap-2 p-0", className)}
      style={{ gridTemplateColumns: `repeat(${etapes.length}, minmax(0, 1fr))` }}
    >
      {etapes.map((libelle, i) => {
        const etat = i < courante ? "terminée" : i === courante ? "en cours" : "à venir";
        const atteinte = i <= courante;
        return (
          <li key={libelle} aria-current={i === courante ? "step" : undefined} className="flex min-w-0 flex-col gap-1.5">
            <span aria-hidden="true" className={cn("h-1.5 rounded-[3px]", atteinte ? "bg-marque" : "bg-bordure")} />
            <span className={cn("text-[13px] font-semibold", atteinte ? "text-encre" : "text-texte-attenue")}>
              <span className="sr-only">
                Étape {i + 1} sur {etapes.length} :{" "}
              </span>
              {libelle}
              <span className="sr-only"> ({etat})</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

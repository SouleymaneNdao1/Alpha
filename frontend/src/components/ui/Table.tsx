import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export interface TableProps extends HTMLAttributes<HTMLTableElement> {
  /** Légende (`<caption>`) : nom accessible du tableau et de sa zone de défilement. */
  legende: string;
  /** Affiche la légende à l'écran (sinon réservée aux lecteurs d'écran). */
  legendeVisible?: boolean;
  children: ReactNode;
}

/**
 * Tableau du prototype (`th` 12 px capitales, `td` 14 px 11×12). Sous 768 px,
 * le défilement horizontal se fait DANS ce conteneur, jamais sur la page ; le
 * conteneur est focalisable pour défiler au clavier.
 */
export function Table({ legende, legendeVisible, className, children, ...reste }: TableProps) {
  return (
    <div role="region" aria-label={legende} tabIndex={0} className="relative w-full min-w-0 max-w-full overflow-x-auto">
      <table className={cn("w-full border-collapse", className)} {...reste}>
        <caption className={legendeVisible ? "px-3 pb-2 text-left text-[13px] text-texte-attenue" : "sr-only"}>{legende}</caption>
        {children}
      </table>
    </div>
  );
}

export interface ThProps extends ThHTMLAttributes<HTMLTableCellElement> {
  /** Colonne numérique (montants) : alignée à droite. */
  num?: boolean;
}

export function Th({ num, className, scope = "col", ...reste }: ThProps) {
  return (
    <th
      scope={scope}
      className={cn(
        "whitespace-nowrap border-b border-bordure bg-entete-tableau px-3 py-2.5 text-th uppercase text-texte-attenue",
        num ? "text-right" : "text-left",
        className,
      )}
      {...reste}
    />
  );
}

export interface TdProps extends TdHTMLAttributes<HTMLTableCellElement> {
  /** Montant : IBM Plex Mono aligné à droite (`.num`). */
  num?: boolean;
  /** Référence, horodatage, IP, empreinte : IBM Plex Mono (`.mono`). */
  mono?: boolean;
  /** Autorise le retour à la ligne (par défaut : `nowrap`, comme le prototype). */
  retourLigne?: boolean;
}

export function Td({ num, mono, retourLigne, className, ...reste }: TdProps) {
  return (
    <td
      className={cn(
        "border-b border-ligne px-3 py-2.75 align-middle text-[14px]",
        !retourLigne && "whitespace-nowrap",
        (num || mono) && "font-mono",
        num && "text-right",
        className,
      )}
      {...reste}
    />
  );
}

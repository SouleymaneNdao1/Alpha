import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export type TonBadge = "vert" | "ambre" | "rouge" | "bleu" | "gris";

const tons: Record<TonBadge, string> = {
  vert: "bg-badge-vert-fond text-badge-vert-texte",
  ambre: "bg-badge-ambre-fond text-badge-ambre-texte",
  rouge: "bg-badge-rouge-fond text-badge-rouge-texte",
  bleu: "bg-badge-bleu-fond text-badge-bleu-texte",
  gris: "bg-badge-gris-fond text-badge-gris-texte",
};

export interface BadgeProps {
  ton?: TonBadge;
  /** Petit point de couleur avant le texte. */
  point?: boolean;
  children: ReactNode;
  className?: string;
  title?: string;
}

/**
 * Pastille de statut (`.badge` du prototype : pilule, 12 px, 600). Le sens
 * est toujours porté par le texte, jamais par la seule couleur.
 */
export function Badge({ ton = "gris", point, children, className, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-pilule px-2.5 py-0.5 text-[12px] font-semibold leading-[1.5]",
        tons[ton],
        className,
      )}
    >
      {point && <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />}
      {children}
    </span>
  );
}

"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Titre d'une étape d'un écran d'authentification. Quand `focaliser` est vrai
 * (changement d'étape), le titre reçoit le focus au montage : le lecteur
 * d'écran annonce la nouvelle étape et la tabulation repart de là.
 */
export function TitreEtape({
  children,
  description,
  focaliser = false,
  taille = "connexion",
}: {
  children: ReactNode;
  description?: ReactNode;
  focaliser?: boolean;
  /** `connexion` : 24 px (écran 01) ; `activation` : 22 px (écran 01b). */
  taille?: "connexion" | "activation";
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focaliser) ref.current?.focus();
  }, [focaliser]);
  return (
    <div className={cn("flex flex-col", taille === "connexion" ? "gap-2" : "gap-1.5")}>
      <h1
        ref={ref}
        tabIndex={-1}
        className={cn("m-0 font-semibold text-encre focus:outline-none", taille === "connexion" ? "text-[24px] leading-[1.25]" : "text-titre-auth")}
      >
        {children}
      </h1>
      {description && <p className="m-0 text-[15px] text-texte-attenue">{description}</p>}
    </div>
  );
}

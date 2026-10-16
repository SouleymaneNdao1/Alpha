"use client";

import { Dialogue, type DialogueProps } from "./Dialogue";
import { cn } from "@/lib/cn";

export interface ModalProps extends Omit<DialogueProps, "classeDialogue"> {
  /** `normal` : 520 px ; `large` : 720 px. */
  taille?: "normal" | "large";
}

/** Fenêtre modale centrée (confirmation de décision, invitation d'un utilisateur…). */
export function Modal({ taille = "normal", ...props }: ModalProps) {
  return (
    <Dialogue
      {...props}
      classeDialogue={cn(
        "m-auto max-h-[calc(100dvh-32px)] w-[calc(100%-32px)] rounded-carte",
        taille === "large" ? "max-w-[720px]" : "max-w-[520px]",
      )}
    />
  );
}

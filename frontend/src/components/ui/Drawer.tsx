"use client";

import { Dialogue, type DialogueProps } from "./Dialogue";

export type DrawerProps = Omit<DialogueProps, "classeDialogue">;

/**
 * Panneau latéral à droite (création et modification dans le catalogue des
 * rôles, fiche utilisateur). Pleine largeur sur mobile, 480 px au-delà.
 */
export function Drawer(props: DrawerProps) {
  return (
    <Dialogue
      {...props}
      classeDialogue="fixed inset-y-0 left-auto right-0 m-0 h-dvh max-h-none w-full max-w-[min(480px,100vw)] rounded-none border-y-0 border-r-0"
    />
  );
}

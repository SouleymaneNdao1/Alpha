"use client";

import { createContext, useContext } from "react";
import type { Moi } from "@/lib/api/hooks/auth";

const Contexte = createContext<Moi | null>(null);

export const FournisseurMoi = Contexte.Provider;

/** Utilisateur connecté. Valable sous la coquille `(app)`, qui n'affiche rien sans session. */
export function useMoi(): Moi {
  const moi = useContext(Contexte);
  if (!moi) throw new Error("useMoi doit être utilisé sous <CoquilleApp>.");
  return moi;
}

"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type TonToast = "succes" | "info" | "alerte" | "erreur";

export interface ToastInit {
  titre: string;
  message?: string;
  ton?: TonToast;
  /** Durée d'affichage en ms ; `null` = jusqu'à fermeture. Erreurs : `null` par défaut. */
  duree?: number | null;
}

interface ToastActif extends Required<Pick<ToastInit, "titre" | "ton">> {
  id: number;
  message?: string;
  duree: number | null;
}

interface ContexteToasts {
  toast: (t: ToastInit) => number;
  fermer: (id: number) => void;
}

const Contexte = createContext<ContexteToasts | null>(null);

/** `const { toast } = useToast(); toast({ titre: "Décision enregistrée", ton: "succes" })`. */
export function useToast(): ContexteToasts {
  const c = useContext(Contexte);
  if (!c) throw new Error("useToast doit être utilisé sous <FournisseurToasts>.");
  return c;
}

const accents: Record<TonToast, string> = {
  succes: "shadow-[inset_3px_0_0_var(--succes),var(--ombre-flottante)]",
  info: "shadow-[inset_3px_0_0_var(--marque),var(--ombre-flottante)]",
  alerte: "shadow-[inset_3px_0_0_var(--alerte-texte),var(--ombre-flottante)]",
  erreur: "shadow-[inset_3px_0_0_var(--danger-texte),var(--ombre-flottante)]",
};

const pastilles: Record<TonToast, string> = {
  succes: "bg-succes",
  info: "bg-marque",
  alerte: "bg-alerte-texte",
  erreur: "bg-danger-texte",
};

const libellesTon: Record<TonToast, string> = { succes: "Succès", info: "Information", alerte: "Attention", erreur: "Erreur" };

/**
 * Notifications éphémères. Deux régions `aria-live` permanentes : « polite »
 * pour l'information et le succès, « assertive » pour les alertes et les
 * erreurs. Le minuteur s'arrête au survol et au focus ; les erreurs restent
 * affichées jusqu'à leur fermeture.
 */
export function FournisseurToasts({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastActif[]>([]);
  const prochain = useRef(1);

  const fermer = useCallback((id: number) => setToasts((l) => l.filter((t) => t.id !== id)), []);
  const toast = useCallback((t: ToastInit) => {
    const id = prochain.current++;
    const ton = t.ton ?? "info";
    const duree = t.duree !== undefined ? t.duree : ton === "erreur" ? null : 6000;
    setToasts((l) => [...l.slice(-4), { id, titre: t.titre, message: t.message, ton, duree }]);
    return id;
  }, []);
  const valeur = useMemo(() => ({ toast, fermer }), [toast, fermer]);

  const region = (urgent: boolean) => (
    <div aria-live={urgent ? "assertive" : "polite"} aria-relevant="additions" className="flex flex-col gap-2">
      {toasts
        .filter((t) => (t.ton === "erreur" || t.ton === "alerte") === urgent)
        .map((t) => (
          <ElementToast key={t.id} toast={t} onFermer={() => fermer(t.id)} />
        ))}
    </div>
  );

  return (
    <Contexte.Provider value={valeur}>
      {children}
      <section
        aria-label="Notifications"
        className="pointer-events-none fixed bottom-4 left-4 right-4 z-50 flex flex-col gap-2 sm:left-auto sm:w-[380px]"
      >
        {region(true)}
        {region(false)}
      </section>
    </Contexte.Provider>
  );
}

function ElementToast({ toast, onFermer }: { toast: ToastActif; onFermer: () => void }) {
  const [pause, setPause] = useState(false);
  const reste = useRef(toast.duree);

  useEffect(() => {
    if (reste.current === null || pause) return;
    const debut = Date.now();
    const minuteur = setTimeout(onFermer, reste.current);
    return () => {
      clearTimeout(minuteur);
      if (reste.current !== null) reste.current -= Date.now() - debut;
    };
  }, [pause, onFermer]);

  return (
    <div
      className={cn("pointer-events-auto flex items-start gap-3 rounded-carte border border-bordure bg-surface py-3 pl-4 pr-2", accents[toast.ton])}
      onMouseEnter={() => setPause(true)}
      onMouseLeave={() => setPause(false)}
      onFocus={() => setPause(true)}
      onBlur={() => setPause(false)}
    >
      <span className={cn("mt-[7px] h-2 w-2 shrink-0 rounded-full", pastilles[toast.ton])} aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-[14px] font-semibold text-encre">
          <span className="sr-only">{libellesTon[toast.ton]} : </span>
          {toast.titre}
        </p>
        {toast.message && <p className="text-[13px] text-texte-attenue">{toast.message}</p>}
      </div>
      <button
        type="button"
        onClick={onFermer}
        aria-label="Fermer la notification"
        className="cible-tactile inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-champ text-texte-attenue hover:bg-survol hover:text-encre"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  );
}

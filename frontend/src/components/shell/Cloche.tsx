"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { formatDateHeureCourte } from "@/lib/format";
import { useMarquerLue, useNotifications, useNotificationsNonLues, useToutMarquerLu, type Notification } from "@/lib/api/hooks/notifications";

const classeBtn =
  "cible-tactile relative inline-flex h-10 min-w-10 items-center justify-center rounded-champ border border-bordure bg-surface px-2 text-texte-2 no-underline hover:bg-survol hover:text-encre";

/**
 * Cloche du bandeau branchée sur `/moi/notifications` : compteur des non lues
 * (relevé toutes les 60 s), panneau des 10 dernières, « Tout marquer comme lu ».
 * Un clic sur une notification la marque lue et ouvre son lien.
 */
export function Cloche() {
  const [ouvert, setOuvert] = useState(false);
  const racine = useRef<HTMLDivElement>(null);
  const bouton = useRef<HTMLButtonElement>(null);
  const idPanneau = useId();
  const router = useRouter();
  const compteur = useNotificationsNonLues();
  const liste = useNotifications({ taille: 10, active: ouvert });
  const lue = useMarquerLue();
  const toutLu = useToutMarquerLu();
  const nonLues = compteur.data ?? 0;

  useEffect(() => {
    if (!ouvert) return;
    const clicExterieur = (e: MouseEvent) => {
      if (racine.current && !racine.current.contains(e.target as Node)) setOuvert(false);
    };
    const echap = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOuvert(false);
        bouton.current?.focus();
      }
    };
    document.addEventListener("mousedown", clicExterieur);
    document.addEventListener("keydown", echap);
    return () => {
      document.removeEventListener("mousedown", clicExterieur);
      document.removeEventListener("keydown", echap);
    };
  }, [ouvert]);

  const ouvrir = (n: Notification) => {
    if (!n.lue_le) lue.mutate(n.id);
    setOuvert(false);
    if (n.lien.startsWith("/")) router.push(n.lien);
  };

  return (
    <div ref={racine} className="relative">
      <button
        ref={bouton}
        type="button"
        aria-haspopup="true"
        aria-expanded={ouvert}
        aria-controls={ouvert ? idPanneau : undefined}
        aria-label={nonLues ? `Notifications : ${nonLues} non lue${nonLues > 1 ? "s" : ""}` : "Notifications"}
        onClick={() => setOuvert((o) => !o)}
        className={cn(classeBtn, "cursor-pointer")}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
        </svg>
        {nonLues > 0 && (
          <span
            data-testid="compteur-cloche"
            className="absolute -right-1.5 -top-1.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-pilule bg-danger-texte px-1 font-mono text-[11px] font-semibold text-white"
            aria-hidden="true"
          >
            {nonLues > 99 ? "99+" : nonLues}
          </span>
        )}
      </button>

      {ouvert && (
        <section
          id={idPanneau}
          aria-label="Notifications reçues"
          className="fixed inset-x-3 top-[64px] z-40 flex max-h-[min(70dvh,520px)] flex-col overflow-hidden rounded-carte border border-bordure bg-surface shadow-flottante sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-[380px]"
        >
          <div className="flex items-center justify-between gap-3 border-b border-bordure px-4 py-3">
            <h2 className="m-0 text-[15px] font-semibold">Notifications</h2>
            <button
              type="button"
              disabled={nonLues === 0 || toutLu.isPending}
              onClick={() => toutLu.mutate()}
              className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-marque underline disabled:cursor-not-allowed disabled:text-texte-attenue disabled:no-underline"
            >
              Tout marquer comme lu
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {liste.isPending ? (
              <p className="m-0 px-4 py-3 text-[14px] text-texte-attenue" role="status">
                Chargement…
              </p>
            ) : liste.isError ? (
              <p className="m-0 px-4 py-3 text-[14px] text-danger-texte" role="alert">
                Notifications indisponibles.
              </p>
            ) : liste.data.results.length === 0 ? (
              <p className="m-0 px-4 py-3 text-[14px] text-texte-attenue">Aucune notification.</p>
            ) : (
              <ul className="m-0 list-none p-0">
                {liste.data.results.map((n) => (
                  <li key={n.id} className="border-b border-ligne last:border-b-0">
                    <button
                      type="button"
                      onClick={() => ouvrir(n)}
                      className={cn("flex w-full cursor-pointer flex-col items-start gap-0.5 border-0 px-4 py-3 text-left hover:bg-survol", n.lue_le ? "bg-surface" : "bg-entete-tableau")}
                    >
                      <span className={cn("text-[14px] text-encre", !n.lue_le && "font-semibold")}>
                        {!n.lue_le && <span className="sr-only">Non lue : </span>}
                        {n.titre}
                      </span>
                      {n.corps && <span className="text-[13px] text-texte-attenue">{n.corps}</span>}
                      <span className="font-mono text-[11px] text-texte-attenue">{formatDateHeureCourte(n.cree_le)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="border-t border-bordure px-4 py-2.5">
            <Link href="/mon-compte?onglet=notifications" onClick={() => setOuvert(false)} className="text-[13px] font-semibold">
              Préférences et toutes les notifications
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}

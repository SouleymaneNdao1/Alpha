"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CATEGORIES, LigneEvenement, PERIODES } from "@/components/audit/EcranJournal";
import { EnTetePage, ErreurChargement } from "@/components/shell/Etats";
import { Button, Card, Input, Select, Table, Th } from "@/components/ui";
import type { FiltresJournal, Periode } from "@/lib/api/hooks/audit";
import { useAuditPlateforme } from "@/lib/api/hooks/plateforme";

/** `/console/journal` : chaîne d'audit de la plateforme (actions des super-administrateurs), version simplifiée du journal F8. */
export function EcranJournalPlateforme() {
  const [recherche, setRecherche] = useState("");
  const [q, setQ] = useState("");
  const [categorie, setCategorie] = useState("");
  const [periode, setPeriode] = useState<Periode>("30j");

  useEffect(() => {
    const t = setTimeout(() => setQ(recherche), 300);
    return () => clearTimeout(t);
  }, [recherche]);

  const filtres: FiltresJournal = useMemo(() => ({ q, categorie, periode }), [q, categorie, periode]);
  const evenements = useAuditPlateforme(filtres);
  const lignes = useMemo(() => (evenements.data?.pages ?? []).flatMap((p) => p.results), [evenements.data]);

  const sentinelle = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = evenements;
  useEffect(() => {
    const el = sentinelle.current;
    if (!el || !hasNextPage || typeof IntersectionObserver === "undefined") return;
    const obs = new IntersectionObserver((entrees) => {
      if (entrees.some((e) => e.isIntersecting) && !isFetchingNextPage) void fetchNextPage();
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage, lignes.length]);

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre="Journal de la plateforme"
        sousTitre="Actions des super-administrateurs FYXOP (création d'établissements, invitations, réinitialisations), en ajout seul. Le journal propre à chaque établissement n'est pas lisible ici."
      />

      <Card marge={false}>
        <div className="flex flex-wrap items-end gap-3 p-4">
          <Input
            type="search"
            label="Rechercher dans le journal"
            labelMasque
            placeholder="Utilisateur, établissement, adresse IP…"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            classeConteneur="min-w-0 flex-1 basis-[220px]"
          />
          <Select label="Catégorie" options={CATEGORIES} value={categorie} onChange={(e) => setCategorie(e.target.value)} classeConteneur="basis-[220px]" />
          <Select label="Période" options={PERIODES} value={periode} onChange={(e) => setPeriode(e.target.value as Periode)} classeConteneur="basis-[180px]" />
        </div>

        {evenements.isPending ? (
          <p className="m-0 border-t border-ligne p-4 text-[15px] text-texte-attenue" role="status">
            Chargement du journal…
          </p>
        ) : evenements.isError ? (
          <div className="border-t border-ligne p-4">
            <ErreurChargement erreur={evenements.error} titre="Journal indisponible" onReessayer={() => void evenements.refetch()} />
          </div>
        ) : lignes.length === 0 ? (
          <p className="m-0 border-t border-ligne p-4 text-[15px] text-texte-2" role="status">
            Aucun événement ne correspond à ces filtres.
          </p>
        ) : (
          <>
            <Table legende="Événements du journal de la plateforme">
              <thead>
                <tr>
                  <Th>Horodatage</Th>
                  <Th>Utilisateur</Th>
                  <Th>Action</Th>
                  <Th>Objet</Th>
                  <Th>Détail (avant → après)</Th>
                  <Th>Adresse IP</Th>
                  <Th>Empreinte</Th>
                </tr>
              </thead>
              <tbody>
                {lignes.map((e) => (
                  <LigneEvenement key={e.seq} e={e} />
                ))}
              </tbody>
            </Table>
            <div ref={sentinelle} className="flex min-h-[56px] items-center justify-center p-3">
              {hasNextPage ? (
                <Button variante="secondaire" chargement={isFetchingNextPage} onClick={() => void fetchNextPage()}>
                  Charger plus d&apos;événements
                </Button>
              ) : (
                <p className="m-0 text-[13px] text-texte-attenue">
                  Fin du journal · {lignes.length} événement{lignes.length > 1 ? "s" : ""} affiché{lignes.length > 1 ? "s" : ""}
                </p>
              )}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

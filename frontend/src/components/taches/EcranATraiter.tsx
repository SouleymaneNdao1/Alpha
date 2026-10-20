"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Compteur, LienBouton } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import {
  GROUPES,
  LIBELLES_MODULES,
  useCompteursTaches,
  useTaches,
  type GroupeTache,
  type Tache,
} from "@/lib/api/hooks/taches";
import { cn } from "@/lib/cn";
import { formatHeure, formatJourMois, formatMontant } from "@/lib/format";

const TITRES_GROUPES: Record<GroupeTache, string> = {
  EN_RETARD: "En retard",
  AUJOURDHUI: "Aujourd'hui",
  CETTE_SEMAINE: "Cette semaine",
  PLUS_TARD: "Plus tard",
};

const LIBELLES_ECHEANCE: Record<string, string> = {
  AVANT: "Avant le",
  ECHEANCE: "Échéance le",
  EXECUTION: "Exécution le",
  PREAVIS: "Préavis avant le",
};

/** Tuiles de synthèse : seuls les trois premiers groupes (le prototype n'a pas de tuile « Plus tard »). */
const TUILES: ReadonlyArray<{ groupe: GroupeTache; ton: string }> = [
  { groupe: "EN_RETARD", ton: "text-danger-texte" },
  { groupe: "AUJOURDHUI", ton: "text-alerte-texte" },
  { groupe: "CETTE_SEMAINE", ton: "text-encre" },
];

/** « À traiter » (écran 01c) : tout ce qui attend la décision de l'utilisateur, par urgence. */
export function EcranATraiter() {
  const moi = useMoi();
  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <h1 className="m-0 text-titre-page">Bonjour {moi.prenom}, voici ce qui vous attend</h1>
        <p className="m-0 text-[15px] text-texte-attenue">
          {moi.etablissement ? `${moi.etablissement.raison_sociale} · ` : ""}tout ce qui attend votre décision, quel que soit le module. Les plus
          urgents en premier.
        </p>
      </header>
      {moi.est_super_admin ? <SansEtablissement /> : <ListeATraiter />}
    </div>
  );
}

function SansEtablissement() {
  return (
    <Card>
      <p className="m-0 text-[15px] text-texte-2" role="status">
        Votre compte de super-administrateur FYXOP n&apos;est rattaché à aucun établissement : il n&apos;a pas de tâches à traiter.
      </p>
      <div className="mt-3">
        <LienBouton href="/console">Ouvrir la console FYXOP</LienBouton>
      </div>
    </Card>
  );
}

function ListeATraiter() {
  const [module, setModule] = useState<string | null>(null);
  const [groupe, setGroupe] = useState<GroupeTache | null>(null);
  const actualisationAuto = useRef(false);

  const compteurs = useCompteursTaches();
  const taches = useTaches({ module, groupe }, () => actualisationAuto.current);

  // Quand les compteurs changent (actualisation toutes les 60 s), la liste est relue en appel de fond.
  const signature = compteurs.data ? JSON.stringify(compteurs.data) : null;
  const precedente = useRef(signature);
  const { refetch } = taches;
  useEffect(() => {
    if (signature === precedente.current) return;
    const premiere = precedente.current === null;
    precedente.current = signature;
    if (premiere) return;
    actualisationAuto.current = true;
    void refetch().finally(() => {
      actualisationAuto.current = false;
    });
  }, [signature, refetch]);

  const liste = useMemo(() => (taches.data?.pages ?? []).flatMap((p) => p.results), [taches.data]);
  const parGroupe = useMemo(() => {
    const r: Record<GroupeTache, Tache[]> = { EN_RETARD: [], AUJOURDHUI: [], CETTE_SEMAINE: [], PLUS_TARD: [] };
    for (const t of liste) r[t.groupe]?.push(t);
    return r;
  }, [liste]);

  const erreur = taches.error ?? compteurs.error;
  if (erreur && estApiError(erreur) && erreur.status === 403) {
    return (
      <Card titre="Accès refusé">
        <p className="m-0 text-[15px] text-texte-2" role="alert">
          Vous n&apos;avez pas accès à cet écran.
        </p>
      </Card>
    );
  }

  const modules = Object.entries(compteurs.data?.par_module ?? {}).sort(([a], [b]) => {
    const ordre = Object.keys(LIBELLES_MODULES);
    return (ordre.indexOf(a) + 1 || 99) - (ordre.indexOf(b) + 1 || 99);
  });
  const filtre = module !== null || groupe !== null;

  return (
    <>
      <section aria-label="Synthèse par urgence" className="grid grid-cols-3 gap-2 sm:gap-3">
        {TUILES.map(({ groupe: g, ton }) => {
          const actif = groupe === g;
          const valeur = compteurs.data?.par_groupe[g];
          return (
            <button
              key={g}
              type="button"
              aria-pressed={actif}
              onClick={() => setGroupe(actif ? null : g)}
              className={cn(
                "cible-tactile flex cursor-pointer flex-col items-start gap-1 rounded-carte border bg-surface px-3 py-3 text-left hover:bg-survol sm:px-4.5 sm:py-3.5",
                actif ? "border-marque shadow-menu-actif" : "border-bordure",
              )}
            >
              <span className="text-[12px] font-semibold text-texte-attenue sm:text-[13px]">{TITRES_GROUPES[g]}</span>
              <span className={cn("font-mono text-[28px] font-semibold leading-none", ton)}>{valeur ?? "–"}</span>
            </button>
          );
        })}
      </section>

      <div role="group" aria-label="Filtrer par module" className="flex flex-wrap gap-2">
        <PuceFiltre actif={module === null} onClick={() => setModule(null)} libelle="Tout" compteur={compteurs.data?.total} />
        {modules.map(([code, n]) => (
          <PuceFiltre key={code} actif={module === code} onClick={() => setModule(module === code ? null : code)} libelle={LIBELLES_MODULES[code] ?? code} compteur={n} />
        ))}
      </div>

      {taches.isPending ? (
        <Card>
          <p className="m-0 text-[15px] text-texte-attenue" role="status">
            Chargement des tâches…
          </p>
        </Card>
      ) : taches.isError ? (
        <Card titre="Tâches indisponibles">
          <p className="m-0 text-[15px] text-texte-2" role="alert">
            {estApiError(taches.error) ? taches.error.message : "Impossible de charger vos tâches."}
          </p>
          <div className="mt-3">
            <Button variante="secondaire" onClick={() => void taches.refetch()}>
              Réessayer
            </Button>
          </div>
        </Card>
      ) : liste.length === 0 ? (
        <Card>
          <p className="m-0 text-[15px] text-texte-2" role="status">
            {filtre ? "Rien à traiter pour ce filtre." : "Rien à traiter pour le moment."}
          </p>
          {filtre && (
            <div className="mt-3">
              <Button
                variante="secondaire"
                onClick={() => {
                  setModule(null);
                  setGroupe(null);
                }}
              >
                Afficher toutes les tâches
              </Button>
            </div>
          )}
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          {GROUPES.filter((g) => parGroupe[g].length > 0).map((g) => (
            <Card key={g} titre={`${TITRES_GROUPES[g]} · ${parGroupe[g].length}`} marge={false}>
              <ul className="m-0 list-none p-0">
                {parGroupe[g].map((t) => (
                  <LigneTache key={t.id} tache={t} />
                ))}
              </ul>
            </Card>
          ))}
          {taches.hasNextPage && (
            <div className="flex justify-center">
              <Button variante="secondaire" chargement={taches.isFetchingNextPage} onClick={() => void taches.fetchNextPage()}>
                Afficher plus de tâches
              </Button>
            </div>
          )}
        </div>
      )}

      <Card>
        <p className="m-0 text-[14px] text-texte-2">
          <strong>Vous serez absent ?</strong> Programmez une délégation dans <Link href="/mon-compte?onglet=absences">Mon compte</Link> : vos demandes
          iront à votre délégataire pendant cette période.
        </p>
      </Card>
    </>
  );
}

function PuceFiltre({ actif, onClick, libelle, compteur }: { actif: boolean; onClick: () => void; libelle: string; compteur?: number }) {
  return (
    <button
      type="button"
      aria-pressed={actif}
      onClick={onClick}
      className={cn(
        "cible-tactile inline-flex min-h-[36px] cursor-pointer items-center gap-2 rounded-pilule border px-3.5 text-[14px] font-semibold",
        actif ? "border-encre bg-encre text-white" : "border-bordure-champ bg-surface text-encre hover:bg-survol",
      )}
    >
      {libelle}
      {compteur !== undefined && <Compteur valeur={compteur} className={actif ? "bg-menu-survol text-white" : undefined} />}
    </button>
  );
}

function echeanceDe(t: Tache): { texte: string; classe: string } {
  if (!t.echeance) return { texte: "Sans échéance", classe: "text-texte-attenue" };
  if (t.groupe === "EN_RETARD") {
    const n = t.retard_jours ?? 0;
    return { texte: n > 0 ? `En retard d'${n} jour${n > 1 ? "s" : ""}` : "En retard", classe: "font-semibold text-danger-texte" };
  }
  if (t.groupe === "AUJOURDHUI") {
    const h = formatHeure(t.echeance);
    return { texte: h === "00:00" ? "Aujourd'hui" : `Aujourd'hui, ${h}`, classe: "font-semibold text-alerte-texte" };
  }
  return { texte: `${LIBELLES_ECHEANCE[t.type_echeance] ?? "Échéance le"} ${formatJourMois(t.echeance)}`, classe: "text-texte-attenue" };
}

function LigneTache({ tache: t }: { tache: Tache }) {
  const echeance = echeanceDe(t);
  return (
    <li className="flex flex-wrap items-center gap-x-5 gap-y-2.5 border-t border-ligne px-4.5 py-3.5">
      <div className="flex min-w-0 flex-1 basis-[260px] flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <Badge ton="bleu">{t.module_libelle}</Badge>
          {t.par_delegation_de && <Badge ton="ambre">par délégation de {t.par_delegation_de.nom}</Badge>}
        </div>
        <p className="m-0 text-[15px] font-semibold text-encre">
          <span className="font-mono text-[13px] font-medium text-texte-attenue">{t.reference}</span> · {t.titre}
        </p>
        {t.sous_titre && <p className="m-0 text-[13px] text-texte-attenue">{t.sous_titre}</p>}
      </div>
      {t.montant !== null && <span className="font-mono text-[14px] font-semibold text-encre sm:min-w-[130px] sm:text-right">{formatMontant(t.montant, t.devise)}</span>}
      <span className={cn("text-[13px] sm:min-w-[130px]", echeance.classe)}>{echeance.texte}</span>
      <LienBouton href={t.lien} variante={t.action === "VALIDER" ? "validation" : "primaire"} aria-label={`${t.action_libelle} : ${t.reference}`}>
        {t.action_libelle}
      </LienBouton>
    </li>
  );
}

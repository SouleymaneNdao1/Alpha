"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Input, Select, Table, Td, Th, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import {
  useControlesAudit,
  useEvenementsAudit,
  useExporterJournal,
  useIndicateursAudit,
  useLancerControle,
  type ControleAudit,
  type EvenementAudit,
  type FiltresJournal,
  type IndicateursAudit,
  type Periode,
} from "@/lib/api/hooks/audit";
import { formatDateHeureCourte, formatHorodatage } from "@/lib/format";
import { possede } from "@/lib/permissions";

export const CATEGORIES = [
  { valeur: "", libelle: "Toutes les actions" },
  { valeur: "CONNEXION", libelle: "Connexions" },
  { valeur: "DECISION", libelle: "Décisions" },
  { valeur: "MODIFICATION", libelle: "Modifications de données" },
  { valeur: "PARAMETRAGE", libelle: "Paramétrage" },
  { valeur: "ACCES_API", libelle: "Accès API" },
  { valeur: "SECURITE", libelle: "Sécurité" },
  { valeur: "DOCUMENT", libelle: "Documents" },
];

export const PERIODES: Array<{ valeur: Periode; libelle: string }> = [
  { valeur: "aujourdhui", libelle: "Aujourd'hui" },
  { valeur: "7j", libelle: "7 derniers jours" },
  { valeur: "30j", libelle: "30 derniers jours" },
];

/** « Journal d'audit » (écran 13). */
export function EcranJournal() {
  const moi = useMoi();
  if (!possede(moi, "audit.lecture")) {
    return (
      <Card titre="Accès refusé">
        <p className="m-0 text-[15px] text-texte-2" role="alert">
          Vous n&apos;avez pas la permission de consulter le journal d&apos;audit.
        </p>
      </Card>
    );
  }
  return <Journal peutExporter={possede(moi, "audit.export")} etablissement={moi.etablissement?.raison_sociale ?? ""} />;
}

function Journal({ peutExporter, etablissement }: { peutExporter: boolean; etablissement: string }) {
  const { toast } = useToast();
  const [recherche, setRecherche] = useState("");
  const [q, setQ] = useState("");
  const [categorie, setCategorie] = useState("");
  const [periode, setPeriode] = useState<Periode>("7j");

  useEffect(() => {
    const t = setTimeout(() => setQ(recherche), 300);
    return () => clearTimeout(t);
  }, [recherche]);

  const filtres: FiltresJournal = useMemo(() => ({ q, categorie, periode }), [q, categorie, periode]);
  const indicateurs = useIndicateursAudit();
  const evenements = useEvenementsAudit(filtres);
  const exporter = useExporterJournal();

  const lignes = useMemo(() => (evenements.data?.pages ?? []).flatMap((p) => p.results), [evenements.data]);

  // Défilement infini : la sentinelle en bas du tableau charge la page suivante.
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

  const lancerExport = () =>
    exporter.mutate(filtres, {
      onSuccess: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `journal-audit-${new Date().toISOString().slice(0, 10)}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 10_000);
        toast({ titre: "Export du journal téléchargé", ton: "succes" });
      },
      onError: (e) =>
        toast({
          titre: estApiError(e) && e.code === "EXPORT_TROP_VOLUMINEUX" ? "Export trop volumineux" : "Export impossible",
          message: estApiError(e) ? e.message : "Réessayez dans un instant.",
          ton: "erreur",
        }),
    });

  const ind = indicateurs.data;
  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="m-0 text-titre-page">Journal d&apos;audit</h1>
          <p className="m-0 max-w-[720px] text-[15px] text-texte-attenue">
            {etablissement ? `${etablissement} · ` : ""}toutes les actions, en ajout seul : aucune entrée ne peut être modifiée ni supprimée, y compris par
            un administrateur.
          </p>
        </div>
        {peutExporter && (
          <Button variante="secondaire" chargement={exporter.isPending} onClick={lancerExport}>
            Exporter (Excel)
          </Button>
        )}
      </header>

      <CarteIntegrite indicateurs={ind} chargement={indicateurs.isPending} />

      <section aria-label="Indicateurs" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tuile libelle="Événements aujourd'hui" valeur={ind?.evenements_aujourdhui} />
        <Tuile libelle="Connexions échouées (24 h)" valeur={ind?.connexions_echouees_24h} />
        <Tuile libelle="Actions d'administration" valeur={ind?.actions_administration_24h} />
      </section>

      <Card marge={false}>
        <div className="flex flex-wrap items-end gap-3 p-4">
          <Input
            type="search"
            label="Rechercher dans le journal"
            labelMasque
            placeholder="Utilisateur, dossier, adresse IP…"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            classeConteneur="min-w-0 flex-1 basis-[220px]"
          />
          <Select label="Catégorie" options={CATEGORIES} value={categorie} onChange={(e) => setCategorie(e.target.value)} classeConteneur="basis-[220px]" />
          <Select
            label="Période"
            options={PERIODES}
            value={periode}
            onChange={(e) => setPeriode(e.target.value as Periode)}
            classeConteneur="basis-[180px]"
          />
        </div>

        {evenements.isPending ? (
          <p className="m-0 border-t border-ligne p-4 text-[15px] text-texte-attenue" role="status">
            Chargement du journal…
          </p>
        ) : evenements.isError ? (
          <div className="border-t border-ligne p-4">
            <p className="m-0 text-[15px] text-texte-2" role="alert">
              {estApiError(evenements.error) ? evenements.error.message : "Impossible de charger le journal."}
            </p>
            <div className="mt-3">
              <Button variante="secondaire" onClick={() => void evenements.refetch()}>
                Réessayer
              </Button>
            </div>
          </div>
        ) : lignes.length === 0 ? (
          <p className="m-0 border-t border-ligne p-4 text-[15px] text-texte-2" role="status">
            Aucun événement ne correspond à ces filtres.
          </p>
        ) : (
          <>
            <Table legende="Événements du journal d'audit">
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
                <p className="m-0 text-[13px] text-texte-attenue">Fin du journal · {lignes.length} événement{lignes.length > 1 ? "s" : ""} affiché{lignes.length > 1 ? "s" : ""}</p>
              )}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function Tuile({ libelle, valeur }: { libelle: string; valeur: number | undefined }) {
  return (
    <div className="flex flex-col gap-1 rounded-carte border border-bordure bg-surface px-4.5 py-3.5">
      <span className="text-[13px] font-semibold text-texte-attenue">{libelle}</span>
      <span className="font-mono text-[28px] font-semibold leading-none text-encre">{valeur ?? "–"}</span>
    </div>
  );
}

const LIBELLES_STATUT: Record<ControleAudit["statut"], { texte: string; ton: "vert" | "rouge" | "ambre" | "gris" }> = {
  INTACTE: { texte: "Intacte", ton: "vert" },
  ROMPUE: { texte: "Rompue", ton: "rouge" },
  EN_COURS: { texte: "En cours", ton: "ambre" },
  ERREUR: { texte: "Erreur", ton: "gris" },
};

function CarteIntegrite({ indicateurs, chargement }: { indicateurs: IndicateursAudit | undefined; chargement: boolean }) {
  const { toast } = useToast();
  const lancer = useLancerControle();
  const [historique, setHistorique] = useState(false);
  const controles = useControlesAudit();
  const dernier = indicateurs?.dernier_controle ?? null;
  const enCours = !!indicateurs?.controle_en_cours || lancer.isPending;

  // Fin d'un contrôle suivi : notification du résultat.
  const etaitEnCours = useRef(false);
  const { refetch: relireControles } = controles;
  useEffect(() => {
    if (!indicateurs) return;
    if (etaitEnCours.current && !indicateurs.controle_en_cours) {
      void relireControles();
      const d = indicateurs.dernier_controle;
      if (d?.statut === "ROMPUE") toast({ titre: "Contrôle terminé : chaîne rompue", message: `Rupture à l'événement n° ${d.premier_seq_invalide ?? "?"}.`, ton: "erreur" });
      else if (d?.statut === "INTACTE") toast({ titre: "Contrôle terminé : intégrité vérifiée", ton: "succes" });
      else toast({ titre: "Contrôle terminé", message: d?.message || undefined, ton: "alerte" });
    }
    etaitEnCours.current = indicateurs.controle_en_cours;
  }, [indicateurs, toast, relireControles]);

  const rompue = dernier?.statut === "ROMPUE";
  const declencher = () =>
    lancer.mutate(undefined, {
      onSuccess: () => toast({ titre: "Contrôle lancé", message: "Le résultat s'affichera ici dès qu'il sera disponible.", ton: "info" }),
      onError: (e) => {
        if (estApiError(e) && e.code === "CONTROLE_EN_COURS") toast({ titre: "Un contrôle est déjà en cours", ton: "info" });
        else toast({ titre: "Contrôle impossible", message: estApiError(e) ? e.message : undefined, ton: "erreur" });
      },
    });

  let titre: string;
  let detail: string;
  if (chargement) {
    titre = "Vérification de l'intégrité…";
    detail = "";
  } else if (rompue && dernier) {
    titre = `Chaîne rompue à l'événement n° ${dernier.premier_seq_invalide ?? "?"}`;
    detail = `Contrôle ${formatDateHeureCourte(dernier.termine_le ?? dernier.lance_le)}. Alertez immédiatement la sécurité FYXOP.`;
  } else if (dernier?.statut === "INTACTE") {
    titre = "Intégrité vérifiée";
    detail = `Chaîne d'empreintes intacte · contrôle ${formatDateHeureCourte(dernier.termine_le ?? dernier.lance_le)}`;
  } else if (dernier?.statut === "ERREUR") {
    titre = "Dernier contrôle en erreur";
    detail = dernier.message || "Relancez un contrôle.";
  } else {
    titre = "Aucun contrôle terminé";
    detail = "Lancez un contrôle pour vérifier la chaîne d'empreintes.";
  }

  return (
    <section
      aria-label="Intégrité du journal"
      className={`flex flex-col gap-3 rounded-carte border px-4.5 py-4 ${rompue ? "border-danger-texte bg-badge-rouge-fond" : "border-bordure bg-surface"}`}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span
          aria-hidden="true"
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${rompue ? "bg-danger-texte text-white" : dernier?.statut === "INTACTE" ? "bg-badge-vert-fond text-badge-vert-texte" : "bg-survol text-texte-2"}`}
        >
          {rompue ? "!" : dernier?.statut === "INTACTE" ? "✓" : "–"}
        </span>
        <div className="flex min-w-0 flex-1 basis-[240px] flex-col">
          <h2 className={`m-0 text-titre-carte ${rompue ? "text-badge-rouge-texte" : ""}`} role={rompue ? "alert" : undefined}>
            {titre}
          </h2>
          {detail && <p className="m-0 text-[13px] text-texte-attenue">{detail}</p>}
          {enCours && (
            <p className="m-0 mt-1 text-[13px] font-semibold text-alerte-texte" role="status">
              Contrôle en cours…
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variante="secondaire" onClick={() => setHistorique((h) => !h)} aria-expanded={historique}>
            Derniers contrôles
          </Button>
          <Button chargement={enCours} onClick={declencher}>
            Lancer un contrôle
          </Button>
        </div>
      </div>

      {historique && (
        <div className="border-t border-bordure pt-3">
          {controles.isPending ? (
            <p className="m-0 text-[13px] text-texte-attenue">Chargement…</p>
          ) : !controles.data?.results.length ? (
            <p className="m-0 text-[13px] text-texte-attenue">Aucun contrôle enregistré.</p>
          ) : (
            <Table legende="Derniers contrôles d'intégrité">
              <thead>
                <tr>
                  <Th>Lancé le</Th>
                  <Th>Déclencheur</Th>
                  <Th>Statut</Th>
                  <Th num>Événements</Th>
                </tr>
              </thead>
              <tbody>
                {controles.data.results.map((c) => (
                  <tr key={c.id}>
                    <Td mono>{formatDateHeureCourte(c.lance_le)}</Td>
                    <Td>{c.declencheur === "MANUEL" ? "Manuel" : "Planifié"}</Td>
                    <Td>
                      <Badge ton={LIBELLES_STATUT[c.statut].ton}>
                        {c.statut === "ROMPUE" ? `Rompue (n° ${c.premier_seq_invalide ?? "?"})` : LIBELLES_STATUT[c.statut].texte}
                      </Badge>
                    </Td>
                    <Td num>{c.nb_evenements ?? "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      )}
    </section>
  );
}

function valeur(v: unknown): string {
  if (v === null || v === undefined) return "—";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

/** Lignes « champ : avant → après » à partir des objets `avant` et `apres`. */
function differences(e: EvenementAudit): string[] {
  const avant = e.avant ?? {};
  const apres = e.apres ?? {};
  const cles = [...new Set([...Object.keys(avant), ...Object.keys(apres)])];
  return cles.map((c) => `${c} : ${valeur(avant[c])} → ${valeur(apres[c])}`);
}

export function LigneEvenement({ e }: { e: EvenementAudit }) {
  const { toast } = useToast();
  const diffs = differences(e);
  const copier = async () => {
    try {
      await navigator.clipboard.writeText(e.hash);
      toast({ titre: "Empreinte copiée", ton: "succes", duree: 3000 });
    } catch {
      toast({ titre: "Copie impossible", message: e.hash, ton: "alerte" });
    }
  };
  return (
    <tr>
      <Td mono>{formatHorodatage(e.horodatage)}</Td>
      <Td>{e.acteur_libelle}</Td>
      <Td>{e.action_libelle}</Td>
      <Td retourLigne className="min-w-[120px]">
        {e.objet_libelle || "—"}
      </Td>
      <Td retourLigne className="min-w-[180px] max-w-[260px] text-[13px]">
        {e.detail && <span className="block">{e.detail}</span>}
        {diffs.map((d) => (
          <span key={d} className="block font-mono text-[12px] text-texte-attenue">
            {d}
          </span>
        ))}
        {!e.detail && diffs.length === 0 && "—"}
      </Td>
      <Td mono>{e.ip ?? "—"}</Td>
      <Td mono>
        {e.hash ? (
          <button
            type="button"
            onClick={() => void copier()}
            title={e.hash}
            aria-label={`Copier l'empreinte complète de l'événement ${e.seq}`}
            className="cursor-pointer border-0 bg-transparent p-0 font-mono text-[14px] text-encre underline decoration-dotted underline-offset-2 hover:text-marque"
          >
            {e.hash_court}
          </button>
        ) : (
          "—"
        )}
      </Td>
    </tr>
  );
}

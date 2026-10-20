"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EnTetePage, ErreurChargement } from "@/components/shell/Etats";
import { Button, Card, Input, Table, Td, Th } from "@/components/ui";
import { useEtablissements } from "@/lib/api/hooks/plateforme";
import { formatDateHeureCourte } from "@/lib/format";
import { ModaleNouvelEtablissement } from "./ModaleNouvelEtablissement";
import { BadgeIntegrite, BadgeStatutEtablissement, libelleType } from "./statuts";

/** `/console` : établissements (écran 18), compteurs techniques et recherche par code ou raison sociale. */
export function EcranEtablissements() {
  const [recherche, setRecherche] = useState("");
  const [q, setQ] = useState("");
  const [creation, setCreation] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setQ(recherche), 300);
    return () => clearTimeout(t);
  }, [recherche]);

  const liste = useEtablissements(q);
  // Les tuiles portent sur tous les établissements, pas sur le résultat de la recherche (même requête si q est vide).
  const tous = useEtablissements("");

  const totaux = useMemo(() => {
    const e = tous.data ?? [];
    return {
      total: e.length,
      actifs: e.filter((x) => x.statut === "ACTIF").length,
      utilisateurs: e.reduce((s, x) => s + x.stats.nb_utilisateurs_actifs, 0),
      restreints: e.filter((x) => x.statut === "LECTURE_SEULE" || x.statut === "SUSPENDU").length,
    };
  }, [tous.data]);

  const lignes = liste.data ?? [];

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre="Établissements"
        sousTitre="Banques, SFD et PME clients d'ALPHA : création, administrateurs et suivi technique. Aucun contenu de dossier n'est accessible depuis cette console."
        actions={<Button onClick={() => setCreation(true)}>+ Nouvel établissement</Button>}
      />

      <section aria-label="Indicateurs" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tuile libelle="Établissements" valeur={tous.isSuccess ? totaux.total : undefined} />
        <Tuile libelle="Établissements actifs" valeur={tous.isSuccess ? totaux.actifs : undefined} />
        <Tuile libelle="Utilisateurs actifs" valeur={tous.isSuccess ? totaux.utilisateurs : undefined} />
        <Tuile libelle="Lecture seule ou suspendus" valeur={tous.isSuccess ? totaux.restreints : undefined} alerte={totaux.restreints > 0} />
      </section>

      <Card marge={false}>
        <div className="p-4">
          <Input
            type="search"
            label="Rechercher un établissement"
            labelMasque
            placeholder="Code ou raison sociale…"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            classeConteneur="max-w-[420px]"
          />
        </div>

        {liste.isPending ? (
          <p className="m-0 border-t border-ligne p-4 text-[15px] text-texte-attenue" role="status">
            Chargement des établissements…
          </p>
        ) : liste.isError ? (
          <div className="border-t border-ligne p-4">
            <ErreurChargement erreur={liste.error} titre="Établissements indisponibles" onReessayer={() => void liste.refetch()} />
          </div>
        ) : lignes.length === 0 ? (
          <p className="m-0 border-t border-ligne p-4 text-[15px] text-texte-2" role="status">
            {q.trim() ? "Aucun établissement ne correspond à cette recherche." : "Aucun établissement pour le moment. Créez le premier avec « + Nouvel établissement »."}
          </p>
        ) : (
          <Table legende="Établissements">
            <thead>
              <tr>
                <Th>Code</Th>
                <Th>Raison sociale et type</Th>
                <Th>Statut</Th>
                <Th num className="min-w-[96px] whitespace-normal">Utilisateurs actifs</Th>
                <Th className="min-w-[96px] whitespace-normal">Dernière activité</Th>
                <Th className="min-w-[96px] whitespace-normal">Intégrité du journal</Th>
              </tr>
            </thead>
            <tbody>
              {lignes.map((e) => (
                <tr key={e.id}>
                  <Td mono>{e.code}</Td>
                  <Td retourLigne className="min-w-[180px] font-semibold">
                    <Link href={`/console/etablissements/${e.id}`} className="text-encre underline-offset-2 hover:text-marque hover:underline">
                      {e.raison_sociale}
                    </Link>
                    <span className="block text-[13px] font-normal text-texte-attenue">{libelleType(e.type)}</span>
                  </Td>
                  <Td>
                    <BadgeStatutEtablissement statut={e.statut} />
                  </Td>
                  <Td num>
                    {e.stats.nb_utilisateurs_actifs}
                    {e.stats.nb_invites > 0 && <span className="ml-1.5 font-sans text-[12px] text-texte-attenue">+ {e.stats.nb_invites} invité{e.stats.nb_invites > 1 ? "s" : ""}</span>}
                  </Td>
                  <Td mono>{formatDateHeureCourte(e.stats.derniere_activite)}</Td>
                  <Td>
                    <BadgeIntegrite statut={e.stats.dernier_controle_statut} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {creation && <ModaleNouvelEtablissement onFermer={() => setCreation(false)} />}
    </div>
  );
}

export function Tuile({ libelle, valeur, alerte }: { libelle: string; valeur: number | string | undefined; alerte?: boolean }) {
  return (
    <div className="flex flex-col gap-1 rounded-carte border border-bordure bg-surface px-4.5 py-3.5">
      <span className="text-[13px] font-semibold text-texte-attenue">{libelle}</span>
      <span className={`font-mono text-[28px] font-semibold leading-none ${alerte ? "text-danger-texte" : "text-encre"}`}>{valeur ?? "–"}</span>
    </div>
  );
}

"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { AlerteErreur, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { Badge, Button, Card, Input, Modal, Select, Table, Td, Th, useToast, type TonBadge } from "@/components/ui";
import {
  useAnnulerAbsence,
  useCreerAbsence,
  useDelegataires,
  useDelegationsRecues,
  useMesAbsences,
  type Absence,
  type DelegatairePossible,
  type MotifAbsence,
  type StatutAbsence,
} from "@/lib/api/hooks/compte";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { estApiError } from "@/lib/api/erreurs";
import { formatDate } from "@/lib/format";
import { messageErreur } from "@/lib/compte/messages";
import { z } from "@/lib/zod";
import { cn } from "@/lib/cn";

export const MOTIFS: ReadonlyArray<{ valeur: MotifAbsence; libelle: string }> = [
  { valeur: "CONGE", libelle: "Congé" },
  { valeur: "MISSION", libelle: "Mission" },
  { valeur: "FORMATION", libelle: "Formation" },
  { valeur: "MALADIE", libelle: "Maladie" },
  { valeur: "AUTRE", libelle: "Autre" },
];

export const STATUTS_ABSENCE: Record<StatutAbsence, { libelle: string; ton: TonBadge }> = {
  SOUMISE: { libelle: "Soumise", ton: "ambre" },
  VALIDEE: { libelle: "Validée", ton: "vert" },
  REFUSEE: { libelle: "Refusée", ton: "rouge" },
  ANNULEE: { libelle: "Annulée", ton: "gris" },
};

/** Messages des refus métier d'une demande d'absence (409 / 400). */
const MESSAGES_ABSENCE: Record<string, string> = {
  CHEVAUCHEMENT: "Cette période chevauche une autre absence ou délégation déjà enregistrée.",
  POUVOIRS_INSUFFISANTS: "Ce délégataire n'a pas des pouvoirs au moins égaux aux vôtres : choisissez une autre personne.",
  SOUS_DELEGATION_INTERDITE: "Le délégataire est lui-même absent ou délègue déjà ses pouvoirs : la sous-délégation est interdite.",
  AUCUN_VALIDEUR: "Aucun valideur n'est disponible pour votre demande. Contactez un administrateur.",
  DELEGATAIRE_INVALIDE: "Ce délégataire n'est pas valide.",
  ROLE_NON_DETENU: "Vous ne détenez pas ce rôle.",
};

export function messageAbsence(e: unknown): string {
  return estApiError(e) && MESSAGES_ABSENCE[e.code] ? MESSAGES_ABSENCE[e.code]! : messageErreur(e);
}

/** Fuseau Africa/Dakar = UTC (pas d'heure d'été) : un jour entier va de 00:00 à 23:59 UTC. */
const debutDuJour = (d: string) => `${d}T00:00:00Z`;
const finDuJour = (d: string) => `${d}T23:59:00Z`;

const schema = z
  .object({
    du: z.string().min(1, "Indiquez le premier jour d'absence."),
    au: z.string().min(1, "Indiquez le dernier jour d'absence."),
    motif: z.enum(["CONGE", "MISSION", "FORMATION", "MALADIE", "AUTRE"]),
    commentaire: z.string().max(2000, "2 000 caractères au plus."),
  })
  .refine((v) => !v.du || !v.au || v.au >= v.du, { path: ["au"], message: "La fin ne peut pas précéder le début." });
type Valeurs = z.infer<typeof schema>;

/** Onglet « Absences et délégation » : formulaire, mes demandes, délégations reçues. */
export function OngletAbsences() {
  return (
    <div className="flex flex-col gap-5">
      <FormulaireAbsence />
      <MesAbsences />
      <DelegationsRecues />
    </div>
  );
}

function FormulaireAbsence() {
  const creer = useCreerAbsence();
  const { toast } = useToast();
  const [delegataire, setDelegataire] = useState<DelegatairePossible | null>(null);
  const [cle, setCle] = useState(0);
  const [erreurDelegataire, setErreurDelegataire] = useState<string | undefined>();
  const [erreur, setErreur] = useState<string | null>(null);
  const form = useForm<Valeurs>({ resolver: zodResolver(schema), defaultValues: { du: "", au: "", motif: "CONGE", commentaire: "" } });
  const { errors } = form.formState;

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    if (!delegataire) {
      setErreurDelegataire("Choisissez la personne qui vous remplacera.");
      return;
    }
    try {
      await creer.mutateAsync({ debut: debutDuJour(v.du), fin: finDuJour(v.au), motif: v.motif, commentaire: v.commentaire.trim(), delegataire_id: delegataire.id });
      toast({ ton: "succes", titre: "Demande d'absence envoyée", message: "Votre responsable doit la valider." });
      form.reset({ du: "", au: "", motif: "CONGE", commentaire: "" });
      setDelegataire(null);
      setCle((n) => n + 1);
    } catch (e) {
      if (estApiError(e) && e.estValidation) {
        const texte = appliquerErreursApi(e, form.setError, ["commentaire"]);
        const sur = e.erreursDeChamps;
        if (sur.delegataire_id) setErreurDelegataire(sur.delegataire_id.join(" "));
        setErreur(texte ? messageAbsence(e) : null);
      } else {
        setErreur(messageAbsence(e));
      }
    }
  });

  return (
    <Card titre="Déclarer une absence" description="Vos demandes iront à votre délégataire pendant cette période, après validation de votre responsable.">
      <form noValidate onSubmit={soumettre} className="flex max-w-[720px] flex-col gap-4">
        <AlerteErreur>{erreur}</AlerteErreur>
        <div className="grid gap-3 sm:grid-cols-3">
          <Input label="Du" type="date" required erreur={errors.du?.message} {...form.register("du")} />
          <Input label="Au" type="date" required erreur={errors.au?.message} {...form.register("au")} />
          <Select label="Motif" options={MOTIFS.map((m) => ({ valeur: m.valeur, libelle: m.libelle }))} {...form.register("motif")} />
        </div>
        <SelecteurDelegataire key={cle} valeur={delegataire} onChoisir={(d) => { setDelegataire(d); setErreurDelegataire(undefined); }} erreur={erreurDelegataire} />
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-texte-2">Commentaire</span>
          <textarea
            rows={3}
            className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
            {...form.register("commentaire")}
          />
          {errors.commentaire && <span className="text-[13px] font-medium text-danger-texte">{errors.commentaire.message}</span>}
        </label>
        <div>
          <Button type="submit" chargement={creer.isPending}>
            Soumettre la demande
          </Button>
        </div>
      </form>
    </Card>
  );
}

function SelecteurDelegataire({
  valeur,
  onChoisir,
  erreur,
}: {
  valeur: DelegatairePossible | null;
  onChoisir: (d: DelegatairePossible) => void;
  erreur?: string;
}) {
  const [q, setQ] = useState("");
  const [recherche, setRecherche] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setRecherche(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const candidats = useDelegataires(recherche);

  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
      <legend className="mb-1 p-0 text-[13px] font-semibold text-texte-2">
        Délégataire <span className="text-danger-texte" aria-hidden="true">*</span>
      </legend>
      <Input label="Rechercher un collaborateur" labelMasque type="search" placeholder="Rechercher par nom ou e-mail…" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      {valeur && (
        <p className="m-0 text-[14px] text-texte-2" role="status">
          Délégataire choisi : <strong>{valeur.nom}</strong>
          {valeur.role_principal ? ` · ${valeur.role_principal}` : ""}
        </p>
      )}
      <div role="radiogroup" aria-label="Délégataires possibles" className="max-h-56 overflow-y-auto rounded-champ border border-bordure">
        {candidats.isPending ? (
          <p className="m-0 px-3 py-2.5 text-[14px] text-texte-attenue" role="status">Recherche…</p>
        ) : candidats.isError ? (
          <p className="m-0 px-3 py-2.5 text-[14px] text-danger-texte" role="alert">{estApiError(candidats.error) ? candidats.error.message : "Recherche impossible."}</p>
        ) : candidats.data.length === 0 ? (
          <p className="m-0 px-3 py-2.5 text-[14px] text-texte-attenue">Aucun collaborateur ne correspond.</p>
        ) : (
          candidats.data.map((c) => (
            <label key={c.id} className={cn("flex cursor-pointer items-center gap-3 border-b border-ligne px-3 py-2.5 last:border-b-0", !c.pouvoirs_suffisants && "cursor-not-allowed opacity-70", valeur?.id === c.id && "bg-survol")}>
              <input
                type="radio"
                name="delegataire"
                value={c.id}
                checked={valeur?.id === c.id}
                disabled={!c.pouvoirs_suffisants}
                onChange={() => onChoisir(c)}
                className="h-4 w-4 flex-none accent-[var(--marque)]"
              />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-[14px] font-semibold text-encre">{c.nom}</span>
                {c.role_principal && <span className="text-[13px] text-texte-attenue">{c.role_principal}</span>}
              </span>
              {!c.pouvoirs_suffisants && <Badge ton="ambre">Pouvoirs insuffisants</Badge>}
            </label>
          ))
        )}
      </div>
      {erreur && <p className="m-0 text-[13px] font-medium text-danger-texte">{erreur}</p>}
    </fieldset>
  );
}

function MesAbsences() {
  const absences = useMesAbsences();
  const [aAnnuler, setAAnnuler] = useState<Absence | null>(null);
  return (
    <Card titre="Mes demandes d'absence" marge={false}>
      {absences.isPending ? (
        <div className="px-4.5 pb-4"><Chargement texte="Chargement de vos absences…" /></div>
      ) : absences.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={absences.error} titre="Absences indisponibles" onReessayer={() => void absences.refetch()} /></div>
      ) : absences.data.results.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucune demande d&rsquo;absence pour le moment.</p>
      ) : (
        <Table legende="Mes demandes d'absence">
          <thead>
            <tr>
              <Th>Période</Th>
              <Th>Motif</Th>
              <Th>Délégataire</Th>
              <Th>Statut</Th>
              <Th><span className="sr-only">Action</span></Th>
            </tr>
          </thead>
          <tbody>
            {absences.data.results.map((a) => {
              const st = STATUTS_ABSENCE[a.statut];
              return (
                <tr key={a.id}>
                  <Td mono>{formatDate(a.debut)} → {formatDate(a.fin)}</Td>
                  <Td>{a.motif_libelle}</Td>
                  <Td>{a.delegation?.delegataire.nom ?? "—"}</Td>
                  <Td retourLigne>
                    <Badge ton={st.ton}>{st.libelle}</Badge>
                    {a.statut === "REFUSEE" && a.motif_refus && <span className="mt-1 block text-[13px] text-texte-attenue">Motif : {a.motif_refus}</span>}
                  </Td>
                  <Td className="text-right">
                    {(a.statut === "SOUMISE" || a.statut === "VALIDEE") && (
                      <Button variante="secondaire" onClick={() => setAAnnuler(a)} aria-label={`Annuler l'absence du ${formatDate(a.debut)}`}>
                        Annuler
                      </Button>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {aAnnuler && <ModaleAnnulation absence={aAnnuler} onFermer={() => setAAnnuler(null)} />}
    </Card>
  );
}

function ModaleAnnulation({ absence, onFermer }: { absence: Absence; onFermer: () => void }) {
  const annuler = useAnnulerAbsence();
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  const confirmer = async () => {
    setErreur(null);
    try {
      await annuler.mutateAsync(absence.id);
      toast({ ton: "succes", titre: "Absence annulée" });
      onFermer();
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };
  return (
    <Modal
      ouvert
      onFermer={onFermer}
      titre="Annuler cette absence ?"
      description={`${absence.motif_libelle} du ${formatDate(absence.debut)} au ${formatDate(absence.fin)}`}
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer}>Conserver</Button>
          <Button chargement={annuler.isPending} onClick={confirmer}>Annuler l&rsquo;absence</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[14px] text-texte-2">
        <AlerteErreur>{erreur}</AlerteErreur>
        <p className="m-0">La délégation associée prend fin. Si l&rsquo;absence a déjà commencé, elle est écourtée à aujourd&rsquo;hui.</p>
      </div>
    </Modal>
  );
}

function DelegationsRecues() {
  const recues = useDelegationsRecues();
  return (
    <Card titre="Délégations reçues" description="Les demandes de vos collègues absents vous parviennent pendant ces périodes." marge={false}>
      {recues.isPending ? (
        <div className="px-4.5 pb-4"><Chargement /></div>
      ) : recues.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={recues.error} titre="Délégations indisponibles" onReessayer={() => void recues.refetch()} /></div>
      ) : recues.data.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucune délégation reçue.</p>
      ) : (
        <Table legende="Délégations reçues">
          <thead>
            <tr>
              <Th>Délégant</Th>
              <Th>Rôle</Th>
              <Th>Période</Th>
              <Th>Statut</Th>
            </tr>
          </thead>
          <tbody>
            {recues.data.map((d) => (
              <tr key={d.id}>
                <Td>{d.delegant.nom}</Td>
                <Td>{d.role?.libelle ?? "Tous ses rôles"}</Td>
                <Td mono>{formatDate(d.debut)} → {formatDate(d.fin)}</Td>
                <Td>
                  {d.effective ? <Badge ton="vert" point>En vigueur</Badge> : d.statut === "EN_ATTENTE" ? <Badge ton="ambre">En attente</Badge> : d.statut === "TERMINEE" ? <Badge ton="gris">Terminée</Badge> : <Badge ton="bleu">Programmée</Badge>}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

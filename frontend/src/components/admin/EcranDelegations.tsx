"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useId, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { MOTIFS, STATUTS_ABSENCE } from "@/components/compte/OngletAbsences";
import { AccesRefuse, AlerteErreur, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Input, Interrupteur, Modal, Select, Table, Td, Th, useToast, type TonBadge } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import {
  useAbsencesAdmin,
  useActionsAbsencesAdmin,
  useCandidatsAdmin,
  useDelegationsAdmin,
  type AbsenceAdmin,
  type Candidat,
  type DelegationAdmin,
  type FiltresPeriode,
  type StatutDelegation,
} from "@/lib/api/hooks/admin";
import { messageErreur } from "@/lib/compte/messages";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
import { possede } from "@/lib/permissions";
import { z } from "@/lib/zod";

/**
 * `/administration/delegations` (écran 12, onglet « Délégations ») : absences et délégations
 * de l'établissement. `admin.absences` : tout (déclarer pour un collaborateur, valider,
 * refuser, révoquer) ; `admin.utilisateurs` seul : délégations en lecture.
 * Les règles P5 (pouvoirs au moins égaux, pas de sous-délégation) sont contrôlées par l'API.
 */
export function EcranDelegations() {
  const moi = useMoi();
  const gereAbsences = possede(moi, "admin.absences");
  if (!gereAbsences && !possede(moi, "admin.utilisateurs")) return <AccesRefuse />;
  return (
    <div className="flex flex-col gap-5">
      {gereAbsences && <ListeAbsences />}
      <ListeDelegations peutRevoquer={gereAbsences} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filtres communs
// ---------------------------------------------------------------------------

function Filtres({
  valeur,
  onChange,
  statuts,
  libelleStatut,
}: {
  valeur: FiltresPeriode;
  onChange: (f: FiltresPeriode) => void;
  statuts: ReadonlyArray<{ valeur: string; libelle: string }>;
  libelleStatut: string;
}) {
  return (
    <>
      <Select
        label={libelleStatut}
        placeholder="Tous les statuts"
        value={valeur.statut}
        onChange={(e) => onChange({ ...valeur, statut: e.currentTarget.value })}
        options={statuts}
        classeConteneur="min-w-[150px] flex-1 basis-[170px]"
      />
      <Input label="Du" type="date" value={valeur.du} onChange={(e) => onChange({ ...valeur, du: e.currentTarget.value })} classeConteneur="min-w-[140px] flex-1 basis-[150px]" />
      <Input label="Au" type="date" value={valeur.au} onChange={(e) => onChange({ ...valeur, au: e.currentTarget.value })} classeConteneur="min-w-[140px] flex-1 basis-[150px]" />
    </>
  );
}

// ---------------------------------------------------------------------------
// Absences
// ---------------------------------------------------------------------------

/** Refus métier vus par l'administrateur (l'absent est un tiers). */
const MESSAGES_ADMIN: Record<string, string> = {
  CHEVAUCHEMENT: "Cette période chevauche une autre absence ou délégation déjà enregistrée pour ce collaborateur.",
  POUVOIRS_INSUFFISANTS: "Le délégataire n'a pas des pouvoirs au moins égaux à ceux de l'absent : choisissez une autre personne.",
  SOUS_DELEGATION_INTERDITE: "L'absent ou le délégataire est déjà concerné par une délégation sur cette période : la sous-délégation est interdite.",
  AUCUN_VALIDEUR: "Aucun valideur n'est disponible pour cette demande.",
  DELEGATAIRE_INVALIDE: "Ce délégataire n'est pas valide.",
  STATUT_INVALIDE: "Cette absence a déjà été traitée : actualisez la liste.",
  ABSENCE_EXPIREE: "Cette absence est terminée : elle ne peut plus être validée.",
};

function messageAbsence(e: unknown): string {
  return estApiError(e) && MESSAGES_ADMIN[e.code] ? MESSAGES_ADMIN[e.code]! : messageErreur(e);
}

const OPTIONS_STATUT_ABSENCE = (Object.keys(STATUTS_ABSENCE) as Array<keyof typeof STATUTS_ABSENCE>).map((s) => ({ valeur: s, libelle: STATUTS_ABSENCE[s].libelle }));

function ListeAbsences() {
  const [filtres, setFiltres] = useState<FiltresPeriode>({ statut: "SOUMISE", du: "", au: "" });
  const absences = useAbsencesAdmin(filtres);
  const actions = useActionsAbsencesAdmin();
  const { toast } = useToast();
  const [declaration, setDeclaration] = useState(false);
  const [aRefuser, setARefuser] = useState<AbsenceAdmin | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const lignes = useMemo(() => absences.data?.pages.flatMap((p) => p.results) ?? [], [absences.data]);
  const total = absences.data?.pages[0]?.count ?? 0;

  const valider = async (a: AbsenceAdmin) => {
    setErreur(null);
    try {
      await actions.valider.mutateAsync(a.id);
      toast({ ton: "succes", titre: "Absence validée", message: `La délégation de ${a.demandeur.nom} est active.` });
    } catch (e) {
      setErreur(messageAbsence(e));
    }
  };

  return (
    <Card
      titre="Absences"
      description="Demandes d'absence de l'établissement, en attente ou décidées."
      actions={<Button onClick={() => setDeclaration(true)}>+ Déclarer une absence</Button>}
      marge={false}
    >
      <div className="flex flex-wrap items-end gap-3 px-4.5 pb-4">
        <Filtres valeur={filtres} onChange={setFiltres} statuts={OPTIONS_STATUT_ABSENCE} libelleStatut="Statut de l'absence" />
      </div>
      {erreur && <div className="px-4.5 pb-3"><AlerteErreur>{erreur}</AlerteErreur></div>}
      {absences.isPending ? (
        <div className="px-4.5 pb-4"><Chargement texte="Chargement des absences…" /></div>
      ) : absences.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={absences.error} titre="Absences indisponibles" onReessayer={() => void absences.refetch()} /></div>
      ) : lignes.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue" role="status">Aucune absence ne correspond à ces filtres.</p>
      ) : (
        <Table legende={`Absences de l'établissement (${total})`}>
          <thead>
            <tr>
              <Th>Collaborateur</Th>
              <Th>Période</Th>
              <Th>Motif</Th>
              <Th>Délégataire</Th>
              <Th>Statut</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((a) => {
              const st = STATUTS_ABSENCE[a.statut];
              return (
                <tr key={a.id}>
                  <Td>
                    <span className="block font-semibold text-encre">{a.demandeur.nom}</span>
                    {a.valideur && <span className="block text-[13px] text-texte-attenue">Valideur : {a.valideur.nom}</span>}
                  </Td>
                  <Td mono>{formatDate(a.debut)} → {formatDate(a.fin)}</Td>
                  <Td>{a.motif_libelle}</Td>
                  <Td>{a.delegation?.delegataire.nom ?? "—"}</Td>
                  <Td retourLigne>
                    <Badge ton={st.ton}>{st.libelle}</Badge>
                    {a.statut === "REFUSEE" && a.motif_refus && <span className="mt-1 block text-[13px] text-texte-attenue">Motif : {a.motif_refus}</span>}
                  </Td>
                  <Td className="text-right">
                    {a.peut_decider && (
                      <div className="flex justify-end gap-2">
                        <Button
                          variante="secondaire"
                          onClick={() => setARefuser(a)}
                          disabled={actions.valider.isPending}
                          aria-label={`Refuser l'absence de ${a.demandeur.nom}`}
                        >
                          Refuser
                        </Button>
                        <Button
                          chargement={actions.valider.isPending && actions.valider.variables === a.id}
                          disabled={actions.valider.isPending}
                          onClick={() => void valider(a)}
                          aria-label={`Valider l'absence de ${a.demandeur.nom}`}
                        >
                          Valider
                        </Button>
                      </div>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {absences.hasNextPage && (
        <div className="flex justify-center border-t border-ligne px-4.5 py-3">
          <Button variante="secondaire" chargement={absences.isFetchingNextPage} onClick={() => void absences.fetchNextPage()}>
            Afficher plus d&rsquo;absences
          </Button>
        </div>
      )}
      {declaration && <ModaleDeclaration onFermer={() => setDeclaration(false)} />}
      {aRefuser && <ModaleRefus absence={aRefuser} onFermer={() => setARefuser(null)} />}
    </Card>
  );
}

function ModaleRefus({ absence, onFermer }: { absence: AbsenceAdmin; onFermer: () => void }) {
  const { refuser } = useActionsAbsencesAdmin();
  const { toast } = useToast();
  const [motif, setMotif] = useState("");
  const [erreurChamp, setErreurChamp] = useState<string | undefined>();
  const [erreur, setErreur] = useState<string | null>(null);
  const confirmer = async () => {
    setErreur(null);
    if (!motif.trim()) {
      setErreurChamp("Indiquez le motif du refus.");
      return;
    }
    try {
      await refuser.mutateAsync({ id: absence.id, motif: motif.trim() });
      toast({ ton: "succes", titre: "Absence refusée", message: `${absence.demandeur.nom} en est informé.` });
      onFermer();
    } catch (e) {
      setErreur(messageAbsence(e));
    }
  };
  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!refuser.isPending}
      titre="Refuser cette absence ?"
      description={`${absence.demandeur.nom} · ${absence.motif_libelle} du ${formatDate(absence.debut)} au ${formatDate(absence.fin)}`}
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={refuser.isPending}>Annuler</Button>
          <Button chargement={refuser.isPending} onClick={() => void confirmer()}>Refuser l&rsquo;absence</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <AlerteErreur>{erreur}</AlerteErreur>
        <ZoneTexte label="Motif du refus" requis valeur={motif} onChange={(v) => { setMotif(v); setErreurChamp(undefined); }} erreur={erreurChamp} />
      </div>
    </Modal>
  );
}

/** Fuseau Africa/Dakar = UTC : un jour entier va de 00:00 à 23:59 UTC (comme « Mon compte »). */
const debutDuJour = (d: string) => `${d}T00:00:00Z`;
const finDuJour = (d: string) => `${d}T23:59:00Z`;

const schemaDeclaration = z
  .object({
    du: z.string().min(1, "Indiquez le premier jour d'absence."),
    au: z.string().min(1, "Indiquez le dernier jour d'absence."),
    motif: z.enum(["CONGE", "MISSION", "FORMATION", "MALADIE", "AUTRE"]),
    commentaire: z.string().max(2000, "2 000 caractères au plus."),
  })
  .refine((v) => !v.du || !v.au || v.au >= v.du, { path: ["au"], message: "La fin ne peut pas précéder le début." });
type ValeursDeclaration = z.infer<typeof schemaDeclaration>;

function ModaleDeclaration({ onFermer }: { onFermer: () => void }) {
  const idForm = useId();
  const { creer } = useActionsAbsencesAdmin();
  const { toast } = useToast();
  const [absent, setAbsent] = useState<Candidat | null>(null);
  const [delegataire, setDelegataire] = useState<Candidat | null>(null);
  const [valider, setValider] = useState(false);
  const [erreurAbsent, setErreurAbsent] = useState<string | undefined>();
  const [erreurDelegataire, setErreurDelegataire] = useState<string | undefined>();
  const [erreur, setErreur] = useState<string | null>(null);
  const form = useForm<ValeursDeclaration>({ resolver: zodResolver(schemaDeclaration), defaultValues: { du: "", au: "", motif: "CONGE", commentaire: "" } });
  const { errors } = form.formState;

  /** Les choix de personnes sont contrôlés en même temps que les champs du formulaire. */
  const personnesChoisies = () => {
    if (!absent) setErreurAbsent("Choisissez le collaborateur absent.");
    else if (!delegataire) setErreurDelegataire("Choisissez la personne qui le remplacera.");
    return Boolean(absent && delegataire);
  };

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    if (!personnesChoisies() || !absent || !delegataire) return;
    try {
      await creer.mutateAsync({
        utilisateur_id: absent.id,
        debut: debutDuJour(v.du),
        fin: finDuJour(v.au),
        motif: v.motif,
        commentaire: v.commentaire.trim(),
        delegataire_id: delegataire.id,
        valider,
      });
      toast({
        ton: "succes",
        titre: valider ? "Absence enregistrée et validée" : "Absence déclarée",
        message: valider ? `${delegataire.nom} remplacera ${absent.nom} sur cette période.` : `La demande de ${absent.nom} attend la décision de son valideur.`,
      });
      onFermer();
    } catch (e) {
      if (estApiError(e) && e.estValidation) {
        const sur = e.erreursDeChamps;
        if (sur.utilisateur_id) setErreurAbsent(sur.utilisateur_id.join(" "));
        if (sur.delegataire_id) setErreurDelegataire(sur.delegataire_id.join(" "));
        const texte = appliquerErreursApi(e, form.setError, ["commentaire"]);
        if (sur.debut || sur.fin) form.setError("au", { type: "serveur", message: [...(sur.debut ?? []), ...(sur.fin ?? [])].join(" ") });
        setErreur(texte ? messageAbsence(e) : null);
      } else {
        setErreur(messageAbsence(e));
      }
    }
  }, personnesChoisies);

  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!creer.isPending}
      taille="large"
      titre="Déclarer une absence"
      description="Pour un collaborateur qui ne peut pas la saisir lui-même. Le délégataire doit détenir des pouvoirs au moins égaux aux siens."
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={creer.isPending}>Annuler</Button>
          <Button type="submit" form={idForm} chargement={creer.isPending}>{valider ? "Enregistrer et valider" : "Déclarer l'absence"}</Button>
        </>
      }
    >
      <form id={idForm} noValidate onSubmit={soumettre} className="flex flex-col gap-4">
        <AlerteErreur>{erreur}</AlerteErreur>
        <SelecteurCandidat
          legende="Collaborateur absent"
          nom="absent"
          pour={null}
          valeur={absent}
          onChoisir={(c) => {
            setAbsent(c);
            setDelegataire(null);
            setErreurAbsent(undefined);
          }}
          erreur={erreurAbsent}
        />
        <div className="grid gap-3 sm:grid-cols-3">
          <Input label="Du" type="date" required erreur={errors.du?.message} {...form.register("du")} />
          <Input label="Au" type="date" required erreur={errors.au?.message} {...form.register("au")} />
          <Select label="Motif" options={MOTIFS.map((m) => ({ valeur: m.valeur, libelle: m.libelle }))} {...form.register("motif")} />
        </div>
        {absent ? (
          <SelecteurCandidat
            key={absent.id}
            legende="Délégataire"
            nom="delegataire"
            pour={absent.id}
            valeur={delegataire}
            onChoisir={(c) => {
              setDelegataire(c);
              setErreurDelegataire(undefined);
            }}
            erreur={erreurDelegataire}
          />
        ) : (
          <p className="m-0 text-[14px] text-texte-attenue">Choisissez d&rsquo;abord le collaborateur absent pour voir les délégataires possibles.</p>
        )}
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-texte-2">Commentaire</span>
          <textarea
            rows={2}
            className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
            {...form.register("commentaire")}
          />
          {errors.commentaire && <span className="text-[13px] font-medium text-danger-texte">{errors.commentaire.message}</span>}
        </label>
        <Interrupteur
          label="Valider immédiatement"
          description="Sinon, la demande part au responsable du collaborateur (à défaut, à un administrateur)."
          actif={valider}
          onChange={setValider}
        />
      </form>
    </Modal>
  );
}

function SelecteurCandidat({
  legende,
  nom,
  pour,
  valeur,
  onChoisir,
  erreur,
}: {
  legende: string;
  nom: string;
  pour: string | null;
  valeur: Candidat | null;
  onChoisir: (c: Candidat) => void;
  erreur?: string;
}) {
  const [q, setQ] = useState("");
  const [recherche, setRecherche] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setRecherche(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const candidats = useCandidatsAdmin(recherche, pour);
  const controle = pour !== null;

  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
      <legend className="mb-1 p-0 text-[13px] font-semibold text-texte-2">
        {legende} <span className="text-danger-texte" aria-hidden="true">*</span>
      </legend>
      <Input label={`Rechercher : ${legende.toLowerCase()}`} labelMasque type="search" placeholder="Rechercher par nom ou e-mail…" value={q} onChange={(e) => setQ(e.currentTarget.value)} />
      {valeur && (
        <p className="m-0 text-[14px] text-texte-2" role="status">
          {legende} : <strong>{valeur.nom}</strong>
          {valeur.role_principal ? ` · ${valeur.role_principal}` : ""}
        </p>
      )}
      <div role="radiogroup" aria-label={legende} className="max-h-44 overflow-y-auto rounded-champ border border-bordure">
        {candidats.isPending ? (
          <p className="m-0 px-3 py-2.5 text-[14px] text-texte-attenue" role="status">Recherche…</p>
        ) : candidats.isError ? (
          <p className="m-0 px-3 py-2.5 text-[14px] text-danger-texte" role="alert">{messageErreur(candidats.error)}</p>
        ) : candidats.data.length === 0 ? (
          <p className="m-0 px-3 py-2.5 text-[14px] text-texte-attenue">Aucun collaborateur ne correspond.</p>
        ) : (
          candidats.data.map((c) => {
            const bloque = controle && c.pouvoirs_suffisants === false;
            return (
              <label key={c.id} className={cn("flex cursor-pointer items-center gap-3 border-b border-ligne px-3 py-2.5 last:border-b-0", bloque && "cursor-not-allowed opacity-70", valeur?.id === c.id && "bg-survol")}>
                <input
                  type="radio"
                  name={nom}
                  value={c.id}
                  checked={valeur?.id === c.id}
                  disabled={bloque}
                  onChange={() => onChoisir(c)}
                  className="h-4 w-4 flex-none accent-[var(--marque)]"
                />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-[14px] font-semibold text-encre">{c.nom}</span>
                  {c.role_principal && <span className="text-[13px] text-texte-attenue">{c.role_principal}</span>}
                </span>
                {bloque && <Badge ton="ambre">Pouvoirs insuffisants</Badge>}
              </label>
            );
          })
        )}
      </div>
      {erreur && <p className="m-0 text-[13px] font-medium text-danger-texte">{erreur}</p>}
    </fieldset>
  );
}

// ---------------------------------------------------------------------------
// Délégations
// ---------------------------------------------------------------------------

const STATUTS_DELEGATION: Record<StatutDelegation, { libelle: string; ton: TonBadge }> = {
  EN_ATTENTE: { libelle: "En attente", ton: "ambre" },
  ACTIVE: { libelle: "Programmée", ton: "bleu" },
  TERMINEE: { libelle: "Terminée", ton: "gris" },
  ANNULEE: { libelle: "Annulée", ton: "gris" },
  REFUSEE: { libelle: "Refusée", ton: "rouge" },
};
const OPTIONS_STATUT_DELEGATION = [
  { valeur: "ACTIVE", libelle: "Active (programmée ou en vigueur)" },
  { valeur: "EN_ATTENTE", libelle: "En attente" },
  { valeur: "TERMINEE", libelle: "Terminée" },
  { valeur: "ANNULEE", libelle: "Annulée" },
  { valeur: "REFUSEE", libelle: "Refusée" },
];

function BadgeDelegation({ d }: { d: DelegationAdmin }) {
  if (d.effective) return <Badge ton="vert" point>En vigueur</Badge>;
  const st = STATUTS_DELEGATION[d.statut];
  return <Badge ton={st.ton}>{st.libelle}</Badge>;
}

function ListeDelegations({ peutRevoquer }: { peutRevoquer: boolean }) {
  const [filtres, setFiltres] = useState<FiltresPeriode>({ statut: "ACTIVE", du: "", au: "" });
  const delegations = useDelegationsAdmin(filtres);
  const [aRevoquer, setARevoquer] = useState<DelegationAdmin | null>(null);
  const lignes = useMemo(() => delegations.data?.pages.flatMap((p) => p.results) ?? [], [delegations.data]);
  const total = delegations.data?.pages[0]?.count ?? 0;

  return (
    <Card
      titre="Délégations"
      description={
        peutRevoquer
          ? "Pendant une absence validée, le délégataire traite les tâches de l'absent. Une délégation active peut être révoquée."
          : "Pendant une absence validée, le délégataire traite les tâches de l'absent. Consultation seule."
      }
      marge={false}
    >
      <div className="flex flex-wrap items-end gap-3 px-4.5 pb-4">
        <Filtres valeur={filtres} onChange={setFiltres} statuts={OPTIONS_STATUT_DELEGATION} libelleStatut="Statut de la délégation" />
      </div>
      {delegations.isPending ? (
        <div className="px-4.5 pb-4"><Chargement texte="Chargement des délégations…" /></div>
      ) : delegations.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={delegations.error} titre="Délégations indisponibles" onReessayer={() => void delegations.refetch()} /></div>
      ) : lignes.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue" role="status">Aucune délégation ne correspond à ces filtres.</p>
      ) : (
        <Table legende={`Délégations de l'établissement (${total})`}>
          <thead>
            <tr>
              <Th>Délégant (absent)</Th>
              <Th>Délégataire</Th>
              <Th>Rôle</Th>
              <Th>Période</Th>
              <Th>Statut</Th>
              {peutRevoquer && <Th><span className="sr-only">Action</span></Th>}
            </tr>
          </thead>
          <tbody>
            {lignes.map((d) => (
              <tr key={d.id}>
                <Td><span className="font-semibold text-encre">{d.delegant.nom}</span></Td>
                <Td>{d.delegataire.nom}</Td>
                <Td>{d.role?.libelle ?? "Tous ses rôles"}</Td>
                <Td mono>{formatDate(d.debut)} → {formatDate(d.fin)}</Td>
                <Td><BadgeDelegation d={d} /></Td>
                {peutRevoquer && (
                  <Td className="text-right">
                    {d.statut === "ACTIVE" && (
                      <Button variante="secondaire" onClick={() => setARevoquer(d)} aria-label={`Révoquer la délégation de ${d.delegant.nom} à ${d.delegataire.nom}`}>
                        Révoquer
                      </Button>
                    )}
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {delegations.hasNextPage && (
        <div className="flex justify-center border-t border-ligne px-4.5 py-3">
          <Button variante="secondaire" chargement={delegations.isFetchingNextPage} onClick={() => void delegations.fetchNextPage()}>
            Afficher plus de délégations
          </Button>
        </div>
      )}
      {aRevoquer && <ModaleRevocation delegation={aRevoquer} onFermer={() => setARevoquer(null)} />}
    </Card>
  );
}

function ModaleRevocation({ delegation, onFermer }: { delegation: DelegationAdmin; onFermer: () => void }) {
  const { revoquer } = useActionsAbsencesAdmin();
  const { toast } = useToast();
  const [motif, setMotif] = useState("");
  const [erreurChamp, setErreurChamp] = useState<string | undefined>();
  const [erreur, setErreur] = useState<string | null>(null);
  const confirmer = async () => {
    setErreur(null);
    if (!motif.trim()) {
      setErreurChamp("Indiquez le motif de la révocation.");
      return;
    }
    try {
      await revoquer.mutateAsync({ id: delegation.id, motif: motif.trim() });
      toast({ ton: "succes", titre: "Délégation révoquée", message: `${delegation.delegataire.nom} ne traite plus les tâches de ${delegation.delegant.nom}.` });
      onFermer();
    } catch (e) {
      setErreur(estApiError(e) && e.code === "STATUT_INVALIDE" ? "Cette délégation n'est plus active : actualisez la liste." : messageErreur(e));
    }
  };
  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!revoquer.isPending}
      titre="Révoquer cette délégation ?"
      description={`${delegation.delegant.nom} → ${delegation.delegataire.nom} · du ${formatDate(delegation.debut)} au ${formatDate(delegation.fin)}`}
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={revoquer.isPending}>Conserver</Button>
          <Button chargement={revoquer.isPending} onClick={() => void confirmer()}>Révoquer</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[14px] text-texte-2">
        <AlerteErreur>{erreur}</AlerteErreur>
        <p className="m-0">
          Le délégataire perd aussitôt l&rsquo;accès aux tâches de l&rsquo;absent. L&rsquo;absence reste enregistrée. Cette décision est inscrite au journal d&rsquo;audit.
        </p>
        <ZoneTexte label="Motif de la révocation" requis valeur={motif} onChange={(v) => { setMotif(v); setErreurChamp(undefined); }} erreur={erreurChamp} />
      </div>
    </Modal>
  );
}

function ZoneTexte({ label, requis, valeur, onChange, erreur }: { label: string; requis?: boolean; valeur: string; onChange: (v: string) => void; erreur?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-semibold text-texte-2">
        {label} {requis && <span className="text-danger-texte" aria-hidden="true">*</span>}
      </label>
      <textarea
        id={id}
        rows={3}
        maxLength={2000}
        required={requis}
        aria-invalid={erreur ? true : undefined}
        aria-describedby={erreur ? `${id}-err` : undefined}
        value={valeur}
        onChange={(e) => onChange(e.currentTarget.value)}
        className={cn(
          "block w-full rounded-champ border bg-surface px-3 py-2 text-[14px] text-encre focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque",
          erreur ? "border-danger-texte" : "border-bordure-champ",
        )}
      />
      {erreur && <span id={`${id}-err`} className="text-[13px] font-medium text-danger-texte">{erreur}</span>}
    </div>
  );
}

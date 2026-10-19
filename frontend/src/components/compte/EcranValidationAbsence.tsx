"use client";

import Link from "next/link";
import { useState } from "react";
import { AlerteErreur, AlerteInfo, Chargement, EnTetePage, ErreurChargement } from "@/components/shell/Etats";
import { Badge, Button, Card, Modal, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { useAbsence, useRefuserAbsence, useValiderAbsence } from "@/lib/api/hooks/compte";
import { formatDate, formatDateHeureCourte } from "@/lib/format";
import { STATUTS_ABSENCE, messageAbsence } from "./OngletAbsences";

const MESSAGES_DECISION: Record<string, string> = {
  STATUT_INVALIDE: "Cette demande a déjà été traitée.",
  ABSENCE_EXPIREE: "Cette absence est déjà terminée : elle ne peut plus être validée.",
};

function messageDecision(e: unknown): string {
  return estApiError(e) && MESSAGES_DECISION[e.code] ? MESSAGES_DECISION[e.code]! : messageAbsence(e);
}

/** `/absences/[id]` : validation ou refus d'une demande d'absence par le responsable (cible des tâches de validation). */
export function EcranValidationAbsence({ id }: { id: string }) {
  const absence = useAbsence(id);
  const valider = useValiderAbsence(id);
  const { toast } = useToast();
  const [refus, setRefus] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  if (absence.isPending) return <Chargement texte="Chargement de la demande…" />;
  if (absence.isError) {
    const introuvable = estApiError(absence.error) && absence.error.status === 404;
    return introuvable ? (
      <Card titre="Demande introuvable">
        <p className="m-0 text-[15px] text-texte-2" role="alert">
          Cette demande d&rsquo;absence n&rsquo;existe pas ou vous n&rsquo;avez pas le droit de la consulter.
        </p>
        <div className="mt-3">
          <Link href="/a-traiter">Retour à « À traiter »</Link>
        </div>
      </Card>
    ) : (
      <ErreurChargement erreur={absence.error} titre="Demande indisponible" onReessayer={() => void absence.refetch()} />
    );
  }

  const a = absence.data;
  const st = STATUTS_ABSENCE[a.statut];
  const decision = a.peut_decider && a.statut === "SOUMISE";

  const accepter = async () => {
    setErreur(null);
    try {
      await valider.mutateAsync();
      toast({ ton: "succes", titre: "Absence validée", message: "La délégation est active sur la période." });
    } catch (e) {
      setErreur(messageDecision(e));
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre={`Demande d'absence · ${a.demandeur.nom}`}
        sousTitre={
          <>
            <Link href="/a-traiter">← Retour à « À traiter »</Link>
          </>
        }
      />
      <Card titre="Demande" actions={<Badge ton={st.ton}>{st.libelle}</Badge>}>
        <dl className="m-0 grid gap-x-8 gap-y-3 text-[14px] sm:grid-cols-2">
          <Ligne terme="Demandeur" valeur={a.demandeur.nom} />
          <Ligne terme="Motif" valeur={a.motif_libelle} />
          <Ligne terme="Période" valeur={`${formatDate(a.debut)} → ${formatDate(a.fin)}`} mono />
          <Ligne terme="Délégataire" valeur={a.delegation?.delegataire.nom ?? "—"} />
          <Ligne terme="Rôle délégué" valeur={a.delegation ? (a.delegation.role?.libelle ?? "Tous les rôles du demandeur") : "—"} />
          <Ligne terme="Demandée le" valeur={formatDateHeureCourte(a.cree_le)} mono />
          {a.commentaire && <Ligne terme="Commentaire" valeur={a.commentaire} large />}
          {a.valideur && <Ligne terme="Valideur" valeur={a.valideur.nom} />}
          {a.decide_le && <Ligne terme="Décision le" valeur={formatDateHeureCourte(a.decide_le)} mono />}
          {a.statut === "REFUSEE" && a.motif_refus && <Ligne terme="Motif du refus" valeur={a.motif_refus} large />}
        </dl>
      </Card>

      <AlerteErreur>{erreur}</AlerteErreur>
      {decision ? (
        <div className="flex flex-wrap gap-2">
          <Button variante="validation" chargement={valider.isPending} onClick={accepter}>
            Valider
          </Button>
          <Button variante="secondaire" onClick={() => setRefus(true)}>
            Refuser
          </Button>
        </div>
      ) : (
        <AlerteInfo ton="bleu">
          {a.statut === "SOUMISE" ? "Vous ne pouvez pas décider de cette demande : elle est consultable en lecture seule." : "Cette demande a été traitée."}
        </AlerteInfo>
      )}
      {refus && <ModaleRefus id={id} onFermer={() => setRefus(false)} />}
    </div>
  );
}

function Ligne({ terme, valeur, mono, large }: { terme: string; valeur: string; mono?: boolean; large?: boolean }) {
  return (
    <div className={large ? "sm:col-span-2" : undefined}>
      <dt className="text-[12px] font-semibold uppercase tracking-[.04em] text-texte-attenue">{terme}</dt>
      <dd className={mono ? "m-0 font-mono text-[14px]" : "m-0 text-[14px]"}>{valeur}</dd>
    </div>
  );
}

function ModaleRefus({ id, onFermer }: { id: string; onFermer: () => void }) {
  const refuser = useRefuserAbsence(id);
  const { toast } = useToast();
  const [motif, setMotif] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const envoyer = async () => {
    setErreur(null);
    try {
      await refuser.mutateAsync(motif.trim());
      toast({ ton: "succes", titre: "Absence refusée" });
      onFermer();
    } catch (e) {
      setErreur(messageDecision(e));
    }
  };
  return (
    <Modal
      ouvert
      onFermer={onFermer}
      titre="Refuser la demande d'absence"
      description="Le motif est communiqué au demandeur."
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer}>
            Annuler
          </Button>
          <Button chargement={refuser.isPending} disabled={motif.trim() === ""} onClick={envoyer}>
            Refuser la demande
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <AlerteErreur>{erreur}</AlerteErreur>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-texte-2">
            Motif du refus <span className="text-danger-texte" aria-hidden="true">*</span>
          </span>
          <textarea
            rows={4}
            required
            maxLength={2000}
            value={motif}
            onChange={(e) => setMotif(e.currentTarget.value)}
            className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
          />
        </label>
      </div>
    </Modal>
  );
}

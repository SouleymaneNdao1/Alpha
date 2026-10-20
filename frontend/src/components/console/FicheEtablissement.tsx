"use client";

import Link from "next/link";
import { useState, type ChangeEvent, type ReactNode } from "react";
import { AlerteInfo, Chargement, EnTetePage, ErreurChargement } from "@/components/shell/Etats";
import { Button, Card, Input, ModaleCode, Select, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import {
  SUSPENSION_DESACTIVEE,
  useActionsEtablissement,
  useEtablissement,
  type EtablissementDetail,
  type StatutEtablissement,
} from "@/lib/api/hooks/plateforme";
import { formatDate, formatDateHeureCourte } from "@/lib/format";
import { BadgeIntegrite, BadgeStatutEtablissement, libelleType } from "./statuts";

type Action = "modifier" | "inviter" | "reinitialiser" | "statut";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** `/console/etablissements/[id]` : fiche d'un établissement (métadonnées et compteurs uniquement). */
export function FicheEtablissement({ id }: { id: string }) {
  const requete = useEtablissement(id);
  const [action, setAction] = useState<Action | null>(null);
  // Mis à `true` si l'API répond 403 SUSPENSION_MANUELLE_DESACTIVEE : les boutons de statut disparaissent.
  const [suspensionCoupee, setSuspensionCoupee] = useState(false);

  if (requete.isPending) return <Chargement texte="Chargement de l'établissement…" />;
  if (requete.isError) {
    const introuvable = estApiError(requete.error) && requete.error.status === 404;
    return (
      <div className="flex flex-col gap-3">
        <ErreurChargement
          erreur={requete.error}
          titre={introuvable ? "Établissement introuvable" : "Établissement indisponible"}
          onReessayer={introuvable ? undefined : () => void requete.refetch()}
        />
        <div>
          <Link href="/console" className="text-[14px] font-semibold">
            ← Tous les établissements
          </Link>
        </div>
      </div>
    );
  }

  const e = requete.data;
  const archive = e.statut === "ARCHIVE";
  const suspensionDisponible = e.suspension_manuelle_disponible && !suspensionCoupee && !archive;
  const ferme = () => setAction(null);

  return (
    <div className="flex flex-col gap-5">
      <nav aria-label="Fil d'Ariane" className="text-[13px]">
        <Link href="/console">← Tous les établissements</Link>
      </nav>

      <EnTetePage
        titre={e.raison_sociale}
        sousTitre={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[14px]">{e.code}</span>
            <span aria-hidden="true">·</span>
            <span>{libelleType(e.type)}</span>
            <BadgeStatutEtablissement statut={e.statut} />
          </span>
        }
        actions={
          <Button variante="secondaire" disabled={archive} onClick={() => setAction("modifier")}>
            Modifier
          </Button>
        }
      />

      {archive && <AlerteInfo>Cet établissement est archivé : aucune modification n&apos;est possible.</AlerteInfo>}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card titre="Informations">
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-[14px]">
            <Ligne libelle="Code" valeur={<span className="font-mono">{e.code}</span>} />
            <Ligne libelle="Raison sociale" valeur={e.raison_sociale} />
            <Ligne libelle="Type" valeur={libelleType(e.type)} />
            <Ligne libelle="Pays" valeur={e.pays} />
            <Ligne libelle="Fuseau horaire" valeur={e.fuseau_horaire} />
            <Ligne libelle="Créé le" valeur={formatDate(e.cree_le)} />
            <Ligne libelle="Modifié le" valeur={formatDateHeureCourte(e.modifie_le)} />
          </dl>
        </Card>

        <Card titre="Compteurs techniques" description="Seuls des compteurs sont visibles : aucun nom d'utilisateur, aucun dossier.">
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2.5 text-[14px]">
            <Ligne libelle="Utilisateurs actifs" valeur={<span className="font-mono">{e.stats.nb_utilisateurs_actifs}</span>} />
            <Ligne libelle="Invitations en attente" valeur={<span className="font-mono">{e.stats.nb_invites}</span>} />
            <Ligne libelle="Dernière activité" valeur={<span className="font-mono">{formatDateHeureCourte(e.stats.derniere_activite)}</span>} />
            <Ligne libelle="Événements d'audit (30 j)" valeur={<span className="font-mono">{e.stats.nb_evenements_audit_30j}</span>} />
            <Ligne libelle="Intégrité du journal" valeur={<BadgeIntegrite statut={e.stats.dernier_controle_statut} />} />
          </dl>
        </Card>
      </div>

      <Card
        titre="Administrateurs"
        description="Le rôle « Administrateur ALPHA » gère les comptes de l'établissement. Les invitations sont envoyées par e-mail (valables 72 h)."
      >
        <div className="flex flex-col gap-4">
          <div>
            <Button disabled={archive} onClick={() => setAction("inviter")}>
              Inviter un administrateur
            </Button>
          </div>
          <div className="flex flex-col gap-2 rounded-champ border border-bordure bg-entete-tableau p-3.5">
            <h3 className="m-0 text-[14px] font-semibold text-encre">Dernier administrateur : Authenticator perdu</h3>
            <p className="m-0 text-[13px] text-texte-2">
              Réservé au cas où aucun autre administrateur actif ne peut traiter la demande (décision P4) : demande écrite signée de la direction du client et
              appel vidéo avec pièce d&apos;identité. La référence de la demande est enregistrée au journal et les autres administrateurs sont prévenus.
            </p>
            <div>
              <Button variante="secondaire" disabled={archive} onClick={() => setAction("reinitialiser")}>
                Réinitialiser l&apos;Authenticator d&apos;un administrateur
              </Button>
            </div>
          </div>
        </div>
      </Card>

      <Card titre="Statut de l'établissement">
        {suspensionDisponible ? (
          <div className="flex flex-col gap-3">
            <p className="m-0 text-[14px] text-texte-2">
              Passer en lecture seule ou suspendre ferme les sessions ouvertes de l&apos;établissement. Un motif est obligatoire et journalisé.
            </p>
            <div>
              <Button variante="secondaire" onClick={() => setAction("statut")}>
                Changer le statut
              </Button>
            </div>
          </div>
        ) : (
          <p className="m-0 text-[14px] text-texte-attenue">
            {archive ? "Établissement archivé." : "La suspension manuelle n'est pas activée sur la plateforme (décision P6 à confirmer avec FYXOP)."}
          </p>
        )}
      </Card>

      {action === "modifier" && <ModaleModification e={e} onFermer={ferme} />}
      {action === "inviter" && <ModaleInvitation e={e} onFermer={ferme} />}
      {action === "reinitialiser" && <ModaleReinitialisation e={e} onFermer={ferme} />}
      {action === "statut" && (
        <ModaleStatut
          e={e}
          onFermer={ferme}
          onSuspensionCoupee={() => {
            setSuspensionCoupee(true);
            ferme();
          }}
        />
      )}
    </div>
  );
}

function Ligne({ libelle, valeur }: { libelle: string; valeur: ReactNode }) {
  return (
    <>
      <dt className="text-texte-attenue">{libelle}</dt>
      <dd className="m-0 min-w-0 break-words font-medium text-encre">{valeur}</dd>
    </>
  );
}

// ---------------------------------------------------------------------------
// Modales avec confirmation par code TOTP
// ---------------------------------------------------------------------------

function ModaleModification({ e, onFermer }: { e: EtablissementDetail; onFermer: () => void }) {
  const { modifier } = useActionsEtablissement(e.id);
  const { toast } = useToast();
  const [raison, setRaison] = useState(e.raison_sociale);
  const valide = raison.trim() !== "" && raison.trim() !== e.raison_sociale;
  return (
    <ModaleCode
      titre="Modifier l'établissement"
      description="Seule la raison sociale est modifiable ; le code est définitif."
      libelleAction="Enregistrer"
      peutConfirmer={valide}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        await modifier.mutateAsync({ raison_sociale: raison.trim(), code });
        toast({ ton: "succes", titre: "Raison sociale enregistrée" });
        onFermer();
      }}
    >
      <Input label="Raison sociale" required maxLength={200} value={raison} onChange={(ev) => setRaison(ev.target.value)} />
    </ModaleCode>
  );
}

function ModaleInvitation({ e, onFermer }: { e: EtablissementDetail; onFermer: () => void }) {
  const { inviter } = useActionsEtablissement(e.id);
  const { toast } = useToast();
  const [v, setV] = useState({ prenom: "", nom: "", email: "" });
  const [erreurEmail, setErreurEmail] = useState<string | undefined>();
  const maj = (cle: keyof typeof v) => (ev: ChangeEvent<HTMLInputElement>) => {
    setV((p) => ({ ...p, [cle]: ev.target.value }));
    if (cle === "email") setErreurEmail(undefined);
  };
  const valide = v.prenom.trim() !== "" && v.nom.trim() !== "" && EMAIL.test(v.email.trim());
  return (
    <ModaleCode
      titre="Inviter un administrateur"
      description={`Un e-mail d'activation est envoyé à la personne, avec le rôle « Administrateur ALPHA » sur ${e.raison_sociale}.`}
      libelleAction="Inviter"
      peutConfirmer={valide}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        try {
          await inviter.mutateAsync({ prenom: v.prenom.trim(), nom: v.nom.trim(), email: v.email.trim(), code });
        } catch (err) {
          if (estApiError(err) && err.code === "EMAIL_EXISTE") {
            setErreurEmail("Cette adresse e-mail est déjà utilisée sur la plateforme.");
            return;
          }
          throw err;
        }
        toast({ ton: "succes", titre: "Invitation envoyée", message: v.email.trim() });
        onFermer();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Prénom" required autoComplete="off" value={v.prenom} onChange={maj("prenom")} />
        <Input label="Nom" required autoComplete="off" value={v.nom} onChange={maj("nom")} />
      </div>
      <Input label="Adresse e-mail professionnelle" type="email" required autoComplete="off" value={v.email} onChange={maj("email")} erreur={erreurEmail} />
    </ModaleCode>
  );
}

function ModaleReinitialisation({ e, onFermer }: { e: EtablissementDetail; onFermer: () => void }) {
  const { reinitialiser } = useActionsEtablissement(e.id);
  const { toast } = useToast();
  const [v, setV] = useState({ email: "", reference: "", commentaire: "" });
  const maj = (cle: keyof typeof v) => (ev: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setV((p) => ({ ...p, [cle]: ev.target.value }));
  const valide = EMAIL.test(v.email.trim()) && v.reference.trim() !== "";
  return (
    <ModaleCode
      titre="Réinitialiser l'Authenticator"
      description={`${e.raison_sociale} · une demande écrite signée de la direction et un appel vidéo avec pièce d'identité sont requis (P4).`}
      libelleAction="Réinitialiser"
      variante="primaire"
      peutConfirmer={valide}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        await reinitialiser.mutateAsync({ email: v.email.trim(), reference_demande: v.reference.trim(), commentaire: v.commentaire.trim(), code });
        toast({ ton: "succes", titre: "Authenticator réinitialisé", message: "Un lien de réenrôlement est envoyé à l'administrateur ; les autres administrateurs sont prévenus." });
        onFermer();
      }}
    >
      <Input
        label="Adresse e-mail de l'administrateur"
        type="email"
        required
        autoComplete="off"
        aide="Telle qu'indiquée sur la demande écrite signée."
        value={v.email}
        onChange={maj("email")}
      />
      <Input label="Référence de la demande" required maxLength={120} autoComplete="off" aide="Numéro ou référence du courrier signé par la direction." value={v.reference} onChange={maj("reference")} />
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-texte-2">Commentaire</span>
        <textarea
          rows={2}
          maxLength={1000}
          placeholder="Ex. Appel vidéo avec CNI le 19/10/2026"
          value={v.commentaire}
          onChange={maj("commentaire")}
          className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] placeholder:text-texte-attenue focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
        />
      </label>
    </ModaleCode>
  );
}

const STATUTS_MANUELS: ReadonlyArray<{ valeur: StatutEtablissement; libelle: string }> = [
  { valeur: "ACTIF", libelle: "Actif" },
  { valeur: "LECTURE_SEULE", libelle: "Lecture seule" },
  { valeur: "SUSPENDU", libelle: "Suspendu" },
];

function ModaleStatut({ e, onFermer, onSuspensionCoupee }: { e: EtablissementDetail; onFermer: () => void; onSuspensionCoupee: () => void }) {
  const { modifier } = useActionsEtablissement(e.id);
  const { toast } = useToast();
  const [statut, setStatut] = useState<StatutEtablissement>(e.statut === "ACTIF" ? "LECTURE_SEULE" : "ACTIF");
  const [motif, setMotif] = useState("");
  return (
    <ModaleCode
      titre="Changer le statut"
      description="Les sessions ouvertes de l'établissement sont fermées lors d'une suspension."
      libelleAction="Appliquer"
      peutConfirmer={statut !== e.statut && motif.trim() !== ""}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        try {
          await modifier.mutateAsync({ statut, motif: motif.trim(), code });
        } catch (err) {
          if (estApiError(err) && err.code === SUSPENSION_DESACTIVEE) {
            toast({ ton: "info", titre: "Suspension manuelle indisponible", message: "Elle n'est pas activée sur la plateforme." });
            onSuspensionCoupee();
            return;
          }
          throw err;
        }
        toast({ ton: "succes", titre: "Statut modifié" });
        onFermer();
      }}
    >
      <Select label="Nouveau statut" options={STATUTS_MANUELS.map((s) => ({ valeur: s.valeur, libelle: s.libelle }))} value={statut} onChange={(ev) => setStatut(ev.target.value as StatutEtablissement)} />
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-texte-2">
          Motif <span className="text-danger-texte" aria-hidden="true">*</span>
        </span>
        <textarea
          rows={2}
          maxLength={500}
          required
          value={motif}
          onChange={(ev) => setMotif(ev.target.value)}
          className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
        />
      </label>
    </ModaleCode>
  );
}

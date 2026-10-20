"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { AccesRefuse, AlerteErreur, AlerteInfo, Chargement, EnTetePage, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Input, Modal, Select, Table, Td, Th, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { aplatirUnites, useActionsUtilisateur, useRoles, useUnites, useUtilisateur, useUtilisateurs, type Affectation, type UtilisateurDetail } from "@/lib/api/hooks/admin";
import { formatDate, formatDateHeureCourte } from "@/lib/format";
import { messageErreur } from "@/lib/compte/messages";
import { possede } from "@/lib/permissions";
import { z } from "@/lib/zod";
import { BadgeAuthenticator, BadgeStatutUtilisateur } from "./statuts";

type Fenetre = null | "suspendre" | { retirer: Affectation };

/** `/administration/utilisateurs/[id]` : fiche, affectations, état du compte, sessions, signalement. */
export function FicheUtilisateur({ id }: { id: string }) {
  const moi = useMoi();
  const fiche = useUtilisateur(id);
  const [fenetre, setFenetre] = useState<Fenetre>(null);

  if (!possede(moi, "admin.utilisateurs")) return <AccesRefuse />;
  if (fiche.isPending) return <Chargement texte="Chargement de la fiche…" />;
  if (fiche.isError) {
    if (estApiError(fiche.error) && fiche.error.status === 404) {
      return (
        <Card titre="Utilisateur introuvable">
          <p className="m-0 text-[15px] text-texte-2" role="alert">Cet utilisateur n&rsquo;existe pas dans votre établissement.</p>
          <div className="mt-3"><Link href="/administration/utilisateurs">← Retour aux utilisateurs</Link></div>
        </Card>
      );
    }
    return <ErreurChargement erreur={fiche.error} titre="Fiche indisponible" onReessayer={() => void fiche.refetch()} />;
  }
  const u = fiche.data;

  return (
    <div className="flex flex-col gap-5">
      <EnTetePage
        titre={`${u.prenom} ${u.nom}`}
        sousTitre={
          <>
            <Link href="/administration/utilisateurs">← Retour aux utilisateurs</Link> · {u.email}
          </>
        }
        actions={<BadgeStatutUtilisateur u={u} />}
      />
      {u.signalement && u.signalement.statut === "OUVERT" && (
        <AlerteInfo>
          Signalement « téléphone perdu » ouvert depuis le {formatDate(u.signalement.signale_le)}. <Link href="/administration/securite">Le traiter dans Sécurité</Link>
        </AlerteInfo>
      )}
      <div className="grid gap-5 xl:grid-cols-2">
        <Identite u={u} />
        <EtatCompte u={u} onSuspendre={() => setFenetre("suspendre")} />
      </div>
      <Affectations u={u} onRetirer={(a) => setFenetre({ retirer: a })} />
      <SessionsActives u={u} />

      {fenetre === "suspendre" && <ModaleSuspension id={id} nom={`${u.prenom} ${u.nom}`} onFermer={() => setFenetre(null)} />}
      {fenetre && fenetre !== "suspendre" && <ModaleRetrait id={id} affectation={fenetre.retirer} onFermer={() => setFenetre(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------------------

const schemaIdentite = z.object({
  prenom: z.string().trim().min(1, "Saisissez le prénom."),
  nom: z.string().trim().min(1, "Saisissez le nom."),
  telephone_mobile: z.string().trim().refine((v) => v === "" || /^\+[1-9][0-9]{6,14}$/.test(v), "Format international attendu (ex. +221770000000)."),
  responsable_id: z.string(),
});
type ValeursIdentite = z.infer<typeof schemaIdentite>;

function Identite({ u }: { u: UtilisateurDetail }) {
  const { modifier } = useActionsUtilisateur(u.id);
  const autres = useUtilisateurs({ q: "", roleId: "" }, 100);
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  const valeursInitiales: ValeursIdentite = { prenom: u.prenom, nom: u.nom, telephone_mobile: u.telephone_mobile ?? "", responsable_id: u.responsable?.id ?? "" };
  const form = useForm<ValeursIdentite>({ resolver: zodResolver(schemaIdentite), defaultValues: valeursInitiales });
  const { errors, isDirty } = form.formState;
  const candidats = useMemo(() => (autres.data?.pages.flatMap((p) => p.results) ?? []).filter((c) => c.id !== u.id && c.statut !== "DESACTIVE"), [autres.data, u.id]);

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      const maj = await modifier.mutateAsync({ prenom: v.prenom, nom: v.nom, telephone_mobile: v.telephone_mobile || null, responsable_id: v.responsable_id || null });
      form.reset({ prenom: maj.prenom, nom: maj.nom, telephone_mobile: maj.telephone_mobile ?? "", responsable_id: maj.responsable?.id ?? "" });
      toast({ ton: "succes", titre: "Fiche enregistrée" });
    } catch (e) {
      setErreur(appliquerErreursApi(e, form.setError, ["prenom", "nom", "telephone_mobile", "responsable_id"]));
    }
  });

  return (
    <Card titre="Identité">
      <form noValidate onSubmit={soumettre} className="flex flex-col gap-4">
        <AlerteErreur>{erreur}</AlerteErreur>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Prénom" erreur={errors.prenom?.message} {...form.register("prenom")} />
          <Input label="Nom" erreur={errors.nom?.message} {...form.register("nom")} />
        </div>
        <Input label="E-mail professionnel" value={u.email} readOnly aide="L'adresse e-mail n'est pas modifiable." />
        <Input label="Téléphone mobile" type="tel" placeholder="+221770000000" erreur={errors.telephone_mobile?.message} {...form.register("telephone_mobile")} />
        <Select
          label="Responsable hiérarchique"
          placeholder="Aucun"
          options={candidats.map((c) => ({ valeur: c.id, libelle: `${c.prenom} ${c.nom}` }))}
          erreur={errors.responsable_id?.message}
          {...form.register("responsable_id")}
        />
        <div>
          <Button type="submit" chargement={modifier.isPending} disabled={!isDirty}>Enregistrer</Button>
        </div>
      </form>
    </Card>
  );
}

function EtatCompte({ u, onSuspendre }: { u: UtilisateurDetail; onSuspendre: () => void }) {
  const actions = useActionsUtilisateur(u.id);
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);

  const lancer = async (action: () => Promise<unknown>, succes: string) => {
    setErreur(null);
    try {
      await action();
      toast({ ton: "succes", titre: succes });
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };

  return (
    <Card titre="État du compte">
      <div className="flex flex-col gap-4">
        <AlerteErreur>{erreur}</AlerteErreur>
        <dl className="m-0 grid gap-x-6 gap-y-3 text-[14px] sm:grid-cols-2">
          <Terme t="Statut"><BadgeStatutUtilisateur u={u} /></Terme>
          <Terme t="Authenticator"><BadgeAuthenticator etat={u.authenticator} />{u.mfa_a_reconfigurer && <span className="ml-2 text-[13px] text-texte-attenue">à reconfigurer</span>}</Terme>
          <Terme t="Dernière connexion"><span className="font-mono">{formatDateHeureCourte(u.derniere_connexion)}</span></Terme>
          <Terme t="Compte activé le"><span className="font-mono">{formatDate(u.active_le)}</span></Terme>
          <Terme t="Créé le"><span className="font-mono">{formatDate(u.cree_le)}</span></Terme>
          <Terme t="Échecs de connexion"><span className="font-mono">{u.echecs_connexion}</span></Terme>
          <Terme t="Signature">{u.signature_bloquee ? <Badge ton="rouge">Bloquée</Badge> : <Badge ton="vert">Autorisée</Badge>}</Terme>
          {u.verrouille && (
            <Terme t="Verrouillage">{u.bloque_par_admin ? "Bloqué : déblocage par un administrateur" : `Jusqu'à ${formatDateHeureCourte(u.verrouille_jusqua)}`}</Terme>
          )}
        </dl>
        <div className="flex flex-wrap gap-2">
          {u.statut === "ACTIF" && <Button variante="secondaire" onClick={onSuspendre}>Suspendre</Button>}
          {u.statut === "SUSPENDU" && (
            <Button variante="secondaire" chargement={actions.reactiver.isPending} onClick={() => void lancer(() => actions.reactiver.mutateAsync(), "Compte réactivé")}>
              Réactiver
            </Button>
          )}
          {u.verrouille && (
            <Button variante="secondaire" chargement={actions.deverrouiller.isPending} onClick={() => void lancer(() => actions.deverrouiller.mutateAsync(), "Compte déverrouillé")}>
              Déverrouiller
            </Button>
          )}
          {u.statut === "INVITE" && (
            <Button variante="secondaire" chargement={actions.renvoyerInvitation.isPending} onClick={() => void lancer(() => actions.renvoyerInvitation.mutateAsync(), "Invitation renvoyée")}>
              Renvoyer l&rsquo;invitation
            </Button>
          )}
          {u.sessions_actives.length > 0 && (
            <Button
              variante="secondaire"
              chargement={actions.revoquerSessions.isPending}
              onClick={() => void lancer(async () => { await actions.revoquerSessions.mutateAsync(); }, "Sessions révoquées")}
            >
              Révoquer les sessions
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}

function Terme({ t, children }: { t: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] font-semibold uppercase tracking-[.04em] text-texte-attenue">{t}</dt>
      <dd className="m-0 mt-0.5 text-[14px]">{children}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Affectations({ u, onRetirer }: { u: UtilisateurDetail; onRetirer: (a: Affectation) => void }) {
  const { affecter } = useActionsUtilisateur(u.id);
  const roles = useRoles();
  const unites = useUnites();
  const { toast } = useToast();
  const [roleId, setRoleId] = useState("");
  const [uniteId, setUniteId] = useState("");
  const [principal, setPrincipal] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  const attribuer = async () => {
    setErreur(null);
    try {
      await affecter.mutateAsync({ role_id: roleId, unite_id: uniteId || null, principal });
      toast({ ton: "succes", titre: "Rôle attribué" });
      setRoleId("");
      setUniteId("");
      setPrincipal(false);
    } catch (e) {
      setErreur(estApiError(e) && e.code === "AFFECTATION_EXISTE" ? "Cet utilisateur a déjà ce rôle sur ce périmètre." : messageErreur(e));
    }
  };

  return (
    <Card titre="Rôles et périmètres" marge={false}>
      <Table legende="Affectations en cours">
        <thead>
          <tr>
            <Th>Rôle</Th>
            <Th>Périmètre</Th>
            <Th>Depuis le</Th>
            <Th><span className="sr-only">Action</span></Th>
          </tr>
        </thead>
        <tbody>
          {u.affectations.length === 0 && (
            <tr><Td colSpan={4} className="text-texte-attenue">Aucun rôle attribué.</Td></tr>
          )}
          {u.affectations.map((a) => (
            <tr key={a.id}>
              <Td>{a.role.libelle} {a.principal && <Badge ton="bleu">Principal</Badge>}</Td>
              <Td>{a.unite?.libelle ?? "Tout l'établissement"}</Td>
              <Td mono>{formatDate(a.debut)}</Td>
              <Td className="text-right">
                <Button variante="secondaire" onClick={() => onRetirer(a)} aria-label={`Retirer le rôle ${a.role.libelle}`}>Retirer</Button>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="flex flex-col gap-3 border-t border-ligne px-4.5 py-4">
        <h3 className="m-0 text-[14px] font-semibold">Attribuer un rôle</h3>
        <AlerteErreur>{erreur}</AlerteErreur>
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Rôle"
            placeholder="Choisir un rôle…"
            value={roleId}
            onChange={(e) => setRoleId(e.currentTarget.value)}
            options={(roles.data ?? []).filter((r) => r.actif).map((r) => ({ valeur: r.id, libelle: r.libelle }))}
            classeConteneur="min-w-[180px] flex-1 basis-[200px]"
          />
          <Select
            label="Périmètre"
            placeholder="Tout l'établissement"
            value={uniteId}
            onChange={(e) => setUniteId(e.currentTarget.value)}
            options={aplatirUnites(unites.data ?? []).filter((x) => x.actif).map((x) => ({ valeur: x.id, libelle: `${"— ".repeat(x.profondeur)}${x.libelle}` }))}
            classeConteneur="min-w-[180px] flex-1 basis-[200px]"
          />
          <label className="flex min-h-champ cursor-pointer items-center gap-2 text-[14px] font-semibold text-texte-2">
            <input type="checkbox" checked={principal} onChange={(e) => setPrincipal(e.currentTarget.checked)} className="h-[18px] w-[18px] accent-[var(--marque)]" />
            Rôle principal
          </label>
          <Button variante="secondaire" chargement={affecter.isPending} disabled={!roleId} onClick={attribuer}>Attribuer</Button>
        </div>
      </div>
    </Card>
  );
}

function SessionsActives({ u }: { u: UtilisateurDetail }) {
  return (
    <Card titre="Sessions actives" marge={false}>
      {u.sessions_actives.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucune session active.</p>
      ) : (
        <Table legende="Sessions actives de l'utilisateur">
          <thead>
            <tr><Th>Appareil</Th><Th>Adresse IP</Th><Th>Ouverte le</Th><Th>Dernière activité</Th></tr>
          </thead>
          <tbody>
            {u.sessions_actives.map((s) => (
              <tr key={s.id}>
                <Td>{s.appareil}</Td>
                <Td mono>{s.ip ?? "—"}</Td>
                <Td mono>{formatDateHeureCourte(s.cree_le)}</Td>
                <Td mono>{formatDateHeureCourte(s.derniere_activite)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------

function ModaleSuspension({ id, nom, onFermer }: { id: string; nom: string; onFermer: () => void }) {
  const { suspendre } = useActionsUtilisateur(id);
  const { toast } = useToast();
  const [motif, setMotif] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const envoyer = async () => {
    setErreur(null);
    try {
      const r = await suspendre.mutateAsync(motif.trim());
      toast({ ton: "succes", titre: "Compte suspendu", message: `${r.sessions_revoquees} session${r.sessions_revoquees > 1 ? "s" : ""} révoquée${r.sessions_revoquees > 1 ? "s" : ""}.` });
      onFermer();
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };
  return (
    <Modal
      ouvert
      onFermer={onFermer}
      titre={`Suspendre ${nom} ?`}
      description="Le compte ne pourra plus se connecter et ses sessions seront fermées. Vous pourrez le réactiver."
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer}>Annuler</Button>
          <Button chargement={suspendre.isPending} disabled={motif.trim() === ""} onClick={envoyer}>Suspendre le compte</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <AlerteErreur>{erreur}</AlerteErreur>
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-texte-2">Motif de la suspension <span className="text-danger-texte" aria-hidden="true">*</span></span>
          <textarea
            rows={3}
            maxLength={500}
            required
            value={motif}
            onChange={(e) => setMotif(e.currentTarget.value)}
            className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
          />
        </label>
      </div>
    </Modal>
  );
}

function ModaleRetrait({ id, affectation, onFermer }: { id: string; affectation: Affectation; onFermer: () => void }) {
  const { terminerAffectation } = useActionsUtilisateur(id);
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  const envoyer = async () => {
    setErreur(null);
    try {
      await terminerAffectation.mutateAsync(affectation.id);
      toast({ ton: "succes", titre: "Rôle retiré" });
      onFermer();
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };
  return (
    <Modal
      ouvert
      onFermer={onFermer}
      titre={`Retirer le rôle « ${affectation.role.libelle} » ?`}
      description={affectation.unite ? `Périmètre : ${affectation.unite.libelle}` : "Périmètre : tout l'établissement"}
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer}>Annuler</Button>
          <Button chargement={terminerAffectation.isPending} onClick={envoyer}>Retirer le rôle</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[14px] text-texte-2">
        <AlerteErreur>{erreur}</AlerteErreur>
        <p className="m-0">L&rsquo;affectation prend fin aujourd&rsquo;hui ; l&rsquo;historique est conservé.</p>
      </div>
    </Modal>
  );
}

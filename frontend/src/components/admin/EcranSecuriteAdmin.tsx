"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { AccesRefuse, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Input, ModaleCode, Select, Table, Td, Th, useToast } from "@/components/ui";
import {
  useModifierParametresSecurite,
  useParametresSecurite,
  useSignalements,
  useTraiterSignalement,
  type ModeVerification,
  type ParametresSecurite,
  type SignalementTelephone,
} from "@/lib/api/hooks/admin";
import { formatDateHeureCourte } from "@/lib/format";
import { possede } from "@/lib/permissions";
import { z } from "@/lib/zod";

/** `/administration/securite` : paramètres de sécurité (avec code TOTP) et signalements « téléphone perdu ». */
export function EcranSecuriteAdmin() {
  const moi = useMoi();
  const parametres = possede(moi, "admin.securite");
  const signalements = possede(moi, "admin.utilisateurs");
  if (!parametres && !signalements) return <AccesRefuse />;
  return (
    <div className="flex flex-col gap-5">
      {parametres && <ParametresSecuriteForm />}
      {signalements && <Signalements />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Paramètres de sécurité
// ---------------------------------------------------------------------------

/** Bornes de `alpha/tenancy/parametres.py` (le serveur reste seul juge). */
const BORNES = {
  inactivite_session_min: [5, 60],
  duree_max_session_h: [1, 24],
  mdp_longueur_min: [12, 64],
  mdp_historique: [5, 24],
  mdp_expiration_jours: [30, 365],
  tentatives_max: [3, 10],
  verrouillage_min: [5, 1440],
  verrouillages_max_24h: [1, 10],
  validite_invitation_h: [1, 168],
  validite_reinit_mdp_min: [10, 120],
  retention_audit_annees: [10, 50],
} as const;
type ChampNumerique = keyof typeof BORNES;

const FORMAT = (c: ChampNumerique) => `${BORNES[c][0]} à ${BORNES[c][1]}`;
const entier = (c: ChampNumerique) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, "Saisissez un nombre entier.")
    .refine((v) => Number(v) >= BORNES[c][0] && Number(v) <= BORNES[c][1], `Valeur attendue : ${FORMAT(c)}.`);

const schema = z
  .object({
    inactivite_session_min: entier("inactivite_session_min"),
    duree_max_session_h: entier("duree_max_session_h"),
    mdp_longueur_min: entier("mdp_longueur_min"),
    mdp_historique: entier("mdp_historique"),
    expiration: z.boolean(),
    mdp_expiration_jours: z.string().trim(),
    tentatives_max: entier("tentatives_max"),
    verrouillage_min: entier("verrouillage_min"),
    verrouillages_max_24h: entier("verrouillages_max_24h"),
    validite_invitation_h: entier("validite_invitation_h"),
    validite_reinit_mdp_min: entier("validite_reinit_mdp_min"),
    retention_audit_annees: entier("retention_audit_annees"),
    email_controle_interne: z.string().trim().refine((v) => v === "" || z.string().email().safeParse(v).success, "Adresse e-mail invalide."),
  })
  .superRefine((v, ctx) => {
    if (v.expiration && !entier("mdp_expiration_jours").safeParse(v.mdp_expiration_jours).success) {
      ctx.addIssue({ code: "custom", path: ["mdp_expiration_jours"], message: `Valeur attendue : ${FORMAT("mdp_expiration_jours")}.` });
    }
  });
type Valeurs = z.infer<typeof schema>;

function valeursDe(p: ParametresSecurite): Valeurs {
  return {
    inactivite_session_min: String(p.inactivite_session_min),
    duree_max_session_h: String(p.duree_max_session_h),
    mdp_longueur_min: String(p.mdp_longueur_min),
    mdp_historique: String(p.mdp_historique),
    expiration: p.mdp_expiration_jours !== null,
    mdp_expiration_jours: p.mdp_expiration_jours !== null ? String(p.mdp_expiration_jours) : "90",
    tentatives_max: String(p.tentatives_max),
    verrouillage_min: String(p.verrouillage_min),
    verrouillages_max_24h: String(p.verrouillages_max_24h),
    validite_invitation_h: String(p.validite_invitation_h),
    validite_reinit_mdp_min: String(p.validite_reinit_mdp_min),
    retention_audit_annees: String(p.retention_audit_annees),
    email_controle_interne: p.email_controle_interne,
  };
}

const CHAMPS: Array<{ groupe: string; champs: Array<{ nom: ChampNumerique; libelle: string; unite: string }> }> = [
  {
    groupe: "Sessions",
    champs: [
      { nom: "inactivite_session_min", libelle: "Inactivité avant déconnexion", unite: "minutes" },
      { nom: "duree_max_session_h", libelle: "Durée maximale d'une session", unite: "heures" },
    ],
  },
  {
    groupe: "Mot de passe",
    champs: [
      { nom: "mdp_longueur_min", libelle: "Longueur minimale", unite: "caractères" },
      { nom: "mdp_historique", libelle: "Anciens mots de passe interdits", unite: "derniers" },
    ],
  },
  {
    groupe: "Verrouillage",
    champs: [
      { nom: "tentatives_max", libelle: "Essais avant verrouillage", unite: "essais" },
      { nom: "verrouillage_min", libelle: "Durée du verrouillage", unite: "minutes" },
      { nom: "verrouillages_max_24h", libelle: "Verrouillages avant déblocage par un administrateur", unite: "en 24 h" },
    ],
  },
  {
    groupe: "Liens et conservation",
    champs: [
      { nom: "validite_invitation_h", libelle: "Validité d'une invitation", unite: "heures" },
      { nom: "validite_reinit_mdp_min", libelle: "Validité d'un lien de réinitialisation", unite: "minutes" },
      { nom: "retention_audit_annees", libelle: "Conservation du journal d'audit", unite: "années" },
    ],
  },
];

function ParametresSecuriteForm() {
  const parametres = useParametresSecurite();
  const modifier = useModifierParametresSecurite();
  const { toast } = useToast();
  const [aConfirmer, setAConfirmer] = useState<Partial<ParametresSecurite> | null>(null);
  const form = useForm<Valeurs>({ resolver: zodResolver(schema), values: parametres.data ? valeursDe(parametres.data) : undefined });
  const { errors, isDirty } = form.formState;
  const expiration = form.watch("expiration");

  if (parametres.isPending) return <Chargement texte="Chargement des paramètres de sécurité…" />;
  if (parametres.isError) return <ErreurChargement erreur={parametres.error} titre="Paramètres indisponibles" onReessayer={() => void parametres.refetch()} />;
  const actuels = parametres.data;

  const preparer = form.handleSubmit((v) => {
    const cible: Partial<ParametresSecurite> = {
      inactivite_session_min: Number(v.inactivite_session_min),
      duree_max_session_h: Number(v.duree_max_session_h),
      mdp_longueur_min: Number(v.mdp_longueur_min),
      mdp_historique: Number(v.mdp_historique),
      mdp_expiration_jours: v.expiration ? Number(v.mdp_expiration_jours) : null,
      tentatives_max: Number(v.tentatives_max),
      verrouillage_min: Number(v.verrouillage_min),
      verrouillages_max_24h: Number(v.verrouillages_max_24h),
      validite_invitation_h: Number(v.validite_invitation_h),
      validite_reinit_mdp_min: Number(v.validite_reinit_mdp_min),
      retention_audit_annees: Number(v.retention_audit_annees),
      email_controle_interne: v.email_controle_interne,
    };
    // Seuls les réglages modifiés sont envoyés (le journal ne garde que ceux-là).
    const modifies = Object.fromEntries(Object.entries(cible).filter(([k, val]) => actuels[k as keyof ParametresSecurite] !== val)) as Partial<ParametresSecurite>;
    if (Object.keys(modifies).length === 0) {
      toast({ ton: "info", titre: "Aucun changement à enregistrer" });
      return;
    }
    setAConfirmer(modifies);
  });

  return (
    <Card titre="Paramètres de sécurité" description="Réglages de l'établissement. Toute modification est confirmée par un code Authenticator et journalisée.">
      <form noValidate onSubmit={preparer} className="flex flex-col gap-6">
        {CHAMPS.map((g) => (
          <fieldset key={g.groupe} className="m-0 flex min-w-0 flex-col gap-3 border-0 p-0">
            <legend className="mb-1 p-0 text-[14px] font-semibold text-encre">{g.groupe}</legend>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {g.champs.map((c) => (
                <Input
                  key={c.nom}
                  label={`${c.libelle} (${c.unite})`}
                  inputMode="numeric"
                  aide={`${FORMAT(c.nom)}`}
                  erreur={errors[c.nom]?.message}
                  {...form.register(c.nom)}
                />
              ))}
              {g.groupe === "Mot de passe" && (
                <div className="flex flex-col gap-1.5">
                  <label className="flex min-h-champ cursor-pointer items-center gap-2 text-[13px] font-semibold text-texte-2">
                    <input type="checkbox" className="h-[18px] w-[18px] accent-[var(--marque)]" {...form.register("expiration")} />
                    Expiration périodique du mot de passe
                  </label>
                  {expiration && (
                    <Input label="Expiration après (jours)" inputMode="numeric" aide={FORMAT("mdp_expiration_jours")} erreur={errors.mdp_expiration_jours?.message} {...form.register("mdp_expiration_jours")} />
                  )}
                </div>
              )}
            </div>
          </fieldset>
        ))}
        <Input
          label="Adresse du contrôle interne (ancrage quotidien du journal)"
          type="email"
          classeConteneur="max-w-[480px]"
          erreur={errors.email_controle_interne?.message}
          {...form.register("email_controle_interne")}
        />
        <div>
          <Button type="submit" disabled={!isDirty}>Enregistrer les paramètres</Button>
        </div>
      </form>

      {aConfirmer && (
        <ModaleCode
          titre="Confirmer la modification"
          description={`${Object.keys(aConfirmer).length} réglage${Object.keys(aConfirmer).length > 1 ? "s" : ""} de sécurité à modifier. Saisissez un code de votre application Authenticator.`}
          libelleAction="Confirmer et enregistrer"
          onFermer={() => setAConfirmer(null)}
          onConfirmer={async (code) => {
            const p = await modifier.mutateAsync({ ...aConfirmer, code });
            form.reset(valeursDe(p));
            setAConfirmer(null);
            toast({ ton: "succes", titre: "Paramètres de sécurité enregistrés" });
          }}
        />
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Signalements « téléphone perdu »
// ---------------------------------------------------------------------------

const MODES: ReadonlyArray<{ valeur: ModeVerification; libelle: string }> = [
  { valeur: "PRESENTIEL_PIECE", libelle: "En présentiel, avec pièce d'identité" },
  { valeur: "RAPPEL_TELEPHONIQUE", libelle: "Rappel au numéro connu" },
  { valeur: "VISIO", libelle: "Appel vidéo" },
  { valeur: "AUTRE", libelle: "Autre" },
];

const STATUTS: Record<string, { libelle: string; ton: "ambre" | "vert" | "gris" }> = {
  OUVERT: { libelle: "Ouvert", ton: "ambre" },
  REINITIALISE: { libelle: "Réinitialisé", ton: "vert" },
  ANNULE: { libelle: "Annulé (retrouvé)", ton: "gris" },
};

const CANAUX: Record<string, string> = { PAGE_PUBLIQUE: "Page publique", MON_COMPTE: "Mon compte", ADMIN: "Administration" };

function Signalements() {
  const liste = useSignalements();
  const [cible, setCible] = useState<{ s: SignalementTelephone; action: "reinitialiser" | "annuler" } | null>(null);
  const lignes = liste.data?.results ?? [];
  const ouverts = lignes.filter((s) => s.statut === "OUVERT").length;

  return (
    <Card
      titre={`Signalements « téléphone perdu »${liste.data ? ` · ${ouverts} ouvert${ouverts > 1 ? "s" : ""}` : ""}`}
      description="Vérifiez l'identité de la personne hors ligne avant de réinitialiser son application Authenticator."
      marge={false}
    >
      {liste.isPending ? (
        <div className="px-4.5 pb-4"><Chargement /></div>
      ) : liste.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={liste.error} titre="Signalements indisponibles" onReessayer={() => void liste.refetch()} /></div>
      ) : lignes.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucun signalement.</p>
      ) : (
        <Table legende="Signalements téléphone perdu">
          <thead>
            <tr>
              <Th>Utilisateur</Th>
              <Th>Signalé le</Th>
              <Th>Canal</Th>
              <Th>Statut</Th>
              <Th>Traité par</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((s) => {
              const st = STATUTS[s.statut] ?? { libelle: s.statut, ton: "gris" as const };
              return (
                <tr key={s.id}>
                  <Td>
                    <span className="font-semibold">{s.utilisateur.nom}</span>
                    <span className="block text-[13px] text-texte-attenue">{s.utilisateur.email}</span>
                  </Td>
                  <Td mono>{formatDateHeureCourte(s.signale_le)}</Td>
                  <Td>{CANAUX[s.canal] ?? s.canal}</Td>
                  <Td><Badge ton={st.ton}>{st.libelle}</Badge></Td>
                  <Td>{s.traite_par?.nom ?? "—"}</Td>
                  <Td className="text-right">
                    {s.statut === "OUVERT" && (
                      <div className="flex justify-end gap-2">
                        <Button onClick={() => setCible({ s, action: "reinitialiser" })} aria-label={`Réinitialiser l'accès de ${s.utilisateur.nom}`}>Réinitialiser</Button>
                        <Button variante="secondaire" onClick={() => setCible({ s, action: "annuler" })} aria-label={`Annuler le signalement de ${s.utilisateur.nom}`}>Annuler</Button>
                      </div>
                    )}
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
      {cible && <ModaleTraitement s={cible.s} action={cible.action} onFermer={() => setCible(null)} />}
    </Card>
  );
}

function ModaleTraitement({ s, action, onFermer }: { s: SignalementTelephone; action: "reinitialiser" | "annuler"; onFermer: () => void }) {
  const traiter = useTraiterSignalement();
  const { toast } = useToast();
  const [mode, setMode] = useState<ModeVerification | "">("");
  const [commentaire, setCommentaire] = useState("");
  const reinit = action === "reinitialiser";

  return (
    <ModaleCode
      titre={reinit ? `Réinitialiser l'accès de ${s.utilisateur.nom}` : `Annuler le signalement de ${s.utilisateur.nom}`}
      description={
        reinit
          ? "L'application Authenticator et les codes de secours sont révoqués, les sessions fermées, et un lien de réenrôlement (24 h) est envoyé par e-mail. La signature reste bloquée jusqu'au réenrôlement."
          : "Le téléphone est retrouvé : l'application Authenticator est réactivée et la signature débloquée."
      }
      libelleAction={reinit ? "Réinitialiser l'accès" : "Annuler le signalement"}
      peutConfirmer={!reinit || mode !== ""}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        await traiter.mutateAsync({ id: s.id, action, code, commentaire: commentaire.trim(), ...(reinit ? { mode_verification: mode as ModeVerification } : {}) });
        toast({ ton: "succes", titre: reinit ? "Accès réinitialisé" : "Signalement annulé", message: s.utilisateur.nom });
        onFermer();
      }}
    >
      {reinit && (
        <Select
          label="Vérification d'identité effectuée"
          required
          placeholder="Choisir le mode de vérification…"
          value={mode}
          onChange={(e) => setMode(e.currentTarget.value as ModeVerification | "")}
          options={MODES.map((m) => ({ valeur: m.valeur, libelle: m.libelle }))}
        />
      )}
      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-semibold text-texte-2">Commentaire</span>
        <textarea
          rows={3}
          maxLength={2000}
          value={commentaire}
          onChange={(e) => setCommentaire(e.currentTarget.value)}
          className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
        />
      </label>
    </ModaleCode>
  );
}

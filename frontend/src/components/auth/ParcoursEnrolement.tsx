"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Button, Input, OtpInput, Stepper, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import {
  useConfirmerAuthenticator,
  useEtapeMotDePasse,
  useGenererAuthenticator,
  useInvitation,
  useTerminerEnrolement,
  type Authenticator,
  type Invitation,
  type Parcours,
} from "@/lib/api/hooks/auth";
import { messageErreurAuth } from "@/lib/auth/messages";
import { destinationApresConnexion } from "@/lib/auth/redirection";
import { z } from "@/lib/zod";
import { AlerteAuth } from "./CadreAuth";
import { ChampsNouveauMotDePasse, schemaNouveauMotDePasse, type ValeursNouveauMotDePasse } from "./ChampsMotDePasse";
import { TitreEtape } from "./TitreEtape";

export const ETAPES_ENROLEMENT = ["Mot de passe", "Téléphone", "Vérification"] as const;

/** Étapes serveur après lesquelles le mot de passe est déjà réglé (reprise du parcours). */
const ETAPES_MDP_FAIT = new Set(["MDP_OK", "AUTHENTICATOR", "AUTHENTICATOR_EN_ATTENTE", "TELEPHONE"]);

/** « de l’Établissement démo », « de Sahel Distribution ». */
function de(nom: string): string {
  return /^[aeiouyhàâéèêëîïôöûüœ]/i.test(nom) ? `de l’${nom}` : `de ${nom}`;
}

/** Secret en groupes de 4 (le backend l'envoie normalement déjà groupé). */
export function grouperSecret(s: string): string {
  return /\s/.test(s.trim()) ? s.trim() : (s.match(/.{1,4}/g) ?? []).join(" ");
}

/**
 * Parcours en trois étapes « Mot de passe → Téléphone → Vérification » (écran 01b),
 * commun à l'activation par invitation (§ 4.3) et au réenrôlement après
 * téléphone perdu (§ 4.5). Après la vérification, les 10 codes de secours sont
 * affichés une seule fois ; « Accéder à ALPHA » termine et ouvre la session.
 */
export function ParcoursEnrolement({ parcours, jeton }: { parcours: Parcours; jeton: string }) {
  const invitation = useInvitation(parcours, jeton);

  if (invitation.isPending) {
    return (
      <p role="status" className="m-0 text-[15px] text-texte-attenue">
        Vérification du lien…
      </p>
    );
  }
  if (invitation.isError) {
    return (
      <div className="flex flex-col gap-4">
        <TitreEtape taille="activation" focaliser>
          Lien non valide
        </TitreEtape>
        <AlerteAuth>{messageErreurAuth(invitation.error, parcours)}</AlerteAuth>
      </div>
    );
  }
  return <Etapes parcours={parcours} jeton={jeton} invitation={invitation.data} />;
}

function Etapes({ parcours, jeton, invitation }: { parcours: Parcours; jeton: string; invitation: Invitation }) {
  const [etape, setEtape] = useState(() => (ETAPES_MDP_FAIT.has(invitation.etape ?? "") ? 1 : 0));
  const [aChange, setAChange] = useState(false);
  const [authenticator, setAuthenticator] = useState<Authenticator | null>(null);
  const [erreurFatale, setErreurFatale] = useState<string | null>(null);

  const aller = (i: number) => {
    setEtape(i);
    setAChange(true);
  };

  return (
    <div className="flex flex-col gap-5">
      <Stepper etapes={ETAPES_ENROLEMENT} courante={etape} label={parcours === "activation" ? "Étapes de l’activation" : "Étapes du réenrôlement"} />
      {erreurFatale ? (
        <div className="flex flex-col gap-4">
          <TitreEtape taille="activation" focaliser>
            Parcours interrompu
          </TitreEtape>
          <AlerteAuth>{erreurFatale}</AlerteAuth>
        </div>
      ) : etape === 0 ? (
        <EtapeMotDePasse parcours={parcours} jeton={jeton} invitation={invitation} focaliser={aChange} suite={() => aller(1)} />
      ) : etape === 1 ? (
        <EtapeTelephone
          parcours={parcours}
          jeton={jeton}
          focaliser={aChange}
          authenticator={authenticator}
          setAuthenticator={setAuthenticator}
          echec={setErreurFatale}
          suite={() => aller(2)}
        />
      ) : (
        <EtapeVerification
          parcours={parcours}
          jeton={jeton}
          invitation={invitation}
          focaliser={aChange}
          retour={() => aller(1)}
          echec={setErreurFatale}
        />
      )}
    </div>
  );
}

// --- Étape 1 : mot de passe ------------------------------------------------------

const schemaMdpActuel = z.object({ mot_de_passe: z.string().min(1, "Saisissez votre mot de passe actuel.") });

function EtapeMotDePasse({
  parcours,
  jeton,
  invitation,
  focaliser,
  suite,
}: {
  parcours: Parcours;
  jeton: string;
  invitation: Invitation;
  focaliser: boolean;
  suite: () => void;
}) {
  const envoi = useEtapeMotDePasse(parcours, jeton);
  const [erreur, setErreur] = useState<string | null>(null);
  const activation = parcours === "activation";
  const form = useForm<ValeursNouveauMotDePasse>({
    resolver: zodResolver(activation ? schemaNouveauMotDePasse : (schemaMdpActuel as unknown as typeof schemaNouveauMotDePasse)),
    defaultValues: { mot_de_passe: "", confirmation: "" },
  });
  const valeur = form.watch("mot_de_passe");

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      await envoi.mutateAsync(v);
      envoi.reset();
      suite();
    } catch (e) {
      envoi.reset();
      if (estApiError(e) && e.estValidation) {
        setErreur(appliquerErreursApi(e, form.setError, ["mot_de_passe", "confirmation"]));
      } else {
        setErreur(messageErreurAuth(e, parcours));
        if (!activation) form.setValue("mot_de_passe", "");
      }
      form.setFocus("mot_de_passe");
    }
  });

  return (
    <form noValidate onSubmit={soumettre} className="flex flex-col gap-5">
      <div className="flex flex-col gap-4">
        {activation ? (
          <TitreEtape
            taille="activation"
            focaliser={focaliser}
            description={
              <>
                L&rsquo;administrateur {de(invitation.etablissement || "votre établissement")} vous a invité
                {invitation.role ? (
                  <>
                    {" "}
                    comme <strong>{invitation.role}</strong>
                  </>
                ) : null}
                . Choisissez votre mot de passe.
              </>
            }
          >
            Bienvenue, {invitation.prenom}
          </TitreEtape>
        ) : (
          <TitreEtape
            taille="activation"
            focaliser={focaliser}
            description={
              <>
                Votre administrateur a réinitialisé votre double authentification
                {invitation.etablissement ? ` (${invitation.etablissement})` : ""}. Confirmez votre mot de passe actuel pour
                associer votre nouveau téléphone.
              </>
            }
          >
            Bonjour, {invitation.prenom}
          </TitreEtape>
        )}
        <AlerteAuth>{erreur}</AlerteAuth>
        {activation ? (
          <ChampsNouveauMotDePasse
            valeur={valeur}
            enregistrerMdp={form.register("mot_de_passe")}
            enregistrerConfirmation={form.register("confirmation")}
            erreurMdp={form.formState.errors.mot_de_passe?.message}
            erreurConfirmation={form.formState.errors.confirmation?.message}
          />
        ) : (
          <Input
            label="Mot de passe actuel"
            type="password"
            taille="auth"
            autoComplete="current-password"
            erreur={form.formState.errors.mot_de_passe?.message}
            {...form.register("mot_de_passe")}
          />
        )}
      </div>
      <div className="flex flex-wrap justify-between gap-2.5">
        <span className="flex-1" />
        <Button type="submit" taille="auth" chargement={envoi.isPending}>
          Continuer
        </Button>
      </div>
    </form>
  );
}

// --- Étape 2 : téléphone (QR code) ---------------------------------------------------

function EtapeTelephone({
  parcours,
  jeton,
  focaliser,
  authenticator,
  setAuthenticator,
  echec,
  suite,
}: {
  parcours: Parcours;
  jeton: string;
  focaliser: boolean;
  authenticator: Authenticator | null;
  setAuthenticator: (a: Authenticator) => void;
  echec: (m: string) => void;
  suite: () => void;
}) {
  const generer = useGenererAuthenticator(parcours, jeton);
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  // Un seul appel par montage (rappeler l'API régénère le secret ; le mode strict de React rejoue les effets).
  const demande = useRef(false);

  const lancer = () => {
    setErreur(null);
    generer.mutate(undefined, {
      onSuccess: (a) => {
        setAuthenticator(a);
        generer.reset(); // le secret ne reste pas dans le cache des mutations
      },
      onError: (e) => {
        if (estApiError(e) && (e.status === 410 || e.code === "ETAPE_INVALIDE")) echec(messageErreurAuth(e, parcours));
        else setErreur(messageErreurAuth(e, parcours));
      },
    });
  };

  useEffect(() => {
    if (authenticator || demande.current) return;
    demande.current = true;
    lancer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const copier = async () => {
    if (!authenticator) return;
    try {
      await navigator.clipboard.writeText(authenticator.secret_affichable.replace(/\s/g, ""));
      toast({ ton: "succes", titre: "Clé copiée" });
    } catch {
      toast({ ton: "erreur", titre: "Copie impossible", message: "Sélectionnez la clé et copiez-la manuellement." });
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <TitreEtape
        taille="activation"
        focaliser={focaliser}
        description="Scannez ce QR code avec Google Authenticator ou Microsoft Authenticator. L’application affichera un code à 6 chiffres."
      >
        Associez votre téléphone
      </TitreEtape>
      <AlerteAuth>{erreur}</AlerteAuth>
      {authenticator ? (
        <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
          {/* SVG du backend affiché en <img> (data URI) : aucun script ni gestionnaire d'événement ne peut s'exécuter. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(authenticator.qr_svg)}`}
            alt={`QR code à scanner avec votre application Authenticator (compte ${authenticator.compte || authenticator.emetteur})`}
            width={176}
            height={176}
            className="h-44 w-44 flex-none rounded-champ border border-bordure bg-white p-2"
          />
          <div className="flex min-w-0 flex-col gap-2 text-[14px]">
            <p className="m-0 font-semibold text-texte-2">Vous ne pouvez pas scanner ?</p>
            <p className="m-0 text-texte-attenue">Ajoutez un compte manuellement avec cette clé :</p>
            <code
              aria-label="Clé secrète"
              className="block select-all break-words rounded-champ bg-entete-tableau px-3 py-2 font-mono text-[15px] font-semibold tracking-[0.04em] text-encre"
            >
              {grouperSecret(authenticator.secret_affichable)}
            </code>
            <div>
              <Button variante="secondaire" onClick={copier}>
                Copier la clé
              </Button>
            </div>
            <p className="m-0 text-[13px] text-texte-attenue">
              Émetteur : <span className="font-semibold text-texte-2">{authenticator.emetteur}</span>
            </p>
          </div>
        </div>
      ) : (
        !erreur && (
          <p role="status" className="m-0 text-[14px] text-texte-attenue">
            Génération du QR code…
          </p>
        )
      )}
      <p className="m-0 text-[13px] text-texte-attenue">
        Pas encore d&rsquo;application ? Installez{" "}
        <a href="https://support.google.com/accounts/answer/1066447?hl=fr" target="_blank" rel="noopener noreferrer">
          Google Authenticator
        </a>{" "}
        ou{" "}
        <a href="https://www.microsoft.com/fr-fr/security/mobile-authenticator-app" target="_blank" rel="noopener noreferrer">
          Microsoft Authenticator
        </a>
        .
      </p>
      <div className="flex flex-wrap justify-between gap-2.5">
        {erreur ? (
          <Button variante="secondaire" taille="auth" onClick={lancer} chargement={generer.isPending}>
            Réessayer
          </Button>
        ) : (
          <span className="flex-1" />
        )}
        <Button taille="auth" onClick={suite} disabled={!authenticator}>
          Continuer
        </Button>
      </div>
    </div>
  );
}

// --- Étape 3 : vérification puis codes de secours -----------------------------------

function EtapeVerification({
  parcours,
  jeton,
  invitation,
  focaliser,
  retour,
  echec,
}: {
  parcours: Parcours;
  jeton: string;
  invitation: Invitation;
  focaliser: boolean;
  retour: () => void;
  echec: (m: string) => void;
}) {
  const confirmer = useConfirmerAuthenticator(parcours, jeton);
  const terminer = useTerminerEnrolement(parcours, jeton);
  const router = useRouter();
  const { toast } = useToast();
  const [code, setCode] = useState("");
  const [cleOtp, setCleOtp] = useState(0);
  const [erreur, setErreur] = useState<string | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [conserves, setConserves] = useState(false);

  const verifier = async (valeur: string) => {
    if (confirmer.isPending) return;
    if (!/^\d{6}$/.test(valeur)) {
      setErreur("Saisissez les 6 chiffres du code.");
      return;
    }
    setErreur(null);
    try {
      const r = await confirmer.mutateAsync(valeur);
      confirmer.reset();
      setCodes(r.codes_secours);
    } catch (e) {
      confirmer.reset();
      if (estApiError(e) && e.status === 410) {
        echec(messageErreurAuth(e, parcours));
        return;
      }
      setErreur(messageErreurAuth(e, parcours));
      setCode("");
      setCleOtp((k) => k + 1);
    }
  };

  const finir = async () => {
    setErreur(null);
    try {
      const moi = await terminer.mutateAsync();
      setCodes(null); // les codes ne restent pas en mémoire après l'affichage
      toast({
        ton: "succes",
        titre: parcours === "activation" ? "Compte activé" : "Téléphone associé",
        message: "Votre double authentification est active.",
      });
      router.replace(destinationApresConnexion(null, !!moi?.est_super_admin));
    } catch (e) {
      if (estApiError(e) && e.status === 410) echec(messageErreurAuth(e, parcours));
      else setErreur(messageErreurAuth(e, parcours));
    }
  };

  if (codes) {
    return (
      <CodesSecours
        codes={codes}
        etablissement={invitation.etablissement}
        conserves={conserves}
        setConserves={setConserves}
        erreur={erreur}
        chargement={terminer.isPending}
        finir={finir}
      />
    );
  }

  return (
    <form
      noValidate
      className="flex flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault();
        void verifier(code);
      }}
    >
      <TitreEtape taille="activation" focaliser={focaliser} description="Saisissez le code à 6 chiffres affiché par votre application Authenticator.">
        Vérifiez votre téléphone
      </TitreEtape>
      <AlerteAuth>{erreur}</AlerteAuth>
      <OtpInput
        key={cleOtp}
        valeur={code}
        onChange={setCode}
        onComplete={(v) => void verifier(v)}
        label="Code Authenticator"
        desactive={confirmer.isPending}
        autoFocus
      />
      <div className="flex flex-wrap justify-between gap-2.5">
        <Button variante="secondaire" taille="auth" onClick={retour}>
          ← Retour
        </Button>
        <Button type="submit" taille="auth" chargement={confirmer.isPending}>
          Vérifier
        </Button>
      </div>
    </form>
  );
}

function CodesSecours({
  codes,
  etablissement,
  conserves,
  setConserves,
  erreur,
  chargement,
  finir,
}: {
  codes: string[];
  etablissement: string;
  conserves: boolean;
  setConserves: (v: boolean) => void;
  erreur: string | null;
  chargement: boolean;
  finir: () => void;
}) {
  const { toast } = useToast();
  const texte = () =>
    [
      "ALPHA — codes de secours",
      etablissement,
      `Générés le ${new Date().toLocaleString("fr-SN")}`,
      "Chaque code ne sert qu'une seule fois. Conservez-les en lieu sûr.",
      "",
      ...codes,
      "",
    ].join("\n");

  const copier = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast({ ton: "succes", titre: "Codes copiés" });
    } catch {
      toast({ ton: "erreur", titre: "Copie impossible", message: "Utilisez « Télécharger » ou notez les codes." });
    }
  };

  const telecharger = () => {
    const url = URL.createObjectURL(new Blob([texte()], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "alpha-codes-de-secours.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <div className="flex flex-col gap-5">
      <TitreEtape
        taille="activation"
        focaliser
        description="Ils vous permettent de vous connecter si vous n’avez plus votre téléphone. Chaque code ne sert qu’une fois. Ils ne seront plus affichés."
      >
        Vos codes de secours
      </TitreEtape>
      <ul aria-label="Codes de secours" className="m-0 grid list-none grid-cols-2 gap-2 rounded-champ border border-bordure bg-entete-tableau p-3.5">
        {codes.map((c) => (
          <li key={c} className="text-center font-mono text-[15px] font-semibold tracking-[0.06em] text-encre">
            {c}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button variante="secondaire" onClick={copier}>
          Copier
        </Button>
        <Button variante="secondaire" onClick={telecharger}>
          Télécharger
        </Button>
      </div>
      <label className="flex cursor-pointer items-start gap-2.5 text-[14px] font-semibold text-texte-2">
        <input
          type="checkbox"
          checked={conserves}
          onChange={(e) => setConserves(e.currentTarget.checked)}
          className="mt-0.5 h-[18px] w-[18px] flex-none accent-[var(--marque)]"
        />
        J&rsquo;ai conservé mes codes
      </label>
      <AlerteAuth>{erreur}</AlerteAuth>
      <div className="flex flex-wrap justify-between gap-2.5">
        <span className="flex-1" />
        <Button taille="auth" onClick={finir} disabled={!conserves} chargement={chargement}>
          Accéder à ALPHA
        </Button>
      </div>
    </div>
  );
}

/** Onglet « Première connexion » ouvert sans jeton (lien « Activer mon compte »). */
export function SansJeton() {
  return (
    <div className="flex flex-col gap-4">
      <TitreEtape taille="activation" description="Votre compte ALPHA est créé par l’administrateur de votre établissement.">
        Activer mon compte
      </TitreEtape>
      <AlerteAuth ton="info">
        Ouvrez le lien d&rsquo;invitation reçu par e-mail : il vous amène directement ici pour choisir votre mot de passe et associer votre
        téléphone. Le lien est valable 72 heures.
      </AlerteAuth>
      <p className="m-0 text-[14px] text-texte-attenue">
        Lien expiré ou e-mail introuvable ? Demandez à votre administrateur de vous renvoyer l&rsquo;invitation. Déjà activé ?{" "}
        <Link href="/connexion">Connectez-vous</Link>.
      </p>
    </div>
  );
}

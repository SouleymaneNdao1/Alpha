"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";
import { useForm } from "react-hook-form";
import { Button, Input, OtpInput, useToast } from "@/components/ui";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { estApiError } from "@/lib/api/erreurs";
import { useConnexion, useMfa, type MethodeMfa, type PreuveMfa } from "@/lib/api/hooks/auth";
import { messageErreurAuth } from "@/lib/auth/messages";
import { destinationApresConnexion } from "@/lib/auth/redirection";
import { z } from "@/lib/zod";
import { AlerteAuth } from "./CadreAuth";
import { TitreEtape } from "./TitreEtape";

const schemaIdentifiants = z.object({
  email: z.string().trim().min(1, "Saisissez votre adresse e-mail.").email("Adresse e-mail invalide."),
  mot_de_passe: z.string().min(1, "Saisissez votre mot de passe."),
});
type Identifiants = z.infer<typeof schemaIdentifiants>;

/** « abcd efgh » / « abcdefgh » / « ABCD-EFGH » → « ABCD-EFGH » (le serveur normalise aussi). */
export function normaliserCodeSecours(v: string): string {
  const brut = v.toUpperCase().replace(/[^0-9A-Z]/g, "");
  return brut.length === 8 ? `${brut.slice(0, 4)}-${brut.slice(4)}` : brut;
}

type Etape = "identifiants" | "mfa" | "reenrolement";

const MOTIFS: Record<string, { ton: "info" | "succes"; texte: string }> = {
  expiree: { ton: "info", texte: "Votre session a expiré. Reconnectez-vous pour continuer." },
  "mdp-modifie": { ton: "succes", texte: "Votre mot de passe a été modifié. Connectez-vous avec le nouveau mot de passe." },
  deconnexion: { ton: "info", texte: "Vous êtes déconnecté." },
};

/** Écran 01 · Connexion + double authentification (F3). */
export function EcranConnexion() {
  const router = useRouter();
  const params = useSearchParams();
  const { toast } = useToast();
  const connexion = useConnexion();
  const mfa = useMfa();

  const [etape, setEtape] = useState<Etape>("identifiants");
  const [methodes, setMethodes] = useState<MethodeMfa[]>([]);
  const [mode, setMode] = useState<"totp" | "secours">("totp");
  const [erreur, setErreur] = useState<string | null>(null);
  const [aChange, setAChange] = useState(false);
  const motif = MOTIFS[params.get("motif") ?? ""];

  const form = useForm<Identifiants>({ resolver: zodResolver(schemaIdentifiants), defaultValues: { email: "", mot_de_passe: "" } });

  const changerEtape = (e: Etape) => {
    setEtape(e);
    setAChange(true);
  };

  const revenirAuMotDePasse = (message: string | null) => {
    form.setValue("mot_de_passe", "");
    setErreur(message);
    changerEtape("identifiants");
  };

  const soumettreIdentifiants = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      const r = await connexion.mutateAsync({ email: v.email.trim(), mot_de_passe: v.mot_de_passe });
      connexion.reset(); // ne garde pas le mot de passe dans le cache des mutations
      if (r.etape === "REENROLEMENT_REQUIS") {
        form.setValue("mot_de_passe", "");
        changerEtape("reenrolement");
        return;
      }
      const m = r.methodes?.length ? r.methodes : (["TOTP", "CODE_SECOURS"] as MethodeMfa[]);
      setMethodes(m);
      setMode(m.includes("TOTP") ? "totp" : "secours");
      changerEtape("mfa");
    } catch (e) {
      connexion.reset();
      const global = appliquerErreursApi(e, form.setError, ["email", "mot_de_passe"]);
      if (estApiError(e) && e.estValidation) {
        setErreur(global);
        return;
      }
      form.setValue("mot_de_passe", "");
      setErreur(messageErreurAuth(e, "connexion"));
      form.setFocus("mot_de_passe");
    }
  });

  const surSucces = (restants: number, superAdmin: boolean) => {
    if (restants <= 2) {
      toast({
        ton: "alerte",
        titre: restants === 0 ? "Plus aucun code de secours" : `Plus que ${restants} code${restants > 1 ? "s" : ""} de secours`,
        message: "Régénérez vos codes de secours dans Mon compte, onglet Sécurité.",
        duree: null,
      });
    }
    router.replace(destinationApresConnexion(params.get("suivant"), superAdmin));
  };

  const verifier = async (preuve: PreuveMfa): Promise<boolean> => {
    setErreur(null);
    try {
      const r = await mfa.mutateAsync(preuve);
      mfa.reset();
      surSucces(r.codes_secours_restants, r.utilisateur.est_super_admin);
      return true;
    } catch (e) {
      mfa.reset();
      if (estApiError(e) && (e.code === "PREAUTH_EXPIREE" || e.code === "COMPTE_VERROUILLE")) {
        revenirAuMotDePasse(messageErreurAuth(e, "mfa"));
      } else {
        setErreur(messageErreurAuth(e, "mfa"));
      }
      return false;
    }
  };

  return (
    <>
      {motif && etape === "identifiants" && !erreur && <AlerteAuth ton={motif.ton}>{motif.texte}</AlerteAuth>}

      {etape === "identifiants" && (
        <form noValidate onSubmit={soumettreIdentifiants} className="flex flex-col gap-6">
          <TitreEtape focaliser={aChange} description="Accédez à l’espace de votre établissement.">
            Connexion
          </TitreEtape>
          <AlerteAuth>{erreur}</AlerteAuth>
          <Input
            label="Adresse e-mail professionnelle"
            type="email"
            taille="auth"
            autoComplete="username"
            inputMode="email"
            spellCheck={false}
            erreur={form.formState.errors.email?.message}
            {...form.register("email")}
          />
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              {/* Libellé visible ; le libellé accessible est celui (masqué) du champ ci-dessous. */}
              <span aria-hidden="true" className="text-[14px] font-semibold text-texte-2">
                Mot de passe
              </span>
              <Link href="/mot-de-passe-oublie" className="text-[13px]">
                Mot de passe oublié ?
              </Link>
            </div>
            <Input
              id="mot_de_passe"
              label="Mot de passe"
              labelMasque
              type="password"
              taille="auth"
              autoComplete="current-password"
              erreur={form.formState.errors.mot_de_passe?.message}
              {...form.register("mot_de_passe")}
            />
          </div>
          <Button type="submit" taille="auth" pleineLargeur chargement={connexion.isPending}>
            Continuer
          </Button>
          <div className="flex items-center gap-3 text-[13px] text-texte-discret" aria-hidden="true">
            <span className="h-px flex-1 bg-bordure" />
            <span>Client ou fournisseur ?</span>
            <span className="h-px flex-1 bg-bordure" />
          </div>
          <Button variante="secondaire" taille="auth" pleineLargeur disabled title="Disponible prochainement">
            <span className="sr-only">Client ou fournisseur ? </span>Accéder au portail externe
          </Button>
          <p className="m-0 text-center text-[13px] text-texte-attenue">
            Vous avez reçu une invitation ? <Link href="/activation">Activer mon compte</Link>
          </p>
        </form>
      )}

      {etape === "mfa" && (
        <EtapeMfa
          methodes={methodes}
          mode={mode}
          setMode={(m) => {
            setErreur(null);
            setMode(m);
          }}
          erreur={erreur}
          chargement={mfa.isPending}
          verifier={verifier}
          retour={() => revenirAuMotDePasse(null)}
        />
      )}

      {etape === "reenrolement" && (
        <div className="flex flex-col gap-5">
          <TitreEtape focaliser description="Votre double authentification a été réinitialisée par votre administrateur.">
            Reconfigurez votre téléphone
          </TitreEtape>
          <AlerteAuth ton="info">
            Ouvrez le lien de réenrôlement reçu par e-mail (valable 24 heures) pour associer votre nouveau téléphone. Vous pourrez ensuite
            vous connecter normalement.
          </AlerteAuth>
          <p className="m-0 text-[14px] text-texte-attenue">
            Vous n&rsquo;avez pas reçu l&rsquo;e-mail ? Contactez votre administrateur pour qu&rsquo;il vous le renvoie.
          </p>
          <Button variante="secondaire" taille="auth" pleineLargeur onClick={() => revenirAuMotDePasse(null)}>
            ← Retour à la connexion
          </Button>
        </div>
      )}

      <PiedAuth />
    </>
  );
}

function EtapeMfa({
  methodes,
  mode,
  setMode,
  erreur,
  chargement,
  verifier,
  retour,
}: {
  methodes: MethodeMfa[];
  mode: "totp" | "secours";
  setMode: (m: "totp" | "secours") => void;
  erreur: string | null;
  chargement: boolean;
  verifier: (p: PreuveMfa) => Promise<boolean>;
  retour: () => void;
}) {
  const [code, setCode] = useState("");
  const [secours, setSecours] = useState("");
  const [erreurChamp, setErreurChamp] = useState<string | undefined>();
  // Changer la clé remonte l'OtpInput : la première case reprend le focus après un échec.
  const [cleOtp, setCleOtp] = useState(0);
  const refSecours = useRef<HTMLInputElement>(null);
  const totpDisponible = methodes.includes("TOTP");
  const secoursDisponible = methodes.includes("CODE_SECOURS");

  const envoyerTotp = async (valeur: string) => {
    if (chargement) return;
    if (!/^\d{6}$/.test(valeur)) {
      setErreurChamp("Saisissez les 6 chiffres du code.");
      return;
    }
    setErreurChamp(undefined);
    if (!(await verifier({ code: valeur }))) {
      setCode("");
      setCleOtp((k) => k + 1);
    }
  };

  const envoyerSecours = async (e: FormEvent) => {
    e.preventDefault();
    const v = normaliserCodeSecours(secours);
    if (!/^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(v)) {
      setErreurChamp("Le code de secours comporte 8 caractères, au format XXXX-XXXX.");
      refSecours.current?.focus();
      return;
    }
    setErreurChamp(undefined);
    if (!(await verifier({ code_secours: v }))) {
      setSecours("");
      refSecours.current?.focus();
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <TitreEtape
        focaliser
        description={
          mode === "totp"
            ? "Saisissez le code à 6 chiffres affiché par votre application Authenticator."
            : "Saisissez l’un de vos codes de secours. Chaque code ne sert qu’une seule fois."
        }
      >
        Double authentification
      </TitreEtape>
      {!totpDisponible && (
        <AlerteAuth ton="info">
          Votre application Authenticator est suspendue (téléphone signalé perdu). Connectez-vous avec un code de secours.
        </AlerteAuth>
      )}
      <AlerteAuth>{erreur}</AlerteAuth>

      {mode === "totp" ? (
        <form
          noValidate
          className="flex flex-col gap-6"
          onSubmit={(e) => {
            e.preventDefault();
            void envoyerTotp(code);
          }}
        >
          <OtpInput
            key={cleOtp}
            valeur={code}
            onChange={(v) => {
              setCode(v);
              setErreurChamp(undefined);
            }}
            onComplete={(v) => void envoyerTotp(v)}
            label="Code Authenticator"
            aide="Le code change toutes les 30 secondes."
            erreur={erreurChamp}
            desactive={chargement}
            autoFocus
          />
          <Button type="submit" taille="auth" pleineLargeur chargement={chargement}>
            Valider
          </Button>
        </form>
      ) : (
        <form noValidate className="flex flex-col gap-6" onSubmit={envoyerSecours}>
          <Input
            ref={refSecours}
            label="Code de secours"
            taille="auth"
            className="font-mono uppercase tracking-[0.08em]"
            placeholder="XXXX-XXXX"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            maxLength={12}
            autoFocus
            value={secours}
            onChange={(e) => {
              setSecours(e.currentTarget.value);
              setErreurChamp(undefined);
            }}
            erreur={erreurChamp}
            aide="Format XXXX-XXXX, tiret facultatif."
          />
          <Button type="submit" taille="auth" pleineLargeur chargement={chargement}>
            Valider
          </Button>
        </form>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-[14px]">
        <Button variante="lien" onClick={retour} className="px-0">
          ← Changer de compte
        </Button>
        {mode === "totp" && secoursDisponible && (
          <Button variante="lien" onClick={() => setMode("secours")} className="px-0">
            Utiliser un code de secours
          </Button>
        )}
        {mode === "secours" && totpDisponible && (
          <Button variante="lien" onClick={() => setMode("totp")} className="px-0">
            Utiliser l&rsquo;application Authenticator
          </Button>
        )}
      </div>
    </div>
  );
}

/** Liens de pied de carte (écran 01). */
export function PiedAuth() {
  return (
    <nav
      aria-label="Liens utiles"
      className="flex flex-wrap justify-between gap-3 border-t border-ligne pt-4 text-[12px] text-texte-attenue"
    >
      <span title="Disponible prochainement">Confidentialité et CGU</span>
      <span title="Disponible prochainement">Support</span>
      <Link href="/console" prefetch={false} className="text-texte-attenue">
        Console FYXOP
      </Link>
    </nav>
  );
}

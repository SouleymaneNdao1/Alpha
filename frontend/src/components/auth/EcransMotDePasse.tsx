"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button, Input, OtpInput } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { useLienReinitialisation, useOubliMotDePasse, useReinitialiserMotDePasse } from "@/lib/api/hooks/auth";
import { messageErreurAuth } from "@/lib/auth/messages";
import { z } from "@/lib/zod";
import { AlerteAuth } from "./CadreAuth";
import { ChampsNouveauMotDePasse, schemaNouveauMotDePasse, type ValeursNouveauMotDePasse } from "./ChampsMotDePasse";
import { normaliserCodeSecours } from "./EcranConnexion";
import { TitreEtape } from "./TitreEtape";

const schemaOubli = z.object({
  email: z.string().trim().min(1, "Saisissez votre adresse e-mail.").email("Adresse e-mail invalide."),
});

/** `/mot-de-passe-oublie` : `POST /auth/mot-de-passe/oubli` (toujours 202). */
export function EcranMotDePasseOublie() {
  const oubli = useOubliMotDePasse();
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoye, setEnvoye] = useState(false);
  const form = useForm<{ email: string }>({ resolver: zodResolver(schemaOubli), defaultValues: { email: "" } });

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      await oubli.mutateAsync({ email: v.email.trim() });
      setEnvoye(true);
    } catch (e) {
      setErreur(estApiError(e) && e.estValidation ? appliquerErreursApi(e, form.setError, ["email"]) : messageErreurAuth(e, "oubli"));
    }
  });

  if (envoye) {
    return (
      <div className="flex flex-col gap-5">
        <TitreEtape focaliser description="Consultez votre boîte de réception.">
          Vérifiez vos e-mails
        </TitreEtape>
        <AlerteAuth ton="succes">
          Si un compte actif correspond à cette adresse, un lien de réinitialisation vient de vous être envoyé. Il est valable 30 minutes.
        </AlerteAuth>
        <p className="m-0 text-[14px] text-texte-attenue">
          Pour choisir votre nouveau mot de passe, vous devrez aussi saisir un code de votre application Authenticator ou un code de
          secours. Plus d&rsquo;accès à votre téléphone ni à vos codes ? Utilisez{" "}
          <Link href="/activation?onglet=telephone-perdu">Téléphone perdu</Link>.
        </p>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={soumettre} className="flex flex-col gap-6">
      <TitreEtape description="Saisissez votre adresse e-mail professionnelle : nous vous enverrons un lien pour choisir un nouveau mot de passe.">
        Mot de passe oublié
      </TitreEtape>
      <AlerteAuth>{erreur}</AlerteAuth>
      <Input
        label="Adresse e-mail professionnelle"
        type="email"
        taille="auth"
        autoComplete="username"
        spellCheck={false}
        erreur={form.formState.errors.email?.message}
        {...form.register("email")}
      />
      <Button type="submit" taille="auth" pleineLargeur chargement={oubli.isPending}>
        Envoyer le lien
      </Button>
    </form>
  );
}

/** `/reinitialisation/[jeton]` : nouveau mot de passe + preuve MFA (§ 4.7). */
export function EcranReinitialisation({ jeton }: { jeton: string }) {
  const lien = useLienReinitialisation(jeton);
  const reinit = useReinitialiserMotDePasse(jeton);
  const router = useRouter();
  const [mode, setMode] = useState<"totp" | "secours">("totp");
  const [code, setCode] = useState("");
  const [secours, setSecours] = useState("");
  const [erreurPreuve, setErreurPreuve] = useState<string | undefined>();
  const [erreur, setErreur] = useState<string | null>(null);
  const [lienMort, setLienMort] = useState<string | null>(null);
  const form = useForm<ValeursNouveauMotDePasse>({
    resolver: zodResolver(schemaNouveauMotDePasse),
    defaultValues: { mot_de_passe: "", confirmation: "" },
  });
  const valeur = form.watch("mot_de_passe");

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    const preuve =
      mode === "totp" ? (/^\d{6}$/.test(code) ? { code } : null) : /^[0-9A-Z]{4}-[0-9A-Z]{4}$/.test(normaliserCodeSecours(secours)) ? { code_secours: normaliserCodeSecours(secours) } : null;
    if (!preuve) {
      setErreurPreuve(mode === "totp" ? "Saisissez les 6 chiffres du code." : "Le code de secours est au format XXXX-XXXX.");
      return;
    }
    setErreurPreuve(undefined);
    try {
      await reinit.mutateAsync({ ...v, ...preuve });
      reinit.reset();
      router.replace("/connexion?motif=mdp-modifie");
    } catch (e) {
      reinit.reset();
      if (estApiError(e) && e.status === 410) {
        setLienMort(messageErreurAuth(e, "reinitialisation"));
      } else if (estApiError(e) && e.estValidation) {
        setErreur(appliquerErreursApi(e, form.setError, ["mot_de_passe", "confirmation"]));
      } else {
        setErreur(messageErreurAuth(e, "reinitialisation"));
        setCode("");
        setSecours("");
      }
    }
  });

  if (lien.isPending) {
    return (
      <p role="status" className="m-0 text-[15px] text-texte-attenue">
        Vérification du lien…
      </p>
    );
  }
  if (lien.isError || lienMort) {
    return (
      <div className="flex flex-col gap-4">
        <TitreEtape focaliser>Lien non valide</TitreEtape>
        <AlerteAuth>{lienMort ?? messageErreurAuth(lien.error, "reinitialisation")}</AlerteAuth>
        <div>
          <Link href="/mot-de-passe-oublie">Demander un nouveau lien</Link>
        </div>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={soumettre} className="flex flex-col gap-5">
      <TitreEtape description={<>Compte {lien.data.email_masque}. Choisissez un nouveau mot de passe, puis prouvez votre identité.</>}>
        Nouveau mot de passe
      </TitreEtape>
      <AlerteAuth>{erreur}</AlerteAuth>
      <ChampsNouveauMotDePasse
        valeur={valeur}
        enregistrerMdp={form.register("mot_de_passe")}
        enregistrerConfirmation={form.register("confirmation")}
        erreurMdp={form.formState.errors.mot_de_passe?.message}
        erreurConfirmation={form.formState.errors.confirmation?.message}
      />
      {mode === "totp" ? (
        <OtpInput valeur={code} onChange={setCode} label="Code Authenticator" erreur={erreurPreuve} />
      ) : (
        <Input
          label="Code de secours"
          taille="auth"
          className="font-mono uppercase tracking-[0.08em]"
          placeholder="XXXX-XXXX"
          autoComplete="off"
          spellCheck={false}
          maxLength={12}
          value={secours}
          onChange={(e) => setSecours(e.currentTarget.value)}
          erreur={erreurPreuve}
        />
      )}
      <div>
        <Button
          variante="lien"
          className="px-0"
          onClick={() => {
            setErreurPreuve(undefined);
            setMode(mode === "totp" ? "secours" : "totp");
          }}
        >
          {mode === "totp" ? "Utiliser un code de secours" : "Utiliser l’application Authenticator"}
        </Button>
      </div>
      <Button type="submit" taille="auth" pleineLargeur chargement={reinit.isPending}>
        Enregistrer le mot de passe
      </Button>
    </form>
  );
}

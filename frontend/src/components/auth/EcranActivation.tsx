"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Button, Input, Tabs } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { useSignalerTelephonePerdu } from "@/lib/api/hooks/auth";
import { messageErreurAuth } from "@/lib/auth/messages";
import { z } from "@/lib/zod";
import { AlerteAuth } from "./CadreAuth";
import { ParcoursEnrolement, SansJeton } from "./ParcoursEnrolement";
import { TitreEtape } from "./TitreEtape";

const ONGLETS = ["premiere-connexion", "telephone-perdu"] as const;
type IdOnglet = (typeof ONGLETS)[number];

/** Écran 01b · Activation du compte et téléphone perdu (F4). `?jeton=…&onglet=premiere-connexion|telephone-perdu`. */
export function EcranActivation() {
  const params = useSearchParams();
  const router = useRouter();
  const chemin = usePathname();
  const jeton = params.get("jeton");
  const demande = params.get("onglet");
  const onglet: IdOnglet = (ONGLETS as readonly string[]).includes(demande ?? "") ? (demande as IdOnglet) : "premiere-connexion";

  const changer = (id: string) => {
    const p = new URLSearchParams(params.toString());
    p.set("onglet", id);
    router.replace(`${chemin}?${p.toString()}`, { scroll: false });
  };

  return (
    <Tabs
      label="Situation"
      variante="segmente"
      actif={onglet}
      onChange={changer}
      onglets={[
        {
          id: "premiere-connexion",
          libelle: "Première connexion",
          contenu: jeton ? <ParcoursEnrolement parcours="activation" jeton={jeton} /> : <SansJeton />,
        },
        { id: "telephone-perdu", libelle: "Téléphone perdu", contenu: <TelephonePerdu /> },
      ]}
    />
  );
}

const schemaSignalement = z.object({
  email: z.string().trim().min(1, "Saisissez votre adresse e-mail.").email("Adresse e-mail invalide."),
  mot_de_passe: z.string().min(1, "Saisissez votre mot de passe."),
});
type Signalement = z.infer<typeof schemaSignalement>;

/** Onglet « Téléphone perdu » : `POST /auth/telephone-perdu` (réponse toujours 202). */
function TelephonePerdu() {
  const signaler = useSignalerTelephonePerdu();
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoye, setEnvoye] = useState(false);
  const form = useForm<Signalement>({ resolver: zodResolver(schemaSignalement), defaultValues: { email: "", mot_de_passe: "" } });

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      await signaler.mutateAsync({ email: v.email.trim(), mot_de_passe: v.mot_de_passe });
      signaler.reset();
      form.reset();
      setEnvoye(true);
    } catch (e) {
      signaler.reset();
      form.setValue("mot_de_passe", "");
      setErreur(estApiError(e) && e.estValidation ? appliquerErreursApi(e, form.setError, ["email", "mot_de_passe"]) : messageErreurAuth(e, "telephone-perdu"));
    }
  });

  if (envoye) {
    return (
      <div className="flex flex-col gap-4">
        <TitreEtape taille="activation" focaliser>
          Signalement enregistré
        </TitreEtape>
        <AlerteAuth ton="succes">
          Si ces informations correspondent à votre compte, la signature de vos décisions est bloquée dès maintenant, toutes vos sessions
          sont fermées et votre administrateur est prévenu. Un e-mail de confirmation vous est envoyé.
        </AlerteAuth>
        <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5 text-[14px] text-texte-attenue">
          <li>En attendant, vous pouvez vous connecter avec un code de secours pour consulter et travailler.</li>
          <li>Votre administrateur vérifiera votre identité, puis vous enverra un lien pour associer votre nouveau téléphone.</li>
        </ul>
        <div>
          <Link href="/connexion">Se connecter avec un code de secours</Link>
        </div>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={soumettre} className="flex flex-col gap-5">
      <TitreEtape
        taille="activation"
        description="Signalez-le tout de suite : la signature de vos décisions est bloquée, vos sessions sont fermées et votre administrateur est prévenu pour réinitialiser votre double authentification."
      >
        Téléphone perdu ou volé ?
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
      <Input
        label="Mot de passe"
        type="password"
        taille="auth"
        autoComplete="current-password"
        erreur={form.formState.errors.mot_de_passe?.message}
        {...form.register("mot_de_passe")}
      />
      <div className="flex flex-wrap justify-between gap-2.5">
        <span className="flex-1" />
        <Button type="submit" taille="auth" chargement={signaler.isPending}>
          Signaler la perte
        </Button>
      </div>
    </form>
  );
}

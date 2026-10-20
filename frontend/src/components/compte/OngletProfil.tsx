"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { Button, Card, Input, Select, useToast } from "@/components/ui";
import { AlerteErreur } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { useModifierProfil } from "@/lib/api/hooks/compte";
import { z } from "@/lib/zod";
import { useState } from "react";

const schema = z.object({
  prenom: z.string().trim().min(1, "Saisissez votre prénom."),
  nom: z.string().trim().min(1, "Saisissez votre nom."),
  telephone_mobile: z
    .string()
    .trim()
    .refine((v) => v === "" || /^\+[1-9][0-9]{6,14}$/.test(v), "Format international attendu (ex. +221770000000)."),
});
type Valeurs = z.infer<typeof schema>;

/** Onglet « Profil » : `PATCH /moi`. L'e-mail est en lecture seule ; rôle et périmètre sont attribués par l'administrateur. */
export function OngletProfil() {
  const moi = useMoi();
  const modifier = useModifierProfil();
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  const form = useForm<Valeurs>({
    resolver: zodResolver(schema),
    defaultValues: { prenom: moi.prenom, nom: moi.nom, telephone_mobile: moi.telephone_mobile ?? "" },
  });
  const { errors, isDirty } = form.formState;

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      const maj = await modifier.mutateAsync({ prenom: v.prenom, nom: v.nom, telephone_mobile: v.telephone_mobile === "" ? null : v.telephone_mobile, langue: "fr" });
      form.reset({ prenom: maj.prenom, nom: maj.nom, telephone_mobile: maj.telephone_mobile ?? "" });
      toast({ ton: "succes", titre: "Profil enregistré" });
    } catch (e) {
      setErreur(appliquerErreursApi(e, form.setError, ["prenom", "nom", "telephone_mobile"]));
    }
  });

  return (
    <Card titre="Profil" description="Vos informations personnelles.">
      <form noValidate onSubmit={soumettre} className="flex max-w-[640px] flex-col gap-4">
        <AlerteErreur>{erreur}</AlerteErreur>
        <fieldset className="m-0 flex min-w-0 flex-col gap-1.5 border-0 p-0">
          <legend className="mb-1.5 p-0 text-[13px] font-semibold text-texte-2">Nom complet</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="Prénom" autoComplete="given-name" erreur={errors.prenom?.message} {...form.register("prenom")} />
            <Input label="Nom" autoComplete="family-name" erreur={errors.nom?.message} {...form.register("nom")} />
          </div>
        </fieldset>
        <Input label="E-mail professionnel" type="email" value={moi.email} readOnly aide="L'adresse e-mail n'est pas modifiable. Adressez une demande à votre administrateur." />
        <Input
          label="Téléphone mobile"
          type="tel"
          autoComplete="tel"
          placeholder="+221770000000"
          erreur={errors.telephone_mobile?.message}
          {...form.register("telephone_mobile")}
        />
        <Select label="Langue" options={[{ valeur: "fr", libelle: "Français" }]} defaultValue="fr" aide="Le français est la seule langue disponible pour le moment." />
        <p className="m-0 rounded-champ bg-entete-tableau px-3.5 py-3 text-[14px] text-texte-2">
          <strong>Rôle :</strong> {moi.role_principal?.libelle ?? "—"} · <strong>Périmètre :</strong> {moi.role_principal?.unite ?? "Tout l'établissement"}
          <span className="mt-1 block text-[13px] text-texte-attenue">
            Le rôle et le périmètre sont attribués par l&rsquo;administrateur. Pour les changer, adressez-lui une demande.
          </span>
        </p>
        <div>
          <Button type="submit" chargement={modifier.isPending} disabled={!isDirty}>
            Enregistrer
          </Button>
        </div>
      </form>
    </Card>
  );
}

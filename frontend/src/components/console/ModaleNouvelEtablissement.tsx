"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { Input, ModaleCode, Select, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { useProvisionner } from "@/lib/api/hooks/plateforme";
import { z } from "@/lib/zod";
import { TYPES_ETABLISSEMENT } from "./statuts";

const schema = z.object({
  raison_sociale: z.string().trim().min(1, "Indiquez la raison sociale.").max(200),
  code: z
    .string()
    .min(1, "Indiquez le code de l'établissement.")
    .max(40)
    .regex(/^[a-z0-9-]+$/, "Minuscules, chiffres et tirets uniquement."),
  type: z.enum(["BANQUE", "SFD", "PME"]),
  pays: z.string().regex(/^[A-Z]{2}$/, "Code pays à 2 lettres majuscules (ex. SN)."),
  prenom: z.string().trim().min(1, "Indiquez le prénom.").max(80),
  nom: z.string().trim().min(1, "Indiquez le nom.").max(80),
  email: z.string().trim().min(1, "Indiquez l'adresse e-mail.").max(254).pipe(z.email("Adresse e-mail invalide.")),
});
type Valeurs = z.infer<typeof schema>;
const CHAMPS = ["raison_sociale", "code", "type", "pays"] as const;

/**
 * Provisionnement d'un établissement avec son premier administrateur, confirmé par un code TOTP.
 * Les conflits 409 (CODE_EXISTE, EMAIL_EXISTE) sont rattachés au champ concerné : l'API les contrôle
 * avant le code, qui n'est donc pas consommé et reste saisi.
 */
export function ModaleNouvelEtablissement({ onFermer }: { onFermer: () => void }) {
  const provisionner = useProvisionner();
  const { toast } = useToast();
  const router = useRouter();
  const form = useForm<Valeurs>({
    resolver: zodResolver(schema),
    mode: "onChange",
    defaultValues: { raison_sociale: "", code: "", type: "BANQUE", pays: "SN", prenom: "", nom: "", email: "" },
  });
  const { errors, isValid } = form.formState;

  const envoyer = async (code: string) => {
    const v = form.getValues();
    try {
      const r = await provisionner.mutateAsync({
        code: v.code,
        raison_sociale: v.raison_sociale.trim(),
        type: v.type,
        pays: v.pays,
        administrateur: { email: v.email.trim(), prenom: v.prenom.trim(), nom: v.nom.trim() },
        code_totp: code,
      });
      toast({ ton: "succes", titre: "Établissement créé", message: `Invitation envoyée à ${r.administrateur.email}.` });
      onFermer();
      router.push(`/console/etablissements/${r.id}`);
    } catch (e) {
      if (estApiError(e) && e.code === "CODE_EXISTE") {
        form.setError("code", { type: "serveur", message: "Ce code est déjà utilisé par un autre établissement." });
        return;
      }
      if (estApiError(e) && e.code === "EMAIL_EXISTE") {
        form.setError("email", { type: "serveur", message: "Cette adresse e-mail est déjà utilisée sur la plateforme." });
        return;
      }
      if (estApiError(e) && e.estValidation && typeof e.details === "object" && e.details !== null) {
        // Erreurs par champ ; celles du premier administrateur arrivent imbriquées sous `administrateur`.
        const texte = (m: unknown) => (Array.isArray(m) ? m.join(" ") : String(m));
        let rattache = false;
        for (const [champ, m] of Object.entries(e.details as Record<string, unknown>)) {
          if ((CHAMPS as readonly string[]).includes(champ)) {
            form.setError(champ as (typeof CHAMPS)[number], { type: "serveur", message: texte(m) });
            rattache = true;
          } else if (champ === "administrateur" && typeof m === "object" && m !== null) {
            for (const [sous, mm] of Object.entries(m)) {
              if (sous === "email" || sous === "prenom" || sous === "nom") {
                form.setError(sous, { type: "serveur", message: texte(mm) });
                rattache = true;
              }
            }
          }
        }
        if (rattache) return;
      }
      throw e;
    }
  };

  return (
    <ModaleCode
      titre="Nouvel établissement"
      description="Crée l'établissement, son catalogue de rôles et son unité racine, puis invite son premier administrateur par e-mail."
      libelleAction="Créer l'établissement"
      taille="large"
      peutConfirmer={isValid}
      onConfirmer={envoyer}
      onFermer={onFermer}
    >
      <div className="flex flex-col gap-4">
        <Input label="Raison sociale" required autoComplete="off" erreur={errors.raison_sociale?.message} {...form.register("raison_sociale")} />
        <div className="grid gap-3 sm:grid-cols-[1fr_160px_100px]">
          <Input
            label="Code de l'établissement"
            required
            autoComplete="off"
            spellCheck={false}
            aide="Définitif, ex. banque-atlantique-sn."
            erreur={errors.code?.message}
            {...form.register("code")}
          />
          <Select label="Type" options={TYPES_ETABLISSEMENT.map((t) => ({ valeur: t.valeur, libelle: t.libelle }))} erreur={errors.type?.message} {...form.register("type")} />
          <Input label="Pays" required maxLength={2} autoComplete="off" erreur={errors.pays?.message} {...form.register("pays")} />
        </div>
        <fieldset className="m-0 flex flex-col gap-3 rounded-champ border border-bordure p-3.5">
          <legend className="px-1.5 text-[13px] font-semibold text-texte-2">Premier administrateur</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="Prénom" required autoComplete="off" erreur={errors.prenom?.message} {...form.register("prenom")} />
            <Input label="Nom" required autoComplete="off" erreur={errors.nom?.message} {...form.register("nom")} />
          </div>
          <Input label="Adresse e-mail professionnelle" type="email" required autoComplete="off" erreur={errors.email?.message} {...form.register("email")} />
        </fieldset>
      </div>
    </ModaleCode>
  );
}

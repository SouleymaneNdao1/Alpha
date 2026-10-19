"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { AlerteErreur, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Input, Modal, Select, Table, Td, Th, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { aplatirUnites, useActionsUnites, useUnites, type TypeUnite, type UniteArbre } from "@/lib/api/hooks/admin";
import { messageErreur } from "@/lib/compte/messages";
import { possede } from "@/lib/permissions";
import { z } from "@/lib/zod";

const TYPES: ReadonlyArray<{ valeur: TypeUnite; libelle: string }> = [
  { valeur: "DIRECTION", libelle: "Direction" },
  { valeur: "SERVICE", libelle: "Service" },
  { valeur: "AGENCE", libelle: "Agence" },
  { valeur: "COMITE", libelle: "Comité" },
];
const libelleType = (t: string) => TYPES.find((x) => x.valeur === t)?.libelle ?? t;

/** `/administration/organisation` : arbre des unités (directions, services, agences, comités). */
export function EcranUnites() {
  const moi = useMoi();
  const unites = useUnites();
  const peutEcrire = possede(moi, "admin.organisation");
  const [edition, setEdition] = useState<UniteArbre | "nouvelle" | null>(null);
  const plat = aplatirUnites(unites.data ?? []);

  return (
    <Card
      titre="Unités et périmètres"
      description="Directions, services, agences et comités auxquels les rôles sont rattachés."
      marge={false}
      actions={peutEcrire ? <Button onClick={() => setEdition("nouvelle")}>+ Nouvelle unité</Button> : undefined}
    >
      {unites.isPending ? (
        <div className="px-4.5 pb-4"><Chargement texte="Chargement des unités…" /></div>
      ) : unites.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={unites.error} titre="Unités indisponibles" onReessayer={() => void unites.refetch()} /></div>
      ) : plat.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucune unité n&rsquo;est définie.</p>
      ) : (
        <Table legende="Unités organisationnelles">
          <thead>
            <tr>
              <Th>Libellé</Th>
              <Th>Code</Th>
              <Th>Type</Th>
              <Th>Statut</Th>
              {peutEcrire && <Th><span className="sr-only">Action</span></Th>}
            </tr>
          </thead>
          <tbody>
            {plat.map((u) => (
              <tr key={u.id}>
                <Td className="font-semibold" style={{ paddingLeft: 12 + u.profondeur * 22 }}>
                  {u.profondeur > 0 && <span aria-hidden="true" className="mr-1.5 text-texte-discret">↳</span>}
                  {u.libelle}
                </Td>
                <Td mono>{u.code}</Td>
                <Td>{libelleType(u.type)}</Td>
                <Td>{u.actif ? <Badge ton="vert">Active</Badge> : <Badge ton="gris">Inactive</Badge>}</Td>
                {peutEcrire && (
                  <Td className="text-right">
                    <Button variante="secondaire" onClick={() => setEdition(u)} aria-label={`Modifier l'unité ${u.libelle}`}>Modifier</Button>
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {edition && <ModaleUnite unite={edition === "nouvelle" ? null : edition} plat={plat} onFermer={() => setEdition(null)} />}
    </Card>
  );
}

const schema = z.object({
  type: z.enum(["DIRECTION", "SERVICE", "AGENCE", "COMITE"]),
  code: z.string().trim().min(1, "Le code est obligatoire.").max(40, "40 caractères au plus."),
  libelle: z.string().trim().min(1, "Le libellé est obligatoire.").max(150, "150 caractères au plus."),
  parent_id: z.string(),
  actif: z.boolean(),
});
type Valeurs = z.infer<typeof schema>;

function descendants(u: UniteArbre): string[] {
  return u.enfants.flatMap((e) => [e.id, ...descendants(e)]);
}

function ModaleUnite({ unite, plat, onFermer }: { unite: UniteArbre | null; plat: Array<UniteArbre & { profondeur: number }>; onFermer: () => void }) {
  const idForm = useId();
  const { creer, modifier } = useActionsUnites();
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  const exclus = unite ? new Set([unite.id, ...descendants(unite)]) : new Set<string>();
  const form = useForm<Valeurs>({
    resolver: zodResolver(schema),
    defaultValues: { type: unite?.type ?? "SERVICE", code: unite?.code ?? "", libelle: unite?.libelle ?? "", parent_id: unite?.parent_id ?? "", actif: unite?.actif ?? true },
  });
  const { errors } = form.formState;
  const envoi = creer.isPending || modifier.isPending;

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    const corps = { type: v.type, code: v.code, libelle: v.libelle, parent_id: v.parent_id || null, actif: v.actif };
    try {
      if (unite) await modifier.mutateAsync({ id: unite.id, ...corps });
      else await creer.mutateAsync(corps);
      toast({ ton: "succes", titre: unite ? "Unité enregistrée" : "Unité créée" });
      onFermer();
    } catch (e) {
      if (estApiError(e) && e.code === "CODE_EXISTE") form.setError("code", { type: "serveur", message: "Une unité porte déjà ce code." });
      else setErreur(estApiError(e) && e.estValidation ? appliquerErreursApi(e, form.setError, ["type", "code", "libelle", "parent_id"]) : messageErreur(e));
    }
  });

  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!envoi}
      titre={unite ? `Modifier l'unité « ${unite.libelle} »` : "Nouvelle unité"}
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={envoi}>Annuler</Button>
          <Button type="submit" form={idForm} chargement={envoi}>Enregistrer</Button>
        </>
      }
    >
      <form id={idForm} noValidate onSubmit={soumettre} className="flex flex-col gap-4">
        <AlerteErreur>{erreur}</AlerteErreur>
        <Input label="Libellé" required erreur={errors.libelle?.message} {...form.register("libelle")} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Code" required erreur={errors.code?.message} {...form.register("code")} />
          <Select label="Type" options={TYPES.map((t) => ({ valeur: t.valeur, libelle: t.libelle }))} erreur={errors.type?.message} {...form.register("type")} />
        </div>
        <Select
          label="Unité parente"
          placeholder="Aucune (racine)"
          options={plat.filter((p) => !exclus.has(p.id)).map((p) => ({ valeur: p.id, libelle: `${"— ".repeat(p.profondeur)}${p.libelle}` }))}
          erreur={errors.parent_id?.message}
          {...form.register("parent_id")}
        />
        {unite && (
          <label className="flex cursor-pointer items-center gap-2.5 text-[14px] font-semibold text-texte-2">
            <input type="checkbox" className="h-[18px] w-[18px] accent-[var(--marque)]" {...form.register("actif")} />
            Unité active
          </label>
        )}
      </form>
    </Modal>
  );
}

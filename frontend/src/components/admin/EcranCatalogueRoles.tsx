"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useState } from "react";
import { useForm } from "react-hook-form";
import { AlerteErreur, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Drawer, Input, Table, Td, Th, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { useActionsRoles, usePermissions, useRoles, type RoleCatalogue } from "@/lib/api/hooks/admin";
import { messageErreur } from "@/lib/compte/messages";
import { possede } from "@/lib/permissions";
import { z } from "@/lib/zod";

/** `/administration/roles` : catalogue des rôles ; création et modification dans un panneau latéral. */
export function EcranCatalogueRoles() {
  const moi = useMoi();
  const roles = useRoles();
  const actions = useActionsRoles();
  const { toast } = useToast();
  const peutEcrire = possede(moi, "admin.roles");
  const [edition, setEdition] = useState<RoleCatalogue | "nouveau" | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const basculer = async (r: RoleCatalogue) => {
    setErreur(null);
    try {
      await (r.actif ? actions.desactiver : actions.activer).mutateAsync(r.id);
      toast({ ton: "succes", titre: r.actif ? "Rôle désactivé" : "Rôle réactivé", message: r.libelle });
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };

  return (
    <Card
      titre="Catalogue des rôles"
      description="Les rôles attribuables aux utilisateurs de l'établissement."
      marge={false}
      actions={peutEcrire ? <Button onClick={() => setEdition("nouveau")}>+ Nouveau rôle</Button> : undefined}
    >
      {erreur && <div className="px-4.5 pb-3"><AlerteErreur>{erreur}</AlerteErreur></div>}
      {roles.isPending ? (
        <div className="px-4.5 pb-4"><Chargement texte="Chargement des rôles…" /></div>
      ) : roles.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={roles.error} titre="Rôles indisponibles" onReessayer={() => void roles.refetch()} /></div>
      ) : (
        <Table legende="Catalogue des rôles">
          <thead>
            <tr>
              <Th>Libellé</Th>
              <Th>Description</Th>
              <Th>Titulaires</Th>
              <Th>Actif</Th>
              <Th>Système</Th>
              {peutEcrire && <Th><span className="sr-only">Actions</span></Th>}
            </tr>
          </thead>
          <tbody>
            {roles.data.map((r) => (
              <tr key={r.id}>
                <Td className="font-semibold">{r.libelle}</Td>
                <Td retourLigne className="max-w-[360px] text-texte-2">{r.description || "—"}</Td>
                <Td>
                  <span className="font-mono">{r.nb_titulaires}</span> {r.vacant && <Badge ton="ambre">Vacant</Badge>}
                </Td>
                <Td>{r.actif ? <Badge ton="vert">Actif</Badge> : <Badge ton="gris">Inactif</Badge>}</Td>
                <Td>{r.est_systeme ? <Badge ton="bleu">Système</Badge> : "—"}</Td>
                {peutEcrire && (
                  <Td className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button variante="secondaire" onClick={() => setEdition(r)} aria-label={`Modifier le rôle ${r.libelle}`}>Modifier</Button>
                      {!r.est_systeme && (
                        <Button variante="secondaire" disabled={actions.desactiver.isPending || actions.activer.isPending} onClick={() => void basculer(r)} aria-label={`${r.actif ? "Désactiver" : "Réactiver"} le rôle ${r.libelle}`}>
                          {r.actif ? "Désactiver" : "Réactiver"}
                        </Button>
                      )}
                    </div>
                  </Td>
                )}
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {edition && <PanneauRole role={edition === "nouveau" ? null : edition} onFermer={() => setEdition(null)} />}
    </Card>
  );
}

const schemaRole = z.object({
  libelle: z.string().trim().min(1, "Le libellé est obligatoire.").max(100, "100 caractères au plus."),
  description: z.string().max(500, "500 caractères au plus."),
});
type ValeursRole = z.infer<typeof schemaRole>;

function PanneauRole({ role, onFermer }: { role: RoleCatalogue | null; onFermer: () => void }) {
  const idForm = useId();
  const { creer, modifier } = useActionsRoles();
  const permissions = usePermissions();
  const { toast } = useToast();
  const [codes, setCodes] = useState<string[]>(role?.permissions ?? []);
  const [erreur, setErreur] = useState<string | null>(null);
  const form = useForm<ValeursRole>({ resolver: zodResolver(schemaRole), defaultValues: { libelle: role?.libelle ?? "", description: role?.description ?? "" } });
  const { errors } = form.formState;
  const systeme = role?.est_systeme ?? false;
  const envoi = creer.isPending || modifier.isPending;

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      if (role) {
        const corps: { id: string; libelle: string; description: string; permissions?: string[] } = { id: role.id, libelle: v.libelle, description: v.description };
        if (!systeme) corps.permissions = codes;
        await modifier.mutateAsync(corps);
        toast({ ton: "succes", titre: "Rôle enregistré" });
      } else {
        await creer.mutateAsync({ libelle: v.libelle, description: v.description, permissions: codes });
        toast({ ton: "succes", titre: "Rôle créé" });
      }
      onFermer();
    } catch (e) {
      if (estApiError(e) && e.code === "LIBELLE_EXISTE") form.setError("libelle", { type: "serveur", message: "Un rôle porte déjà ce libellé." });
      else setErreur(estApiError(e) && e.estValidation ? appliquerErreursApi(e, form.setError, ["libelle", "description"]) : messageErreur(e));
    }
  });

  return (
    <Drawer
      ouvert
      onFermer={onFermer}
      fermable={!envoi}
      titre={role ? `Modifier le rôle « ${role.libelle} »` : "Nouveau rôle"}
      description={systeme ? "Rôle système : ses habilitations ne sont pas modifiables." : "Choisissez les habilitations que ce rôle confère."}
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
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-semibold text-texte-2">Description</span>
          <textarea
            rows={3}
            className="block w-full rounded-champ border border-bordure-champ bg-surface px-3 py-2 text-[14px] focus:outline focus:outline-2 focus:outline-offset-1 focus:outline-marque"
            {...form.register("description")}
          />
          {errors.description && <span className="text-[13px] font-medium text-danger-texte">{errors.description.message}</span>}
        </label>
        <fieldset className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
          <legend className="mb-1 p-0 text-[13px] font-semibold text-texte-2">Habilitations</legend>
          {permissions.isPending && <Chargement />}
          {permissions.isError && <AlerteErreur>{messageErreur(permissions.error)}</AlerteErreur>}
          {permissions.data?.map((p) => (
            <label key={p.code} className="flex cursor-pointer items-start gap-2.5 text-[14px]">
              <input
                type="checkbox"
                disabled={systeme}
                checked={codes.includes(p.code)}
                onChange={(e) => {
                  const coche = e.currentTarget.checked;
                  setCodes((c) => (coche ? [...c, p.code] : c.filter((x) => x !== p.code)));
                }}
                className="mt-0.5 h-[18px] w-[18px] flex-none accent-[var(--marque)]"
              />
              <span className="flex flex-col">
                <span className="font-semibold">{p.libelle}</span>
                <span className="text-[13px] text-texte-attenue">{p.description}</span>
              </span>
            </label>
          ))}
        </fieldset>
      </form>
    </Drawer>
  );
}

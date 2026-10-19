"use client";

import { useMemo, useState } from "react";
import { AccesRefuse, AlerteErreur, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Table, Td, Th, useToast } from "@/components/ui";
import { useActionsRoles, usePermissions, useRoles } from "@/lib/api/hooks/admin";
import { messageErreur } from "@/lib/compte/messages";
import { possede } from "@/lib/permissions";

/** `/administration/habilitations` : matrice rôle × permission (`PATCH /admin/roles/{id}`). */
export function EcranHabilitations() {
  const moi = useMoi();
  const roles = useRoles();
  const permissions = usePermissions();
  const { modifier } = useActionsRoles();
  const { toast } = useToast();
  // Modifications non enregistrées : id du rôle → codes cochés.
  const [brouillon, setBrouillon] = useState<Record<string, string[]>>({});
  const [erreurs, setErreurs] = useState<string[]>([]);
  const [envoi, setEnvoi] = useState(false);

  const modifies = useMemo(() => Object.keys(brouillon), [brouillon]);

  if (!possede(moi, "admin.roles")) return <AccesRefuse />;
  if (roles.isPending || permissions.isPending) return <Chargement texte="Chargement de la matrice…" />;
  if (roles.isError) return <ErreurChargement erreur={roles.error} titre="Rôles indisponibles" onReessayer={() => void roles.refetch()} />;
  if (permissions.isError) return <ErreurChargement erreur={permissions.error} titre="Permissions indisponibles" onReessayer={() => void permissions.refetch()} />;

  const codesDe = (id: string, base: string[]) => brouillon[id] ?? base;

  const basculer = (id: string, base: string[], code: string, coche: boolean) => {
    const courant = codesDe(id, base);
    const suivant = coche ? [...courant, code] : courant.filter((c) => c !== code);
    const identique = suivant.length === base.length && suivant.every((c) => base.includes(c));
    setBrouillon((b) => {
      const { [id]: _ancien, ...reste } = b;
      return identique ? reste : { ...reste, [id]: suivant };
    });
  };

  const enregistrer = async () => {
    setEnvoi(true);
    setErreurs([]);
    const echecs: string[] = [];
    for (const id of modifies) {
      const role = roles.data.find((r) => r.id === id);
      if (!role) continue;
      try {
        await modifier.mutateAsync({ id, libelle: role.libelle, permissions: brouillon[id] });
        setBrouillon((b) => {
          const { [id]: _ok, ...reste } = b;
          return reste;
        });
      } catch (e) {
        echecs.push(`${role.libelle} : ${messageErreur(e)}`);
      }
    }
    setEnvoi(false);
    setErreurs(echecs);
    if (echecs.length === 0) toast({ ton: "succes", titre: "Habilitations enregistrées" });
  };

  return (
    <Card
      titre="Rôles et habilitations"
      description="Cochez les droits conférés par chaque rôle. Les rôles système ne sont pas modifiables."
      marge={false}
      actions={
        <>
          <Button variante="secondaire" disabled={modifies.length === 0 || envoi} onClick={() => { setBrouillon({}); setErreurs([]); }}>Annuler les modifications</Button>
          <Button chargement={envoi} disabled={modifies.length === 0} onClick={() => void enregistrer()}>Enregistrer{modifies.length ? ` (${modifies.length})` : ""}</Button>
        </>
      }
    >
      {erreurs.length > 0 && (
        <div className="flex flex-col gap-2 px-4.5 pb-3">
          {erreurs.map((e) => <AlerteErreur key={e}>{e}</AlerteErreur>)}
        </div>
      )}
      <Table legende="Matrice des habilitations par rôle">
        <thead>
          <tr>
            <Th>Rôle</Th>
            {permissions.data.map((p) => (
              <Th key={p.code} title={p.description} className="text-center">{p.libelle}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {roles.data.map((r) => {
            const codes = codesDe(r.id, r.permissions);
            return (
              <tr key={r.id}>
                <Td className="font-semibold">
                  {r.libelle} {r.est_systeme && <Badge ton="bleu">Système</Badge>} {!r.actif && <Badge ton="gris">Inactif</Badge>}
                </Td>
                {permissions.data.map((p) => (
                  <Td key={p.code} className="text-center">
                    <input
                      type="checkbox"
                      checked={codes.includes(p.code)}
                      disabled={r.est_systeme || envoi}
                      onChange={(e) => basculer(r.id, r.permissions, p.code, e.currentTarget.checked)}
                      aria-label={`${r.libelle} : ${p.libelle}`}
                      className="h-[18px] w-[18px] cursor-pointer accent-[var(--marque)] disabled:cursor-not-allowed"
                    />
                  </Td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </Table>
    </Card>
  );
}

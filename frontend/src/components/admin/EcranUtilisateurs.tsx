"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useId, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { AccesRefuse, AlerteErreur, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Button, Card, Input, LienBouton, Modal, Select, Table, Td, Th, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { appliquerErreursApi } from "@/lib/api/formulaire";
import { aplatirUnites, useHistoriqueUtilisateurs, useInviterUtilisateur, useRoles, useUnites, useUtilisateurs } from "@/lib/api/hooks/admin";
import { formatDate, formatDateHeureCourte } from "@/lib/format";
import { possede } from "@/lib/permissions";
import { z } from "@/lib/zod";
import { BadgeAuthenticator, BadgeStatutUtilisateur, Pastille } from "./statuts";

/** `/administration/utilisateurs` : liste, recherche, filtre par rôle, invitation, historique (écran 12, onglet « Utilisateurs »). */
export function EcranUtilisateurs() {
  const moi = useMoi();
  const [saisie, setSaisie] = useState("");
  const [q, setQ] = useState("");
  const [roleId, setRoleId] = useState("");
  const [invitation, setInvitation] = useState(false);
  const roles = useRoles();
  const utilisateurs = useUtilisateurs({ q, roleId });
  const historique = useHistoriqueUtilisateurs(3);

  useEffect(() => {
    const t = setTimeout(() => setQ(saisie.trim()), 300);
    return () => clearTimeout(t);
  }, [saisie]);

  const lignes = useMemo(() => utilisateurs.data?.pages.flatMap((p) => p.results) ?? [], [utilisateurs.data]);
  const total = utilisateurs.data?.pages[0]?.count ?? 0;

  if (!possede(moi, "admin.utilisateurs")) {
    return <AccesRefuse />;
  }

  return (
    <div className="flex flex-col gap-5">
      <Card marge={false}>
        <div className="flex flex-wrap items-end gap-3 px-4.5 py-4">
          <Input label="Recherche" type="search" placeholder="Nom, e-mail…" value={saisie} onChange={(e) => setSaisie(e.currentTarget.value)} classeConteneur="min-w-[200px] flex-1 basis-[240px]" />
          <Select
            label="Rôle"
            placeholder="Tous les rôles"
            value={roleId}
            onChange={(e) => setRoleId(e.currentTarget.value)}
            options={(roles.data ?? []).map((r) => ({ valeur: r.id, libelle: r.libelle }))}
            classeConteneur="min-w-[180px] flex-1 basis-[200px]"
          />
          <Button onClick={() => setInvitation(true)}>+ Inviter un utilisateur</Button>
        </div>
        {utilisateurs.isPending ? (
          <div className="px-4.5 pb-4"><Chargement texte="Chargement des utilisateurs…" /></div>
        ) : utilisateurs.isError ? (
          <div className="px-4.5 pb-4"><ErreurChargement erreur={utilisateurs.error} titre="Utilisateurs indisponibles" onReessayer={() => void utilisateurs.refetch()} /></div>
        ) : lignes.length === 0 ? (
          <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue" role="status">Aucun utilisateur ne correspond à cette recherche.</p>
        ) : (
          <Table legende={`Utilisateurs de l'établissement (${total})`}>
            <thead>
              <tr>
                <Th>Utilisateur</Th>
                <Th>Rôle</Th>
                <Th>Périmètre</Th>
                <Th>Authenticator</Th>
                <Th className="min-w-[96px] whitespace-normal">Dernière connexion</Th>
                <Th>Statut</Th>
                <Th><span className="sr-only">Action</span></Th>
              </tr>
            </thead>
            <tbody>
              {lignes.map((u) => (
                <tr key={u.id}>
                  <Td>
                    <div className="flex items-center gap-3">
                      <Pastille initiales={u.initiales} />
                      <div className="flex min-w-0 flex-col">
                        <span className="font-semibold text-encre">{u.prenom} {u.nom}</span>
                        <span className="max-w-[185px] truncate text-[13px] text-texte-attenue" title={u.email}>{u.email}</span>
                      </div>
                    </div>
                  </Td>
                  <Td retourLigne className="min-w-[100px] max-w-[140px]">{u.role_principal ?? "—"}</Td>
                  <Td retourLigne className="min-w-[90px] max-w-[120px]">{u.perimetre ?? "—"}</Td>
                  <Td><BadgeAuthenticator etat={u.authenticator} /></Td>
                  <Td mono>{formatDateHeureCourte(u.derniere_connexion)}</Td>
                  <Td><BadgeStatutUtilisateur u={u} /></Td>
                  <Td className="text-right">
                    <LienBouton href={`/administration/utilisateurs/${u.id}`} variante="secondaire" aria-label={`Modifier ${u.prenom} ${u.nom}`}>
                      Modifier
                    </LienBouton>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {utilisateurs.hasNextPage && (
          <div className="flex justify-center border-t border-ligne px-4.5 py-3">
            <Button variante="secondaire" chargement={utilisateurs.isFetchingNextPage} onClick={() => void utilisateurs.fetchNextPage()}>
              Afficher plus d&rsquo;utilisateurs
            </Button>
          </div>
        )}
      </Card>

      <Card
        titre="Historique des décisions · Utilisateurs et comptes"
        description="Les 3 dernières décisions. Rien n'est supprimé ni modifiable."
        marge={false}
      >
        {historique.isPending ? (
          <div className="px-4.5 pb-4"><Chargement /></div>
        ) : historique.isError ? (
          <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Historique indisponible.</p>
        ) : historique.data.length === 0 ? (
          <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucune décision enregistrée.</p>
        ) : (
          <Table legende="Dernières décisions sur les utilisateurs et les comptes">
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Référence</Th>
                <Th>Objet</Th>
                <Th>Décision</Th>
                <Th>Décidé par</Th>
              </tr>
            </thead>
            <tbody>
              {historique.data.map((e) => (
                <tr key={e.seq}>
                  <Td mono>{formatDate(e.horodatage)}</Td>
                  <Td mono>JRN-{String(e.seq).padStart(4, "0")}</Td>
                  <Td retourLigne className="min-w-[240px]">{e.objet_libelle}{e.detail ? <span className="block text-[13px] text-texte-attenue">{e.detail}</span> : null}</Td>
                  <Td>{e.action_libelle}</Td>
                  <Td>{e.acteur_libelle}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {invitation && <ModaleInvitation onFermer={() => setInvitation(false)} />}
    </div>
  );
}

const schemaInvitation = z.object({
  prenom: z.string().trim().min(1, "Saisissez le prénom."),
  nom: z.string().trim().min(1, "Saisissez le nom."),
  email: z.string().trim().min(1, "Saisissez l'adresse e-mail.").email("Adresse e-mail invalide."),
  role_id: z.string().min(1, "Choisissez un rôle."),
  unite_id: z.string(),
  telephone_mobile: z.string().trim().refine((v) => v === "" || /^\+[1-9][0-9]{6,14}$/.test(v), "Format international attendu (ex. +221770000000)."),
});
type ValeursInvitation = z.infer<typeof schemaInvitation>;

function ModaleInvitation({ onFermer }: { onFermer: () => void }) {
  const idForm = useId();
  const inviter = useInviterUtilisateur();
  const roles = useRoles();
  const unites = useUnites();
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);
  const form = useForm<ValeursInvitation>({
    resolver: zodResolver(schemaInvitation),
    defaultValues: { prenom: "", nom: "", email: "", role_id: "", unite_id: "", telephone_mobile: "" },
  });
  const { errors } = form.formState;

  const soumettre = form.handleSubmit(async (v) => {
    setErreur(null);
    try {
      const u = await inviter.mutateAsync({
        email: v.email.trim(),
        prenom: v.prenom,
        nom: v.nom,
        role_id: v.role_id,
        unite_id: v.unite_id || null,
        telephone_mobile: v.telephone_mobile || null,
      });
      toast({ ton: "succes", titre: "Invitation envoyée", message: `${u.prenom} ${u.nom} recevra un lien d'activation.` });
      onFermer();
    } catch (e) {
      if (estApiError(e) && e.code === "EMAIL_EXISTE") form.setError("email", { type: "serveur", message: "Cette adresse e-mail est déjà utilisée." });
      else if (estApiError(e) && e.code === "ROLE_HORS_CATALOGUE") form.setError("role_id", { type: "serveur", message: "Ce rôle n'est pas disponible dans le catalogue de l'établissement." });
      else setErreur(appliquerErreursApi(e, form.setError, ["prenom", "nom", "email", "role_id", "unite_id", "telephone_mobile"]));
    }
  });

  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!inviter.isPending}
      taille="large"
      titre="Inviter un utilisateur"
      description="La personne reçoit un lien d'activation par e-mail pour choisir son mot de passe et configurer son Authenticator."
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={inviter.isPending}>Annuler</Button>
          <Button type="submit" form={idForm} chargement={inviter.isPending}>Envoyer l&rsquo;invitation</Button>
        </>
      }
    >
      <form id={idForm} noValidate onSubmit={soumettre} className="flex flex-col gap-4">
        <AlerteErreur>{erreur ?? (estApiError(roles.error) ? roles.error.message : null)}</AlerteErreur>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label="Prénom" required autoComplete="off" erreur={errors.prenom?.message} {...form.register("prenom")} />
          <Input label="Nom" required autoComplete="off" erreur={errors.nom?.message} {...form.register("nom")} />
        </div>
        <Input label="Adresse e-mail professionnelle" type="email" required autoComplete="off" erreur={errors.email?.message} {...form.register("email")} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label="Rôle"
            required
            placeholder="Choisir un rôle…"
            options={(roles.data ?? []).filter((r) => r.actif).map((r) => ({ valeur: r.id, libelle: r.libelle }))}
            erreur={errors.role_id?.message}
            {...form.register("role_id")}
          />
          <Select
            label="Périmètre"
            placeholder="Tout l'établissement"
            options={aplatirUnites(unites.data ?? []).filter((u) => u.actif).map((u) => ({ valeur: u.id, libelle: `${"— ".repeat(u.profondeur)}${u.libelle}` }))}
            {...form.register("unite_id")}
          />
        </div>
        <Input label="Téléphone mobile" type="tel" placeholder="+221770000000" erreur={errors.telephone_mobile?.message} {...form.register("telephone_mobile")} />
      </form>
    </Modal>
  );
}


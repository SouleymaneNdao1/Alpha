"use client";

import { useState } from "react";
import { AlerteErreur, AlerteInfo, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { useMoi } from "@/components/shell/ContexteMoi";
import { Badge, Button, Card, Input, Modal, ModaleCode, Table, Td, Th, useToast } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import type { Authenticator } from "@/lib/api/hooks/auth";
import {
  useChangerMotDePasse,
  useConfirmerChangementAuthenticator,
  useDemanderChangementAuthenticator,
  useMesSessions,
  useRegenererCodesSecours,
  useRevoquerAutresSessions,
  useRevoquerSession,
  useSecurite,
  useSignalerTelephonePerdu,
  type SessionMoi,
} from "@/lib/api/hooks/compte";
import { formatDate, formatDateHeureCourte } from "@/lib/format";
import { messageErreur } from "@/lib/compte/messages";
import { cn } from "@/lib/cn";
import { CodesSecoursAffiches } from "./CodesSecoursAffiches";

type Fenetre = null | "mot-de-passe" | "authenticator" | "codes" | "perdu";

/** Onglet « Sécurité » : mot de passe, Authenticator, codes de secours, téléphone perdu, sessions. */
export function OngletSecurite() {
  const securite = useSecurite();
  const [fenetre, setFenetre] = useState<Fenetre>(null);
  const fermer = () => setFenetre(null);

  if (securite.isPending) return <Chargement texte="Chargement de vos paramètres de sécurité…" />;
  if (securite.isError) return <ErreurChargement erreur={securite.error} titre="Sécurité indisponible" onReessayer={() => void securite.refetch()} />;
  const s = securite.data;
  const auth = s.authenticator;

  return (
    <div className="flex flex-col gap-5">
      {s.signalement && s.signalement.statut === "OUVERT" && (
        <AlerteInfo>
          Un signalement « téléphone perdu » est en cours depuis le {formatDate(s.signalement.signale_le)} : votre signature est bloquée jusqu&rsquo;à la vérification de votre identité par un administrateur.
        </AlerteInfo>
      )}
      {s.mot_de_passe_expire && <AlerteErreur>Votre mot de passe a expiré : changez-le pour continuer à utiliser ALPHA.</AlerteErreur>}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card titre="Mot de passe" description={s.mdp_modifie_le ? `Dernière modification le ${formatDate(s.mdp_modifie_le)}.` : "Jamais modifié depuis l'activation."}>
          <p className="m-0 mb-3 text-[14px] text-texte-2">Le changement exige votre mot de passe actuel et un code de votre application Authenticator. Vos autres appareils seront déconnectés.</p>
          <Button variante="secondaire" onClick={() => setFenetre("mot-de-passe")}>
            Changer le mot de passe
          </Button>
        </Card>

        <Card titre="Application Authenticator" description={auth.libelle || undefined}>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-[14px] text-texte-2">
            <Badge ton={auth.statut === "ACTIVE" ? "vert" : auth.statut === "SUSPENDUE" ? "rouge" : "ambre"} point>
              {auth.statut === "ACTIVE" ? "Activée" : auth.statut === "SUSPENDUE" ? "Suspendue" : "Non configurée"}
            </Badge>
            {auth.active_le && <span>depuis le {formatDate(auth.active_le)}</span>}
          </div>
          <Button variante="secondaire" disabled={auth.statut !== "ACTIVE"} onClick={() => setFenetre("authenticator")}>
            Changer de téléphone
          </Button>
        </Card>

        <Card titre="Codes de secours" description="Utilisables une seule fois si vous n'avez plus votre téléphone.">
          <p className="m-0 mb-3 text-[14px] text-texte-2">
            <span className="font-mono text-[16px] font-semibold text-encre">{s.codes_secours_restants} sur 10</span> restants
          </p>
          <Button variante="secondaire" disabled={auth.statut !== "ACTIVE"} onClick={() => setFenetre("codes")}>
            Régénérer
          </Button>
        </Card>

        <Card titre="J'ai perdu mon téléphone" description="Bloque votre signature et ferme toutes vos sessions.">
          <p className="m-0 mb-3 text-[14px] text-texte-2">Un administrateur vérifiera votre identité avant de réinitialiser votre application Authenticator.</p>
          <Button variante="secondaire" className="!border-danger-texte !text-danger-texte" disabled={s.signalement?.statut === "OUVERT"} onClick={() => setFenetre("perdu")}>
            J&rsquo;ai perdu mon téléphone
          </Button>
        </Card>
      </div>

      <TableauSessions />

      {fenetre === "mot-de-passe" && <ModaleMotDePasse onFermer={fermer} />}
      {fenetre === "authenticator" && <ModaleChangementAuthenticator onFermer={fermer} />}
      {fenetre === "codes" && <ModaleCodesSecours onFermer={fermer} />}
      {fenetre === "perdu" && <ModaleTelephonePerdu onFermer={fermer} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mot de passe
// ---------------------------------------------------------------------------

function categories(v: string): number {
  return [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length;
}

function ModaleMotDePasse({ onFermer }: { onFermer: () => void }) {
  const changer = useChangerMotDePasse();
  const { toast } = useToast();
  const [actuel, setActuel] = useState("");
  const [nouveau, setNouveau] = useState("");
  const [confirmation, setConfirmation] = useState("");

  const longueurOk = nouveau.length >= 12;
  const categoriesOk = categories(nouveau) >= 3;
  const identiques = nouveau !== "" && nouveau === confirmation;
  const erreurConfirmation = confirmation !== "" && nouveau !== confirmation ? "Les deux mots de passe ne sont pas identiques." : undefined;

  return (
    <ModaleCode
      titre="Changer le mot de passe"
      description="Saisissez votre mot de passe actuel, le nouveau, puis un code de votre application Authenticator."
      libelleAction="Changer le mot de passe"
      peutConfirmer={actuel !== "" && longueurOk && categoriesOk && identiques}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        await changer.mutateAsync({ actuel, nouveau, confirmation, code });
        toast({ ton: "succes", titre: "Mot de passe modifié", message: "Vos autres appareils ont été déconnectés." });
        onFermer();
      }}
    >
      <Input label="Mot de passe actuel" type="password" autoComplete="current-password" value={actuel} onChange={(e) => setActuel(e.currentTarget.value)} />
      <Input label="Nouveau mot de passe" type="password" autoComplete="new-password" value={nouveau} onChange={(e) => setNouveau(e.currentTarget.value)} aria-describedby="regles-nouveau-mdp" />
      <Input label="Confirmer le mot de passe" type="password" autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.currentTarget.value)} erreur={erreurConfirmation} />
      <ul id="regles-nouveau-mdp" aria-live="polite" className="m-0 flex list-none flex-col gap-1 p-0">
        {[
          { ok: longueurOk, texte: "12 caractères minimum" },
          { ok: categoriesOk, texte: "3 types parmi : minuscule, majuscule, chiffre, symbole" },
        ].map((r) => (
          <li key={r.texte} className={cn("flex items-center gap-2 text-[13px]", r.ok ? "text-succes" : "text-texte-attenue")}>
            <span aria-hidden="true" className="inline-block w-3 text-center font-semibold">
              {r.ok ? "✓" : "·"}
            </span>
            {r.texte}
            <span className="sr-only">{r.ok ? " : respecté" : " : pas encore respecté"}</span>
          </li>
        ))}
      </ul>
    </ModaleCode>
  );
}

// ---------------------------------------------------------------------------
// Changement d'Authenticator (deux étapes)
// ---------------------------------------------------------------------------

function ModaleChangementAuthenticator({ onFermer }: { onFermer: () => void }) {
  const demander = useDemanderChangementAuthenticator();
  const confirmer = useConfirmerChangementAuthenticator();
  const { toast } = useToast();
  const [nouvelle, setNouvelle] = useState<Authenticator | null>(null);
  const [retour, setRetour] = useState(0);

  if (!nouvelle) {
    return (
      <ModaleCode
        titre="Changer de téléphone"
        description="Étape 1 sur 2 : confirmez avec le code de l'application actuelle. L'ancienne application reste active jusqu'à la fin du changement."
        libelleAction="Continuer"
        labelCode="Code de l'application actuelle"
        onFermer={onFermer}
        key={`etape1-${retour}`}
        onConfirmer={async (code) => setNouvelle(await demander.mutateAsync(code))}
      />
    );
  }

  return (
    <ModaleNouvelleApplication
      authenticator={nouvelle}
      onFermer={onFermer}
      onConfirmer={async (code) => {
        try {
          await confirmer.mutateAsync(code);
        } catch (e) {
          if (estApiError(e) && e.code === "AUCUN_CHANGEMENT_EN_COURS") {
            setNouvelle(null);
            setRetour((n) => n + 1);
          }
          throw e;
        }
        toast({ ton: "succes", titre: "Nouveau téléphone activé", message: "Vos codes de secours restent valables." });
        onFermer();
      }}
    />
  );
}

function ModaleNouvelleApplication({ authenticator, onFermer, onConfirmer }: { authenticator: Authenticator; onFermer: () => void; onConfirmer: (code: string) => Promise<unknown> }) {
  const { toast } = useToast();
  const copier = async () => {
    try {
      await navigator.clipboard.writeText(authenticator.secret_affichable.replace(/\s/g, ""));
      toast({ ton: "succes", titre: "Clé copiée" });
    } catch {
      toast({ ton: "erreur", titre: "Copie impossible", message: "Saisissez la clé à la main." });
    }
  };
  return (
    <ModaleCode
      titre="Changer de téléphone"
      description="Étape 2 sur 2 : scannez le QR code avec la nouvelle application, puis saisissez le premier code affiché."
      libelleAction="Activer le nouveau téléphone"
      labelCode="Premier code de la nouvelle application"
      onFermer={onFermer}
      onConfirmer={onConfirmer}
    >
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
        {/* SVG du backend affiché en <img> (data URI) : aucun script ne peut s'exécuter. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(authenticator.qr_svg)}`}
          alt={`QR code de la nouvelle application (compte ${authenticator.compte || authenticator.emetteur})`}
          width={160}
          height={160}
          className="h-40 w-40 flex-none rounded-champ border border-bordure bg-white p-2"
        />
        <div className="flex min-w-0 flex-col gap-2 text-[14px]">
          <p className="m-0 font-semibold text-texte-2">Vous ne pouvez pas scanner ?</p>
          <code aria-label="Clé secrète" className="block select-all break-words rounded-champ bg-entete-tableau px-3 py-2 font-mono text-[15px] font-semibold tracking-[0.04em] text-encre">
            {authenticator.secret_affichable}
          </code>
          <div>
            <Button variante="secondaire" onClick={copier}>
              Copier la clé
            </Button>
          </div>
        </div>
      </div>
    </ModaleCode>
  );
}

// ---------------------------------------------------------------------------
// Codes de secours
// ---------------------------------------------------------------------------

function ModaleCodesSecours({ onFermer }: { onFermer: () => void }) {
  const regenerer = useRegenererCodesSecours();
  const moi = useMoi();
  const [codes, setCodes] = useState<string[] | null>(null);
  const [conserves, setConserves] = useState(false);

  if (!codes) {
    return (
      <ModaleCode
        titre="Régénérer les codes de secours"
        description="Les 10 anciens codes seront invalidés. Confirmez avec un code de votre application Authenticator."
        libelleAction="Régénérer"
        onFermer={onFermer}
        onConfirmer={async (code) => setCodes((await regenerer.mutateAsync(code)).codes_secours)}
      />
    );
  }

  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={conserves}
      titre="Vos nouveaux codes de secours"
      description="Ils ne seront plus affichés. Chaque code ne sert qu'une seule fois."
      pied={
        <Button onClick={onFermer} disabled={!conserves}>
          Terminer
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <CodesSecoursAffiches codes={codes} etablissement={moi.etablissement?.raison_sociale ?? ""} />
        <label className="flex cursor-pointer items-start gap-2.5 text-[14px] font-semibold text-texte-2">
          <input type="checkbox" checked={conserves} onChange={(e) => setConserves(e.currentTarget.checked)} className="mt-0.5 h-[18px] w-[18px] flex-none accent-[var(--marque)]" />
          J&rsquo;ai conservé mes codes
        </label>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Téléphone perdu
// ---------------------------------------------------------------------------

function ModaleTelephonePerdu({ onFermer }: { onFermer: () => void }) {
  const signaler = useSignalerTelephonePerdu();
  const [erreur, setErreur] = useState<string | null>(null);
  const [confirme, setConfirme] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const envoyer = async () => {
    setErreur(null);
    try {
      const r = await signaler.mutateAsync();
      setMessage(r.message);
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };

  if (message) {
    return (
      <Modal
        ouvert
        onFermer={() => window.location.assign("/connexion?motif=deconnexion")}
        titre="Signalement enregistré"
        pied={<Button onClick={() => window.location.assign("/connexion?motif=deconnexion")}>Retour à la connexion</Button>}
      >
        <p className="m-0 text-[15px] text-texte-2">{message}</p>
      </Modal>
    );
  }

  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!signaler.isPending}
      titre="J'ai perdu mon téléphone"
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={signaler.isPending}>
            Annuler
          </Button>
          <Button chargement={signaler.isPending} disabled={!confirme} className="!bg-danger-texte hover:!bg-danger-texte" onClick={envoyer}>
            Signaler la perte
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[14px] text-texte-2">
        <AlerteErreur>{erreur}</AlerteErreur>
        <p className="m-0">En confirmant :</p>
        <ul className="m-0 flex flex-col gap-1 pl-5">
          <li>votre signature est bloquée ;</li>
          <li>votre application Authenticator est suspendue ;</li>
          <li>toutes vos sessions sont fermées, y compris celle-ci ;</li>
          <li>un administrateur vérifie votre identité avant de réinitialiser votre accès.</li>
        </ul>
        <label className="flex cursor-pointer items-start gap-2.5 font-semibold">
          <input type="checkbox" checked={confirme} onChange={(e) => setConfirme(e.currentTarget.checked)} className="mt-0.5 h-[18px] w-[18px] flex-none accent-[var(--marque)]" />
          Je confirme avoir perdu mon téléphone
        </label>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Appareils et sessions
// ---------------------------------------------------------------------------

function TableauSessions() {
  const sessions = useMesSessions();
  const revoquer = useRevoquerSession();
  const autres = useRevoquerAutresSessions();
  const { toast } = useToast();
  const [erreur, setErreur] = useState<string | null>(null);

  const deconnecter = async (s: SessionMoi) => {
    setErreur(null);
    try {
      await revoquer.mutateAsync(s.id);
      toast({ ton: "succes", titre: "Session fermée", message: s.appareil });
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };
  const deconnecterAutres = async () => {
    setErreur(null);
    try {
      const r = await autres.mutateAsync();
      toast({ ton: "succes", titre: r.revoquees > 0 ? `${r.revoquees} session${r.revoquees > 1 ? "s" : ""} fermée${r.revoquees > 1 ? "s" : ""}` : "Aucune autre session active" });
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };

  const liste = sessions.data ?? [];
  return (
    <Card
      titre="Appareils et sessions"
      marge={false}
      actions={
        <Button variante="secondaire" chargement={autres.isPending} disabled={liste.filter((s) => !s.courante).length === 0} onClick={deconnecterAutres}>
          Déconnecter les autres appareils
        </Button>
      }
    >
      {erreur && (
        <div className="px-4.5 pb-3">
          <AlerteErreur>{erreur}</AlerteErreur>
        </div>
      )}
      {sessions.isPending ? (
        <div className="px-4.5 pb-4">
          <Chargement texte="Chargement des sessions…" />
        </div>
      ) : sessions.isError ? (
        <div className="px-4.5 pb-4">
          <ErreurChargement erreur={sessions.error} titre="Sessions indisponibles" onReessayer={() => void sessions.refetch()} />
        </div>
      ) : (
        <Table legende="Appareils et sessions actives">
          <thead>
            <tr>
              <Th>Appareil</Th>
              <Th>Adresse IP</Th>
              <Th>Ouverte le</Th>
              <Th>Dernière activité</Th>
              <Th>
                <span className="sr-only">Action</span>
              </Th>
            </tr>
          </thead>
          <tbody>
            {liste.map((s) => (
              <tr key={s.id}>
                <Td retourLigne>
                  <span className="font-semibold">{s.appareil}</span> {s.courante && <Badge ton="bleu">Cette session</Badge>}
                </Td>
                <Td mono>{s.ip ?? "—"}</Td>
                <Td mono>{formatDateHeureCourte(s.cree_le)}</Td>
                <Td mono>{formatDateHeureCourte(s.derniere_activite)}</Td>
                <Td className="text-right">
                  {!s.courante && (
                    <Button variante="secondaire" disabled={revoquer.isPending} onClick={() => void deconnecter(s)} aria-label={`Déconnecter : ${s.appareil}`}>
                      Déconnecter
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

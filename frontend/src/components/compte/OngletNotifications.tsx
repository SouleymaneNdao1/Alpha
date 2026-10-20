"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlerteErreur, AlerteInfo, Chargement, ErreurChargement } from "@/components/shell/Etats";
import { Button, Card, Input, Interrupteur, useToast } from "@/components/ui";
import { useEnregistrerPreferences, usePreferencesNotification, type PreferencesNotification } from "@/lib/api/hooks/compte";
import { useMarquerLue, useNotifications, useToutMarquerLu } from "@/lib/api/hooks/notifications";
import { formatDateHeureCourte } from "@/lib/format";
import { messageErreur } from "@/lib/compte/messages";
import { cn } from "@/lib/cn";

/** Onglet « Notifications » : préférences (`/moi/preferences-notification`) et notifications reçues. */
export function OngletNotifications() {
  return (
    <div className="flex flex-col gap-5">
      <Preferences />
      <ListeNotifications />
    </div>
  );
}

function Preferences() {
  const prefs = usePreferencesNotification();
  const enregistrer = useEnregistrerPreferences();
  const { toast } = useToast();
  const [valeurs, setValeurs] = useState<PreferencesNotification | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    if (prefs.data) setValeurs((v) => v ?? { ...prefs.data });
  }, [prefs.data]);

  if (prefs.isPending) return <Chargement texte="Chargement de vos préférences…" />;
  if (prefs.isError) return <ErreurChargement erreur={prefs.error} titre="Préférences indisponibles" onReessayer={() => void prefs.refetch()} />;
  const v = valeurs ?? prefs.data;
  const modifie = JSON.stringify(v) !== JSON.stringify(prefs.data);
  const maj = (champ: Partial<PreferencesNotification>) => setValeurs({ ...v, ...champ });

  const sauver = async () => {
    setErreur(null);
    try {
      const p = await enregistrer.mutateAsync({ ...v, heure_resume: v.heure_resume.slice(0, 5) });
      setValeurs({ ...p });
      toast({ ton: "succes", titre: "Préférences enregistrées" });
    } catch (e) {
      setErreur(messageErreur(e));
    }
  };

  return (
    <Card titre="Préférences de notification" description="Choisissez comment ALPHA vous prévient.">
      <div className="flex max-w-[640px] flex-col gap-1">
        <AlerteErreur>{erreur}</AlerteErreur>
        <div className="divide-y divide-ligne">
          <Interrupteur label="E-mail" actif={v.email} onChange={(a) => maj({ email: a })} />
          <Interrupteur label="Téléphone (notification)" actif={v.push} onChange={(a) => maj({ push: a })} />
          <Interrupteur label="SMS" actif={v.sms} onChange={(a) => maj({ sms: a })} />
          <Interrupteur label="Résumé quotidien" description="Un seul e-mail par jour avec ce qui vous attend." actif={v.resume_quotidien} onChange={(a) => maj({ resume_quotidien: a })} />
        </div>
        <div className="max-w-[200px] pt-2">
          <Input
            label="Heure du résumé"
            type="time"
            value={v.heure_resume.slice(0, 5)}
            disabled={!v.resume_quotidien}
            onChange={(e) => maj({ heure_resume: e.currentTarget.value })}
          />
        </div>
        <p className="m-0 pt-3 text-[13px] text-texte-attenue">Les alertes de sécurité sont toujours envoyées par e-mail.</p>
        <div className="pt-2">
          <AlerteInfo ton="bleu">Envoi par SMS et notification mobile disponible prochainement : vos choix sont enregistrés dès maintenant.</AlerteInfo>
        </div>
        <div className="pt-3">
          <Button chargement={enregistrer.isPending} disabled={!modifie} onClick={sauver}>
            Enregistrer
          </Button>
        </div>
      </div>
    </Card>
  );
}

function ListeNotifications() {
  const liste = useNotifications({ taille: 25 });
  const lue = useMarquerLue();
  const toutLu = useToutMarquerLu();
  return (
    <Card
      titre="Mes notifications"
      marge={false}
      actions={
        <Button variante="secondaire" chargement={toutLu.isPending} disabled={!liste.data || liste.data.non_lues === 0} onClick={() => toutLu.mutate()}>
          Tout marquer comme lu
        </Button>
      }
    >
      {liste.isPending ? (
        <div className="px-4.5 pb-4"><Chargement /></div>
      ) : liste.isError ? (
        <div className="px-4.5 pb-4"><ErreurChargement erreur={liste.error} titre="Notifications indisponibles" onReessayer={() => void liste.refetch()} /></div>
      ) : liste.data.results.length === 0 ? (
        <p className="m-0 px-4.5 pb-4 text-[14px] text-texte-attenue">Aucune notification pour le moment.</p>
      ) : (
        <ul className="m-0 list-none p-0">
          {liste.data.results.map((n) => (
            <li key={n.id} className={cn("flex flex-wrap items-start gap-3 border-t border-ligne px-4.5 py-3", !n.lue_le && "bg-entete-tableau")}>
              <div className="flex min-w-0 flex-1 basis-[240px] flex-col gap-0.5">
                <p className={cn("m-0 text-[14px] text-encre", !n.lue_le && "font-semibold")}>
                  {!n.lue_le && <span className="sr-only">Non lue : </span>}
                  {n.lien ? <Link href={n.lien} onClick={() => !n.lue_le && lue.mutate(n.id)}>{n.titre}</Link> : n.titre}
                </p>
                {n.corps && <p className="m-0 text-[13px] text-texte-attenue">{n.corps}</p>}
              </div>
              <span className="font-mono text-[12px] text-texte-attenue">{formatDateHeureCourte(n.cree_le)}</span>
              {!n.lue_le && (
                <Button variante="secondaire" onClick={() => lue.mutate(n.id)} aria-label={`Marquer comme lue : ${n.titre}`}>
                  Marquer comme lue
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

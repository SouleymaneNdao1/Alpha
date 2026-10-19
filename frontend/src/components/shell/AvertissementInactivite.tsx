"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Modal } from "@/components/ui";
import { api } from "@/lib/api/client";
import { CLE_SESSION, CHEMINS_AUTH, useDeconnexion, type Moi } from "@/lib/api/hooks/auth";

/** Délai d'avertissement avant l'expiration (architecture § 4.8 : 60 s). */
export const AVERTISSEMENT_MS = 60_000;
/** Les actions de l'utilisateur sont relayées au serveur (GET /auth/session) au plus toutes les 20 s. */
const RELAI_MS = 20_000;
const EVENEMENTS = ["pointerdown", "keydown", "wheel", "touchstart", "scroll"] as const;

/**
 * Suit l'inactivité de l'utilisateur. Le serveur révoque la session après
 * `inactivite_session_min` minutes sans appel (hors appels de fond) : le front
 * relaie donc les actions de l'utilisateur et affiche un avertissement 60 s
 * avant l'échéance. « Rester connecté » = `GET /auth/session` (sans
 * `X-Alpha-Fond`). À l'échéance, retour à la connexion (« Votre session a expiré »).
 */
export function AvertissementInactivite({ minutes }: { minutes: number }) {
  const client = useQueryClient();
  const deconnexion = useDeconnexion();
  const limite = Math.max(minutes, 1) * 60_000;
  const avertissement = Math.min(AVERTISSEMENT_MS, limite / 2);
  const derniereAction = useRef(Date.now());
  const dernierRelai = useRef(Date.now());
  const affiche = useRef(false);
  const [reste, setReste] = useState<number | null>(null);

  const relayer = useCallback(async () => {
    dernierRelai.current = Date.now();
    try {
      // Pas de `fond` : cet appel prolonge la session côté serveur.
      const moi = await api.get<Moi>(CHEMINS_AUTH.session);
      client.setQueryData(CLE_SESSION, moi);
    } catch {
      // 401 : le client d'API redirige vers la connexion ; autre erreur : on réessaiera à la prochaine action.
    }
  }, [client]);

  const expirer = useCallback(() => {
    client.clear();
    const { pathname, search } = window.location;
    window.location.assign(`/connexion?suivant=${encodeURIComponent(pathname + search)}&motif=expiree`);
  }, [client]);

  useEffect(() => {
    const surAction = () => {
      if (affiche.current) return; // l'avertissement n'est levé que par « Rester connecté »
      const maintenant = Date.now();
      derniereAction.current = maintenant;
      if (maintenant - dernierRelai.current > RELAI_MS) void relayer();
    };
    for (const e of EVENEMENTS) window.addEventListener(e, surAction, { passive: true, capture: true });
    const verifier = () => {
      const restant = derniereAction.current + limite - Date.now();
      if (restant <= 0) return expirer();
      const visible = restant <= avertissement;
      affiche.current = visible;
      setReste(visible ? restant : null);
    };
    const minuteur = setInterval(verifier, 1000);
    return () => {
      clearInterval(minuteur);
      for (const e of EVENEMENTS) window.removeEventListener(e, surAction, { capture: true });
    };
  }, [limite, avertissement, relayer, expirer]);

  const resterConnecte = async () => {
    derniereAction.current = Date.now();
    affiche.current = false;
    setReste(null);
    await relayer();
  };

  const secondes = reste === null ? 0 : Math.max(Math.ceil(reste / 1000), 0);
  return (
    <Modal
      ouvert={reste !== null}
      onFermer={() => void resterConnecte()}
      fermable={false}
      titre="Votre session va expirer"
      description="Par sécurité, une session inactive est fermée automatiquement."
      pied={
        <>
          <Button
            variante="secondaire"
            chargement={deconnexion.isPending}
            onClick={() => deconnexion.mutate(undefined, { onSettled: () => window.location.assign("/connexion?motif=deconnexion") })}
          >
            Se déconnecter
          </Button>
          <Button onClick={() => void resterConnecte()}>Rester connecté</Button>
        </>
      }
    >
      <p className="m-0 text-[15px] text-texte-2" role="timer" aria-live="off">
        Déconnexion dans <strong className="font-mono">{secondes} s</strong> sans action de votre part.
      </p>
    </Modal>
  );
}

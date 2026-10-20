"use client";

import { useId, useState, type ReactNode } from "react";
import { estErreurCode, messageErreur } from "@/lib/compte/messages";
import { Button, type VarianteBouton } from "./Button";
import { Modal } from "./Modal";
import { OtpInput } from "./OtpInput";

export interface ModaleCodeProps {
  titre: ReactNode;
  description?: ReactNode;
  /** Libellé du bouton de confirmation (ex. « Changer le mot de passe »). */
  libelleAction: string;
  variante?: VarianteBouton;
  /** Champs propres à l'action, affichés au-dessus du code. */
  children?: ReactNode;
  /** `false` tant que les champs propres sont incomplets ou invalides. */
  peutConfirmer?: boolean;
  /**
   * Envoie l'action avec le code saisi. Doit lever l'`ApiError` en cas d'échec ;
   * en cas de succès, l'appelant ferme la fenêtre (il la démonte).
   */
  onConfirmer: (code: string) => Promise<unknown>;
  onFermer: () => void;
  taille?: "normal" | "large";
  labelCode?: string;
}

/**
 * Fenêtre de confirmation par code TOTP (« step-up », architecture § 4.9) : champs
 * propres à l'action puis `OtpInput`. À monter seulement quand elle est ouverte :
 * le code et l'erreur repartent de zéro à chaque ouverture. Le code n'est jamais conservé.
 */
export function ModaleCode({
  titre,
  description,
  libelleAction,
  variante = "primaire",
  children,
  peutConfirmer = true,
  onConfirmer,
  onFermer,
  taille,
  labelCode = "Code de votre application Authenticator",
}: ModaleCodeProps) {
  const idForm = useId();
  const [code, setCode] = useState("");
  const [erreurCode, setErreurCode] = useState<string | undefined>();
  const [erreur, setErreur] = useState<string | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [cle, setCle] = useState(0);

  const soumettre = async () => {
    if (code.length !== 6 || !peutConfirmer || envoi) return;
    setErreur(null);
    setErreurCode(undefined);
    setEnvoi(true);
    try {
      await onConfirmer(code);
    } catch (e) {
      if (estErreurCode(e)) setErreurCode(messageErreur(e));
      else setErreur(messageErreur(e));
      // Un code est à usage unique : on repart d'une saisie vide.
      setCode("");
      setCle((c) => c + 1);
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <Modal
      ouvert
      onFermer={onFermer}
      fermable={!envoi}
      taille={taille}
      titre={titre}
      description={description}
      pied={
        <>
          <Button variante="secondaire" onClick={onFermer} disabled={envoi}>
            Annuler
          </Button>
          <Button type="submit" form={idForm} variante={variante} chargement={envoi} disabled={code.length !== 6 || !peutConfirmer}>
            {libelleAction}
          </Button>
        </>
      }
    >
      <form
        id={idForm}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void soumettre();
        }}
        className="flex flex-col gap-4"
      >
        {erreur && (
          <p role="alert" className="m-0 rounded-champ border border-badge-rouge-fond bg-badge-rouge-fond px-3 py-2.5 text-[14px] text-badge-rouge-texte">
            {erreur}
          </p>
        )}
        {children}
        <OtpInput key={cle} valeur={code} onChange={setCode} label={labelCode} erreur={erreurCode} desactive={envoi} autoFocus={!children} />
      </form>
    </Modal>
  );
}

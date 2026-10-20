"use client";

import { Button, useToast } from "@/components/ui";

/**
 * Les 10 codes de secours, affichés UNE SEULE FOIS : copie dans le presse-papiers
 * et téléchargement en fichier texte. L'appelant impose la case « J'ai conservé mes codes ».
 */
export function CodesSecoursAffiches({ codes, etablissement }: { codes: string[]; etablissement: string }) {
  const { toast } = useToast();
  const contenu = () =>
    ["ALPHA — codes de secours", etablissement, `Générés le ${new Date().toLocaleString("fr-SN")}`, "Chaque code ne sert qu'une seule fois. Conservez-les en lieu sûr.", "", ...codes, ""].join("\n");

  const copier = async () => {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast({ ton: "succes", titre: "Codes copiés" });
    } catch {
      toast({ ton: "erreur", titre: "Copie impossible", message: "Utilisez « Télécharger » ou notez les codes." });
    }
  };

  const telecharger = () => {
    const url = URL.createObjectURL(new Blob([contenu()], { type: "text/plain;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "alpha-codes-de-secours.txt";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  return (
    <div className="flex flex-col gap-3">
      <ul aria-label="Codes de secours" className="m-0 grid list-none grid-cols-2 gap-2 rounded-champ border border-bordure bg-entete-tableau p-3.5">
        {codes.map((c) => (
          <li key={c} className="text-center font-mono text-[15px] font-semibold tracking-[0.06em] text-encre">
            {c}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button variante="secondaire" onClick={copier}>
          Copier
        </Button>
        <Button variante="secondaire" onClick={telecharger}>
          Télécharger
        </Button>
      </div>
    </div>
  );
}

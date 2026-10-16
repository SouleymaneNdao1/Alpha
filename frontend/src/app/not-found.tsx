import { LienBouton } from "@/components/ui";

export default function PageIntrouvable() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[560px] flex-col justify-center gap-4 px-4 py-12">
      <p className="font-mono text-[13px] font-semibold text-texte-attenue">Erreur 404</p>
      <h1 className="text-titre-page">Page introuvable</h1>
      <p className="text-[15px] text-texte-attenue">L&apos;adresse demandée n&apos;existe pas ou n&apos;est plus disponible.</p>
      <div>
        <LienBouton href="/" variante="secondaire">
          Retour à l&apos;accueil
        </LienBouton>
      </div>
    </main>
  );
}

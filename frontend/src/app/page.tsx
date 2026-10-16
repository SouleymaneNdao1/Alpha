import { LienBouton } from "@/components/ui";

/**
 * Page d'accueil provisoire (F1). L'architecture (§ 7.1) prévoit une
 * redirection vers `/a-traiter` (ou `/console` pour un super-admin) : elle sera
 * posée avec la coquille et la garde de session (F2, F3).
 */
export default function Accueil() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[560px] flex-col justify-center gap-5 px-4 py-12">
      <p className="font-mono text-[13px] font-semibold tracking-[.12em] text-alerte-texte">ALPHA</p>
      <h1 className="text-titre-page">Chaque décision, formalisée, tracée et vérifiable.</h1>
      <p className="text-[15px] text-texte-attenue">
        Socle technique du sprint 1. Les écrans de connexion et l&apos;espace « À traiter » arrivent avec les tâches suivantes.
      </p>
      <div>
        <LienBouton href="/demo">Voir la bibliothèque de composants</LienBouton>
      </div>
    </main>
  );
}

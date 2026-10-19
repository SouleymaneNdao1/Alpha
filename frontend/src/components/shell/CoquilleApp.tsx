"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Button, Card } from "@/components/ui";
import { Dialogue } from "@/components/ui/Dialogue";
import { estApiError } from "@/lib/api/erreurs";
import { useSession } from "@/lib/api/hooks/auth";
import { useNotificationsNonLues } from "@/lib/api/hooks/notifications";
import { useCompteursTaches } from "@/lib/api/hooks/taches";
import { AvertissementInactivite } from "./AvertissementInactivite";
import { Bandeau } from "./Bandeau";
import { FournisseurMoi } from "./ContexteMoi";
import { MenuLateral } from "./MenuLateral";

/**
 * Coquille des écrans `(app)` : garde de session (`GET /auth/session`), barre
 * latérale construite depuis Moi, bandeau, avertissement d'inactivité, tiroir
 * sur mobile. Rien n'est affiché de l'application sans session valide.
 */
export function CoquilleApp({ children }: { children: ReactNode }) {
  const session = useSession();
  const router = useRouter();
  const chemin = usePathname();
  const [tiroir, setTiroir] = useState(false);

  const expiree = session.isError && estApiError(session.error) && session.error.status === 401;
  useEffect(() => {
    if (!expiree) return;
    const motif = estApiError(session.error) && session.error.code === "SESSION_EXPIREE" ? "&motif=expiree" : "";
    router.replace(`/connexion?suivant=${encodeURIComponent(window.location.pathname + window.location.search)}${motif}`);
  }, [expiree, session.error, router]);

  // Le tiroir se referme dès qu'on change d'écran.
  useEffect(() => setTiroir(false), [chemin]);

  const moi = session.data;
  const compteurs = useCompteursTaches({ active: !!moi && !moi.est_super_admin });
  const notifications = useNotificationsNonLues({ active: !!moi && !moi.est_super_admin });

  if (!moi) {
    return (
      <div className="flex min-h-dvh items-center justify-center p-4">
        {session.isError && !expiree ? (
          <Card className="w-full max-w-[460px]" titre="Session indisponible">
            <p className="m-0 text-[15px] text-texte-2" role="alert">
              {estApiError(session.error) ? session.error.message : "Impossible de joindre le serveur."}
            </p>
            <div className="mt-3">
              <Button onClick={() => void session.refetch()}>Réessayer</Button>
            </div>
          </Card>
        ) : (
          <p className="m-0 text-[15px] text-texte-attenue" role="status">
            Chargement de votre session…
          </p>
        )}
      </div>
    );
  }

  const menu = (onNavigation?: () => void) => <MenuLateral moi={moi} compteurTaches={compteurs.data?.total} onNavigation={onNavigation} />;

  return (
    <FournisseurMoi value={moi}>
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-champ focus:bg-surface focus:px-3 focus:py-2"
      >
        Aller au contenu
      </a>
      <div className="min-h-dvh md:flex">
        <aside aria-label="Barre latérale" className="sticky top-0 hidden h-dvh w-[260px] shrink-0 overflow-y-auto bg-encre md:block">
          {menu()}
        </aside>
        <div className="flex min-w-0 flex-1 flex-col gap-5 px-4 pb-10 pt-4 md:px-8">
          <Bandeau moi={moi} nonLues={notifications.data} onMenu={() => setTiroir(true)} menuOuvert={tiroir} />
          <main id="contenu" tabIndex={-1} className="flex min-w-0 flex-col gap-5 outline-none">
            {children}
          </main>
        </div>
      </div>
      <Dialogue
        ouvert={tiroir}
        onFermer={() => setTiroir(false)}
        titre="Menu"
        classeDialogue="fixed inset-y-0 left-0 right-auto m-0 h-dvh max-h-none w-[min(300px,85vw)] rounded-none border-y-0 border-l-0"
        classeCorps="!p-0 !bg-encre"
      >
        <div id="menu-mobile">{menu(() => setTiroir(false))}</div>
      </Dialogue>
      <AvertissementInactivite minutes={moi.inactivite_session_min} />
    </FournisseurMoi>
  );
}

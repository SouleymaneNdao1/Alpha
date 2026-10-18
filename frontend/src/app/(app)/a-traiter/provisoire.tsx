"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Button, Card } from "@/components/ui";
import { estApiError } from "@/lib/api/erreurs";
import { useDeconnexion, useSession } from "@/lib/api/hooks/auth";

/**
 * « À traiter » provisoire (F3/F4) : confirme la session ouverte. Remplacé par
 * l'écran 01c en F5 (la coquille et la garde de session arrivent en F2).
 */
export function ATraiterProvisoire() {
  const session = useSession();
  const deconnexion = useDeconnexion();
  const router = useRouter();

  useEffect(() => {
    if (session.isError && estApiError(session.error) && session.error.status === 401) {
      const motif = session.error.code === "SESSION_EXPIREE" ? "&motif=expiree" : "";
      router.replace(`/connexion?suivant=${encodeURIComponent("/a-traiter")}${motif}`);
    }
  }, [session.isError, session.error, router]);

  const moi = session.data;
  return (
    <main className="mx-auto flex min-h-dvh max-w-[760px] flex-col gap-5 px-4 py-10">
      <h1 className="m-0 text-titre-page">{moi ? `Bonjour ${moi.prenom}, voici ce qui vous attend` : "À traiter"}</h1>
      {moi?.etablissement && <p className="m-0 text-[15px] text-texte-attenue">{moi.etablissement.raison_sociale}</p>}
      <Card>
        <p className="m-0 text-[15px] text-texte-2" role="status">
          {session.isPending ? "Chargement de votre session…" : moi ? "Rien à traiter pour le moment." : "Session indisponible."}
        </p>
      </Card>
      {moi && (
        <div>
          <Button
            variante="secondaire"
            chargement={deconnexion.isPending}
            onClick={() => deconnexion.mutate(undefined, { onSettled: () => router.replace("/connexion?motif=deconnexion") })}
          >
            Se déconnecter
          </Button>
        </div>
      )}
    </main>
  );
}

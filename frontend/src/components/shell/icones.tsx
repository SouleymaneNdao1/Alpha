import type { IconeMenu } from "@/lib/permissions";

const trace = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

/** Icônes du menu (tracés du prototype), 18 px, décoratives. */
export function IconeMenuSvg({ nom }: { nom: IconeMenu | "aide" }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" {...trace}>
      {nom === "taches" && <path d="M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h9" />}
      {nom === "administration" && (
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8" />
      )}
      {nom === "journal" && <path d="M12 3l8 3v6c0 4.5-3.2 8-8 9-4.8-1-8-4.5-8-9V6zM9 12l2 2 4-4" />}
      {nom === "etablissements" && <path d="M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6M9 11h.01M15 11h.01" />}
      {nom === "compte" && <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" />}
      {nom === "aide" && (
        <>
          <circle cx="12" cy="12" r="10" />
          <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01" />
        </>
      )}
    </svg>
  );
}

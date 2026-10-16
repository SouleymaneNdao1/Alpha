/**
 * Formats d'affichage (architecture § 7.3) : dates `fr-SN` (`dd/MM HH:mm`),
 * montants `14 600 000 FCFA` avec espace fine insécable, fuseau Africa/Dakar.
 */
const ESPACE_FINE = " ";
const FUSEAU = "Africa/Dakar";

const entier = new Intl.NumberFormat("fr-SN", { maximumFractionDigits: 0 });

/** `"14600000.00"` → `14 600 000 FCFA` (XOF affiché « FCFA », sans décimales). */
export function formatMontant(valeur: string | number, devise = "XOF"): string {
  const n = typeof valeur === "number" ? valeur : Number(valeur);
  if (!Number.isFinite(n)) return "—";
  const chiffres = entier.format(Math.round(n)).replace(/[\s  ]/g, ESPACE_FINE);
  return `${chiffres}${ESPACE_FINE}${devise === "XOF" ? "FCFA" : devise}`;
}

function parties(date: Date, options: Intl.DateTimeFormatOptions) {
  const p = new Intl.DateTimeFormat("fr-SN", { timeZone: FUSEAU, hour12: false, ...options }).formatToParts(date);
  return Object.fromEntries(p.map((x) => [x.type, x.value]));
}

/** `2026-10-10T08:02:00Z` → `10/10 08:02` ; `null` → `—`. */
export function formatDateHeureCourte(iso: string | null | undefined): string {
  if (!iso) return "—";
  const p = parties(new Date(iso), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  return `${p.day}/${p.month} ${p.hour}:${p.minute}`;
}

/** Horodatage du journal : `10/10 20:31:07`. */
export function formatHorodatage(iso: string): string {
  const p = parties(new Date(iso), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return `${p.day}/${p.month} ${p.hour}:${p.minute}:${p.second}`;
}

/** `2026-10-14` → `14/10/2026`. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const p = parties(new Date(iso), { day: "2-digit", month: "2-digit", year: "numeric" });
  return `${p.day}/${p.month}/${p.year}`;
}

/** Empreinte abrégée : `a41f…9c2e`. */
export function formatEmpreinte(hash: string): string {
  return hash.length > 8 ? `${hash.slice(0, 4)}…${hash.slice(-4)}` : hash;
}

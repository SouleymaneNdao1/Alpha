/**
 * Accès aux types générés depuis l'OpenAPI (`npm run api:types` → schema.d.ts).
 * Exemple : `type Moi = Schema<"Moi">`. Tant que le backend n'expose pas un
 * schéma, le type vaut `never` et le compilateur le signale à l'usage.
 */
import type { components } from "./schema";

type Schemas = components extends { schemas: infer S } ? S : Record<string, never>;

export type Schema<N extends string> = N extends keyof Schemas ? Schemas[N] : never;

/** Liste paginée (architecture § 5) : `?page=1&taille=25`. */
export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Liste par curseur (journal d'audit) : `?curseur=`. */
export interface PageCurseur<T> {
  next: string | null;
  results: T[];
}

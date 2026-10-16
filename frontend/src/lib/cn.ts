/** Concatène des classes CSS en ignorant les valeurs fausses. */
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

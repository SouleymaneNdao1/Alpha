/**
 * `next` des listes paginées est une URL absolue (parfois avec le nom d'hôte
 * interne du serveur) : on ne garde que le chemin et la requête, pour rester
 * sur la même origine que l'application.
 */
export function cheminDepuisUrl(url: string): string {
  try {
    const u = new URL(url, "http://alpha.invalid");
    return u.pathname + u.search;
  } catch {
    return url;
  }
}

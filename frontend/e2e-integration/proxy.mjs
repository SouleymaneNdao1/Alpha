// Proxy de test : joue le rôle de Caddy (recette et production) devant le frontend et le backend.
//   /api/*  -> Django (gunicorn)
//   le reste -> Next.js (`next start`)
// Même origine pour le navigateur, donc cookies SameSite=Lax et jeton CSRF comme en production.
//
// Variables : PROXY_PORT, PROXY_BACKEND (ex. http://127.0.0.1:8123), PROXY_FRONTEND (ex. http://127.0.0.1:3124).
// En-tête de test « x-e2e-ip » : adresse IP que Django doit voir (X-Forwarded-For). La suite en donne
// une différente à chaque test, pour que les limites de débit par IP de la connexion ne se cumulent pas.
import http from "node:http";

const port = Number(process.env.PROXY_PORT ?? 3123);
const backend = new URL(process.env.PROXY_BACKEND ?? "http://127.0.0.1:8123");
const frontend = new URL(process.env.PROXY_FRONTEND ?? "http://127.0.0.1:3124");

const HOP = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "x-e2e-ip"]);

const serveur = http.createServer((req, res) => {
  const cible = req.url?.startsWith("/api/") || req.url === "/api" ? backend : frontend;
  const ip = String(req.headers["x-e2e-ip"] ?? req.socket.remoteAddress ?? "127.0.0.1").replace(/^::ffff:/, "");
  const entetes = {};
  for (const [nom, valeur] of Object.entries(req.headers)) if (!HOP.has(nom)) entetes[nom] = valeur;
  entetes["x-forwarded-for"] = ip;
  entetes["x-forwarded-host"] = req.headers.host ?? "";
  entetes["x-forwarded-proto"] = "http";

  const amont = http.request(
    { hostname: cible.hostname, port: cible.port, path: req.url, method: req.method, headers: entetes },
    (reponse) => {
      res.writeHead(reponse.statusCode ?? 502, reponse.headers);
      reponse.pipe(res);
    },
  );
  amont.on("error", (erreur) => {
    if (!res.headersSent) res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end(`Proxy de test : ${erreur.message}`);
  });
  req.pipe(amont);
});

serveur.listen(port, "127.0.0.1", () => console.log(`Proxy de test sur http://127.0.0.1:${port}`));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => serveur.close(() => process.exit(0)));

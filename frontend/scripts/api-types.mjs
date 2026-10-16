#!/usr/bin/env node
// Génère src/lib/api/schema.d.ts depuis le schéma OpenAPI de drf-spectacular
// (architecture § 7.4). Le fichier généré est versionné ; la CI (D2) le
// régénère et échoue s'il diffère.
//
// Source, par ordre de priorité :
//   1. argument : `npm run api:types -- ../chemin/schema.yml` (fichier ou URL)
//   2. variable ALPHA_OPENAPI_SOURCE
//   3. ${ALPHA_BACKEND_URL}/api/v1/schema/ (http://backend:8000 dans docker-compose)
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const racine = join(dirname(fileURLToPath(import.meta.url)), "..");
const backend = (process.env.ALPHA_BACKEND_URL ?? "http://backend:8000").replace(/\/+$/, "");
const source = process.argv[2] ?? process.env.ALPHA_OPENAPI_SOURCE ?? `${backend}/api/v1/schema/`;
const sortie = join(racine, "src/lib/api/schema.d.ts");

const require = createRequire(import.meta.url);
const cli = join(dirname(require.resolve("openapi-typescript/package.json")), "bin/cli.js");

console.log(`Schéma OpenAPI : ${source}`);
const r = spawnSync(process.execPath, [cli, source, "-o", sortie], { stdio: "inherit", cwd: racine });
process.exit(r.status ?? 1);

/* eslint-disable @typescript-eslint/no-require-imports -- fichier CommonJS volontaire (voir ci-dessous) */
// Emplacements partagés par la préparation (preparer.mjs), la configuration Playwright et les tests.
// CommonJS : importable à la fois par un script Node en ESM et par les fichiers TypeScript de Playwright.
const path = require("node:path");

const RACINE_FRONTEND = path.resolve(__dirname, "..");
const RACINE_BACKEND = path.resolve(RACINE_FRONTEND, "..", "backend");
/** Dossier de travail d'une exécution (ignoré par git) : comptes, e-mails reçus, état des codes TOTP. */
const DOSSIER_EXECUTION = process.env.ALPHA_E2E_DOSSIER || path.join(RACINE_FRONTEND, ".e2e-integration");

exports.RACINE_FRONTEND = RACINE_FRONTEND;
exports.RACINE_BACKEND = RACINE_BACKEND;
exports.DOSSIER_EXECUTION = DOSSIER_EXECUTION;
exports.DOSSIER_COURRIELS = path.join(DOSSIER_EXECUTION, "courriels");
exports.DOSSIER_DEMO = path.join(DOSSIER_EXECUTION, "demo-acces");
exports.FICHIER_ACCES = path.join(DOSSIER_EXECUTION, "acces.json");
exports.FICHIER_ETAT_TOTP = path.join(DOSSIER_EXECUTION, "etat-totp.json");

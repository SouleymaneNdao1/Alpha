/**
 * zod configuré en français (architecture § 7.4 : messages de formulaire en
 * français). Importer `z` depuis ce module plutôt que depuis "zod".
 */
import { z } from "zod";

z.config(z.locales.fr());

export { z };

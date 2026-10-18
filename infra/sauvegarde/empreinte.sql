-- =============================================================================
-- ALPHA — empreinte d'une base, pour prouver qu'une restauration est fidèle
--
-- Exécuté par scripts/sauvegarde.sh (dans le MÊME instantané que pg_dump) et par
-- scripts/restauration.sh (sur la base restaurée) ; les deux sorties, triées,
-- doivent être identiques. Connexion : alpha_owner (BYPASSRLS, donc toutes les
-- lignes, y compris sous FORCE ROW LEVEL SECURITY).
--
-- Une ligne par élément, préfixée par sa catégorie :
--   role, extension, schema, defaut (privilèges par défaut), table (propriétaire,
--   RLS, FORCE, droits), politique (RLS), trigger, fonction (propriétaire,
--   SECURITY DEFINER, droits EXECUTE, corps), index, contrainte, sequence,
--   donnees (nombre de lignes et empreinte du contenu, table par table).
--
-- Variable psql : donnees_completes = true (empreinte MD5 du contenu de chaque
-- table, lecture complète) ou false (nombre de lignes seulement).
-- Lecture seule : aucune écriture, aucun objet créé.
-- =============================================================================

-- Formats indépendants de la session (dates, nombres) pour des empreintes stables.
SET TimeZone = 'UTC';
SET DateStyle = 'ISO, YMD';
SET IntervalStyle = 'postgres';
SET extra_float_digits = 3;
SET bytea_output = 'hex';

-- Rôles applicatifs (attributs de sécurité ; CREATEDB varie selon l'environnement).
SELECT format('role|%s|super=%s|bypassrls=%s|createrole=%s|login=%s',
              rolname, rolsuper, rolbypassrls, rolcreaterole, rolcanlogin)
  FROM pg_roles WHERE rolname IN ('alpha_owner', 'alpha_app');

SELECT format('extension|%s|%s|owner=%s', extname, extversion, pg_get_userbyid(extowner))
  FROM pg_extension;

SELECT format('schema|%s|owner=%s|acl=%s', nspname, pg_get_userbyid(nspowner),
              array_to_string(ARRAY(SELECT a::text FROM unnest(nspacl) a ORDER BY 1), ','))
  FROM pg_namespace WHERE nspname = 'public';

SELECT format('defaut|%s|%s|%s|%s', pg_get_userbyid(d.defaclrole), COALESCE(n.nspname, '*'),
              d.defaclobjtype,
              array_to_string(ARRAY(SELECT a::text FROM unnest(d.defaclacl) a ORDER BY 1), ','))
  FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace;

-- Tables, vues, séquences : propriétaire (alpha_app ne doit rien posséder),
-- RLS activée et forcée, droits accordés.
SELECT format('table|%s|%s|owner=%s|rls=%s|force=%s|acl=%s', c.relname, c.relkind,
              pg_get_userbyid(c.relowner), c.relrowsecurity, c.relforcerowsecurity,
              array_to_string(ARRAY(SELECT a::text FROM unnest(c.relacl) a ORDER BY 1), ','))
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f');

SELECT format('politique|%s|%s|%s|%s|%s|using=%s|check=%s', tablename, policyname, permissive,
              array_to_string(roles, ','), cmd,
              regexp_replace(COALESCE(qual, ''), '::[a-z_ ]+(\[\])?|[()[:space:]]', '', 'g'),
              regexp_replace(COALESCE(with_check, ''), '::[a-z_ ]+(\[\])?|[()[:space:]]', '', 'g'))
  FROM pg_policies WHERE schemaname = 'public';

-- Triggers (chaînage et immutabilité du journal d'audit, etc.) et leur état
-- d'activation : un trigger désactivé (tgenabled = 'D') serait détecté.
SELECT format('trigger|%s|%s|enabled=%s|%s', c.relname, t.tgname, t.tgenabled, pg_get_triggerdef(t.oid))
  FROM pg_trigger t
  JOIN pg_class c ON c.oid = t.tgrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND NOT t.tgisinternal;

-- Les expressions (contraintes CHECK, politiques, index) sont comparées après
-- normalisation : PostgreSQL réécrit certaines expressions lors d'un aller-retour
-- dump/restauration sans en changer le sens, par exemple
--   ((ARRAY['A'::varchar, 'B'::varchar])::text[])  devient
--   ARRAY[('A'::varchar)::text, ('B'::varchar)::text]
-- On retire donc conversions de type (::…), parenthèses et espaces avant le MD5.

-- Fonctions propres à ALPHA (hors fonctions des extensions).
SELECT format('fonction|%s(%s)|owner=%s|secdef=%s|acl=%s|corps=%s', p.proname,
              pg_get_function_identity_arguments(p.oid), pg_get_userbyid(p.proowner), p.prosecdef,
              array_to_string(ARRAY(SELECT a::text FROM unnest(p.proacl) a ORDER BY 1), ','),
              md5(pg_get_functiondef(p.oid)))
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public' AND p.prokind IN ('f', 'p')
   AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e');

SELECT format('index|%s|%s', c.relname, md5(regexp_replace(pg_get_indexdef(i.indexrelid), '::[a-z_ ]+(\[\])?|[()[:space:]]', '', 'g')))
  FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public';

SELECT format('contrainte|%s|%s|%s|%s', conrelid::regclass::text, conname, contype,
              md5(regexp_replace(pg_get_constraintdef(oid), '::[a-z_ ]+(\[\])?|[()[:space:]]', '', 'g')))
  FROM pg_constraint WHERE connamespace = 'public'::regnamespace;

-- Séquences : présence et type seulement. Leur valeur courante n'obéit pas à
-- l'instantané (non transactionnelle) : la comparer donnerait de fausses
-- alertes sur une base en service. Les identifiants déjà attribués sont
-- couverts par l'empreinte des données ci-dessous.
SELECT format('sequence|%s|%s|%s', sequencename, data_type, increment_by)
  FROM pg_sequences WHERE schemaname = 'public';

-- Données, table par table : nombre de lignes et MD5 de l'ensemble des lignes
-- (ordre indépendant du stockage physique).
\if :donnees_completes
SELECT format($q$SELECT format('donnees|%%s|%%s|%%s', %L, count(*), COALESCE(md5(string_agg(h, '' ORDER BY h COLLATE "C")), '-')) FROM (SELECT md5(t::text) AS h FROM %I.%I t) s$q$,
              c.relname, n.nspname, c.relname)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
 ORDER BY c.relname \gexec
\else
SELECT format($q$SELECT format('donnees|%%s|%%s|-', %L, count(*)) FROM %I.%I$q$,
              c.relname, n.nspname, c.relname)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
 ORDER BY c.relname \gexec
\endif

#!/usr/bin/env bash
# =============================================================================
# ALPHA — initialisation des rôles PostgreSQL (architecture-sprint1.md, § 3.1)
#
# Exécuté UNE SEULE FOIS par l'image officielle postgres, au premier démarrage
# d'un volume de données vide (montage sur /docker-entrypoint-initdb.d).
# Pour le rejouer en développement : `scripts/dev.ps1 reset` (efface la base).
#
# Crée :
#   - alpha_owner : LOGIN NOSUPERUSER NOCREATEROLE BYPASSRLS (+ CREATEDB en dev/CI)
#                   propriétaire de la base `alpha` (et donc du schéma public,
#                   dont le propriétaire est pg_database_owner depuis PG 15) ;
#   - alpha_app   : LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOBYPASSRLS
#                   propriétaire de RIEN, donc soumis à la RLS ;
#   - la base `alpha`, propriété d'alpha_owner.
#
# Les droits sur le schéma et les tables (GRANT, DEFAULT PRIVILEGES, extensions)
# ne sont PAS posés ici : ils relèvent de la migration Django `tenancy.0001`,
# exécutée par alpha_owner (§ 3.1), car ils sont stockés par base et doivent
# être rejoués dans la base de test.
#
# Variables lues (aucun mot de passe n'est écrit dans ce fichier) :
#   ALPHA_OWNER_PASSWORD ou ALPHA_OWNER_PASSWORD_FILE   (obligatoire)
#   ALPHA_APP_PASSWORD   ou ALPHA_APP_PASSWORD_FILE     (obligatoire)
#   ALPHA_OWNER_CREATEDB  true|false (défaut false ; true en dev/CI uniquement)
#   ALPHA_DB_NAME         nom de la base (défaut alpha)
# Les variantes *_FILE permettent d'utiliser des secrets Docker (recette/prod).
#
# Le script est idempotent : relancé à la main sur une instance existante, il
# réaligne les attributs et les mots de passe des deux rôles sans rien casser.
# Remarque : l'entrypoint postgres « source » les .sh non exécutables ; on évite
# donc `set -u` et toute variable globale qui pourrait gêner l'entrypoint.
# =============================================================================
set -Eeo pipefail

alpha_lire_secret() {
	# $1 = nom de la variable ; lit $1 ou le fichier désigné par ${1}_FILE.
	local nom="$1" fichier_var="${1}_FILE" valeur=""
	if [ -n "${!nom:-}" ] && [ -n "${!fichier_var:-}" ]; then
		echo "01-roles.sh : $nom et ${fichier_var} sont tous deux définis, n'en garder qu'un." >&2
		return 1
	fi
	if [ -n "${!fichier_var:-}" ]; then
		valeur="$(< "${!fichier_var}")"
	else
		valeur="${!nom:-}"
	fi
	printf '%s' "$valeur"
}

alpha_init_roles() {
	local owner_pwd app_pwd createdb db_name

	owner_pwd="$(alpha_lire_secret ALPHA_OWNER_PASSWORD)"
	app_pwd="$(alpha_lire_secret ALPHA_APP_PASSWORD)"
	db_name="${ALPHA_DB_NAME:-alpha}"

	# --- Garde-fous : aucun mot de passe vide, par défaut ou partagé ---------
	local nom valeur
	for nom in owner_pwd app_pwd; do
		valeur="${!nom}"
		if [ -z "$valeur" ]; then
			echo "01-roles.sh : mot de passe manquant ($nom). Renseignez ALPHA_OWNER_PASSWORD et ALPHA_APP_PASSWORD dans .env (scripts/dev.ps1 init)." >&2
			return 1
		fi
		if [ "$valeur" = "A_GENERER" ] || [ "${#valeur}" -lt 16 ]; then
			echo "01-roles.sh : mot de passe trop court ou encore à la valeur d'exemple ($nom). Minimum 16 caractères ; lancez scripts/dev.ps1 init." >&2
			return 1
		fi
	done
	if [ "$owner_pwd" = "$app_pwd" ]; then
		echo "01-roles.sh : alpha_owner et alpha_app doivent avoir des mots de passe différents." >&2
		return 1
	fi
	if ! [[ "$db_name" =~ ^[a-z_][a-z0-9_]*$ ]]; then
		echo "01-roles.sh : ALPHA_DB_NAME invalide ($db_name)." >&2
		return 1
	fi

	case "${ALPHA_OWNER_CREATEDB:-false}" in
		true | TRUE | 1 | on | yes | oui) createdb=on ;;
		*) createdb=off ;;
	esac

	# Les mots de passe sont transmis par l'environnement de psql et relus avec
	# \getenv (PostgreSQL ≥ 15) : ils n'apparaissent ni dans la ligne de commande
	# (ps), ni dans ce fichier. Interpolation :'...' = littéral SQL correctement
	# échappé. Le serveur stocke un hachage SCRAM-SHA-256 (défaut de PG 16).
	ALPHA_PSQL_OWNER_PWD="$owner_pwd" \
	ALPHA_PSQL_APP_PWD="$app_pwd" \
	psql -v ON_ERROR_STOP=1 -X -q \
		--username "${POSTGRES_USER:-postgres}" \
		--dbname "${POSTGRES_DB:-postgres}" \
		-v owner_createdb="$createdb" \
		-v db_name="$db_name" <<-'EOSQL'
		\getenv owner_pwd ALPHA_PSQL_OWNER_PWD
		\getenv app_pwd ALPHA_PSQL_APP_PWD

		-- Ne jamais journaliser ces commandes (elles contiennent un mot de passe).
		SET log_statement = 'none';
		SET log_min_duration_statement = -1;

		-- 1. Rôles (création si absents, puis alignement systématique des attributs)
		SELECT 'CREATE ROLE alpha_owner'
		 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha_owner') \gexec
		SELECT 'CREATE ROLE alpha_app'
		 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alpha_app') \gexec

		ALTER ROLE alpha_owner LOGIN NOSUPERUSER NOCREATEROLE NOREPLICATION BYPASSRLS
		      PASSWORD :'owner_pwd';
		ALTER ROLE alpha_app   LOGIN NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS
		      PASSWORD :'app_pwd';

		-- CREATEDB pour alpha_owner : développement et CI uniquement (base de test).
		\if :owner_createdb
		ALTER ROLE alpha_owner CREATEDB;
		\else
		ALTER ROLE alpha_owner NOCREATEDB;
		\endif

		-- 2. Base applicative, propriété d'alpha_owner
		SELECT format('CREATE DATABASE %I OWNER alpha_owner ENCODING %L TEMPLATE template0', :'db_name', 'UTF8')
		 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name') \gexec
		SELECT format('ALTER DATABASE %I OWNER TO alpha_owner', :'db_name') \gexec

		-- Connexion : seulement les deux rôles applicatifs (et le superutilisateur).
		SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name') \gexec
		SELECT format('GRANT CONNECT ON DATABASE %I TO alpha_app', :'db_name') \gexec

		-- 3. Contrôles : alpha_app ne possède rien et reste soumis à la RLS.
		\connect :db_name
		DO $verif$
		DECLARE
		  r record;
		BEGIN
		  SELECT * INTO r FROM pg_roles WHERE rolname = 'alpha_app';
		  IF r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb THEN
		    RAISE EXCEPTION 'alpha_app a des attributs interdits (superuser/bypassrls/createrole/createdb)';
		  END IF;
		  SELECT * INTO r FROM pg_roles WHERE rolname = 'alpha_owner';
		  IF r.rolsuper OR r.rolcreaterole OR NOT r.rolbypassrls THEN
		    RAISE EXCEPTION 'alpha_owner n''a pas les attributs attendus';
		  END IF;
		  IF EXISTS (SELECT 1 FROM pg_database WHERE datdba = 'alpha_app'::regrole)
		     OR EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = 'alpha_app'::regrole)
		     OR EXISTS (SELECT 1 FROM pg_class WHERE relowner = 'alpha_app'::regrole)
		     OR EXISTS (SELECT 1 FROM pg_proc WHERE proowner = 'alpha_app'::regrole)
		     OR EXISTS (SELECT 1 FROM pg_type WHERE typowner = 'alpha_app'::regrole)
		     OR EXISTS (SELECT 1 FROM pg_shdepend
		                 WHERE refclassid = 'pg_authid'::regclass
		                   AND refobjid = 'alpha_app'::regrole AND deptype = 'o') THEN
		    RAISE EXCEPTION 'alpha_app est propriétaire d''au moins un objet';
		  END IF;
		END
		$verif$;
	EOSQL

	echo "01-roles.sh : rôles alpha_owner (CREATEDB=${createdb}) et alpha_app prêts ; base ${db_name} propriété d'alpha_owner."
}

alpha_init_roles
unset -f alpha_init_roles alpha_lire_secret

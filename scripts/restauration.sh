#!/usr/bin/env bash
# =============================================================================
# ALPHA — restauration d'une sauvegarde chiffrée (tâche D3)
#
#   scripts/restauration.sh <prod|recette> --lister
#   scripts/restauration.sh <prod|recette> --identite <clé privée age> [options]
#
# Options :
#   --sauvegarde NOM|derniere  sauvegarde à restaurer (défaut : la plus récente
#                              du stockage hors site)
#   --source DOSSIER           dossier local contenant la sauvegarde (copie du
#                              stockage, dossier de /var/backups/alpha) au lieu
#                              du stockage hors site
#   --base NOM                 base cible, qui ne doit pas exister
#                              (défaut : alpha_restau_<horodatage>)
#   --verifier-audit           lance « manage.py verifier_chaine_audit --tous »
#                              sur la base restaurée (connexion alpha_app, RLS)
#   --remplacer                remplace la base ET les fichiers déposés de
#                              l'environnement par la sauvegarde (application
#                              arrêtée pendant l'opération ; l'ancienne base est
#                              conservée sous alpha_avant_restau_<horodatage>)
#   --oui                      pas de confirmation interactive (--remplacer)
#
# Étapes : téléchargement → contrôle SHA-256 (manifeste) → création d'une base
# NEUVE → déchiffrement en flux et pg_restore en une seule transaction (aucun
# dump en clair sur le disque) → comparaison de l'empreinte de la base restaurée
# avec celle prise au moment de la sauvegarde (structure, politiques RLS,
# triggers, droits d'alpha_app, données table par table) → [vérification de la
# chaîne d'audit] → [bascule].
#
# Sans --remplacer, rien n'est modifié dans la base en service : c'est le mode
# du TEST DE RESTAURATION mensuel (docs/ops/deploiement.md § 8).
#
# La clé privée age n'est pas sur le serveur : apportez-la le temps de
# l'opération (fichier 600), puis supprimez-la (shred -u).
# Codes de sortie : 0 succès, 1 erreur, 3 empreinte différente, 4 chaîne d'audit rompue.
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
# shellcheck source=scripts/ops-commun.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/ops-commun.sh"

aide() {
	sed -n '2,/^# =====/p' "$SCRIPT" | sed -e 's/^# \{0,1\}//' -e '/^=====/d'
}

# --- Arguments ---------------------------------------------------------------
ENV_NOM="${1:-}"
case "$ENV_NOM" in
	"" | -h | --help)
		aide
		exit 0
		;;
esac
shift
verifier_env_nom "$ENV_NOM"
IDENTITE="" SAUVEGARDE="derniere" SOURCE="" BASE_CIBLE="" VERIFIER_AUDIT="non"
REMPLACER="non" CONFIRME="non" LISTER="non"
while [ $# -gt 0 ]; do
	case "$1" in
		--identite)
			IDENTITE="${2:-}"
			shift
			;;
		--sauvegarde)
			SAUVEGARDE="${2:-}"
			shift
			;;
		--source)
			SOURCE="${2:-}"
			shift
			;;
		--base)
			BASE_CIBLE="${2:-}"
			shift
			;;
		--verifier-audit) VERIFIER_AUDIT="oui" ;;
		--remplacer) REMPLACER="oui" ;;
		--oui) CONFIRME="oui" ;;
		--lister) LISTER="oui" ;;
		*) erreur "option inconnue : $1 (--help pour l'aide)" ;;
	esac
	shift
done

charger_config_ops oui
PG_MODE="${ALPHA_PG_MODE:-docker}"
DESTINATION="${ALPHA_SAUVEGARDE_DESTINATION:-}"
SPOOL="${ALPHA_SAUVEGARDE_SPOOL:-/var/backups/alpha}"
EMPREINTE_SQL="$ALPHA_RACINE/infra/sauvegarde/empreinte.sql"
export RCLONE_CONFIG="${RCLONE_CONFIG:-/etc/alpha/rclone.conf}"
PROJET="alpha-$ENV_NOM"
MOTIF_NOM="^${PROJET}_[0-9]{8}T[0-9]{6}Z_[a-z0-9-]+$"

# --- Liste des sauvegardes hors site ---------------------------------------------
lister_distantes() {
	[ -n "$DESTINATION" ] || erreur "ALPHA_SAUVEGARDE_DESTINATION vide dans $ALPHA_OPS_CONFIG."
	# Chemins relatifs : AAAA/MM/<nom>/ et mensuel/<nom>/ ; tri par nom (= date).
	rclone lsf "$DESTINATION/$ENV_NOM" -R --dirs-only --max-depth 3 2>/dev/null |
		sed 's#/$##' | awk -F/ -v m="$MOTIF_NOM" '$NF ~ m { print $NF "\t" $0 }' |
		LC_ALL=C sort -t$'\t' -k1,1 -u
}

if [ "$LISTER" = "oui" ]; then
	lister_distantes | cut -f2
	exit 0
fi

# --- Contrôles préalables ------------------------------------------------------------
[ -n "$IDENTITE" ] || erreur "--identite <fichier de clé privée age> est obligatoire."
[ -f "$IDENTITE" ] || erreur "clé privée introuvable : $IDENTITE"
verifier_droits_secret "$IDENTITE"
grep -q 'AGE-SECRET-KEY-' "$IDENTITE" || erreur "$IDENTITE ne contient pas de clé privée age."
for outil in age sha256sum; do
	command -v "$outil" >/dev/null 2>&1 || erreur "outil manquant : $outil"
done
if [ "$REMPLACER" = "oui" ] && [ "$PG_MODE" != "docker" ]; then
	erreur "--remplacer n'est disponible qu'en mode docker (VPS)."
fi

HORODATAGE="$(date -u +%Y%m%dT%H%M%SZ)"
BASE_CIBLE="${BASE_CIBLE:-alpha_restau_${HORODATAGE,,}}"
[[ "$BASE_CIBLE" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || erreur "nom de base invalide : $BASE_CIBLE"

FICHIER_ENV="$(fichier_env "$ENV_NOM")"
DB_EN_SERVICE="${ALPHA_DB_NAME:-}"
if [ -z "$DB_EN_SERVICE" ] && [ -f "$FICHIER_ENV" ]; then
	DB_EN_SERVICE="$(valeur_env "$FICHIER_ENV" ALPHA_DB_NAME)"
fi
DB_EN_SERVICE="${DB_EN_SERVICE:-alpha}"
[ "$BASE_CIBLE" != "$DB_EN_SERVICE" ] || erreur "la base cible ne peut pas être la base en service ($DB_EN_SERVICE) : utilisez --remplacer."

# --- Accès à PostgreSQL (voir sauvegarde.sh) -------------------------------------------
case "$PG_MODE" in
	docker)
		DB_CONTENEUR="$(conteneur_service "$PROJET" db)"
		[ -n "$DB_CONTENEUR" ] || erreur "le conteneur db du projet $PROJET ne tourne pas."
		# pg_admin : superutilisateur, base « postgres » (création/renommage de bases).
		pg_admin() {
			local prog="$1"
			shift
			docker exec -i -u postgres "$DB_CONTENEUR" "$prog" -U postgres -d postgres "$@"
		}
		# pg_owner BASE PROG… : alpha_owner sur la base indiquée.
		pg_owner() {
			local base="$1" prog="$2"
			shift 2
			docker exec -i -u postgres "$DB_CONTENEUR" "$prog" -U alpha_owner -d "$base" "$@"
		}
		;;
	local)
		: "${ALPHA_OWNER_PASSWORD:?ALPHA_OWNER_PASSWORD requis en mode local}"
		pg_admin() {
			local prog="$1"
			shift
			PGPASSWORD="${ALPHA_PG_ADMIN_PASSWORD:-$ALPHA_OWNER_PASSWORD}" "$prog" -h "${PGHOST:-127.0.0.1}" \
				-p "${PGPORT:-5432}" -U "${ALPHA_PG_ADMIN_USER:-alpha_owner}" -d postgres "$@"
		}
		pg_owner() {
			local base="$1" prog="$2"
			shift 2
			PGPASSWORD="$ALPHA_OWNER_PASSWORD" "$prog" -h "${PGHOST:-127.0.0.1}" -p "${PGPORT:-5432}" \
				-U alpha_owner -d "$base" "$@"
		}
		;;
	*) erreur "ALPHA_PG_MODE inconnu : $PG_MODE (docker ou local)." ;;
esac

sql_admin() { pg_admin psql -X -q -A -t -v ON_ERROR_STOP=1 "$@"; }

# --- Dossier de travail ----------------------------------------------------------------
mkdir -p "$SPOOL"
chmod 700 "$SPOOL"
TRAVAIL="$(mktemp -d "$SPOOL/restauration.XXXXXX")"
nettoyer() { rm -rf -- "$TRAVAIL"; }
trap nettoyer EXIT

# --- 1. Récupération de la sauvegarde --------------------------------------------------
if [ -n "$SOURCE" ]; then
	[ -f "$SOURCE/manifeste.txt" ] || erreur "$SOURCE/manifeste.txt introuvable."
	DOSSIER="$SOURCE"
	NOM="$(basename -- "$SOURCE")"
else
	command -v rclone >/dev/null 2>&1 || erreur "outil manquant : rclone"
	LISTE="$(lister_distantes)"
	[ -n "$LISTE" ] || erreur "aucune sauvegarde de $ENV_NOM sur $DESTINATION."
	if [ "$SAUVEGARDE" = "derniere" ]; then
		LIGNE="$(tail -n 1 <<<"$LISTE")"
	else
		LIGNE="$(awk -F'\t' -v n="$SAUVEGARDE" '$1 == n' <<<"$LISTE" | head -n 1)"
		[ -n "$LIGNE" ] || erreur "sauvegarde introuvable : $SAUVEGARDE (--lister pour la liste)."
	fi
	NOM="$(cut -f1 <<<"$LIGNE")"
	DOSSIER="$TRAVAIL/$NOM"
	info "Téléchargement de $NOM"
	rclone copy "$DESTINATION/$ENV_NOM/$(cut -f2 <<<"$LIGNE")" "$DOSSIER" --retries 5 -q
fi
info "Sauvegarde : $NOM"
grep -E '^(date_utc|version_alpha|postgresql|empreinte|evenements_audit|media)=' "$DOSSIER/manifeste.txt" | sed 's/^/    /' >&2

# --- 2. Intégrité des fichiers chiffrés ------------------------------------------------
info "Contrôle des empreintes SHA-256 du manifeste"
(cd "$DOSSIER" && grep -E '^[0-9a-f]{64}  ' manifeste.txt | sha256sum -c --strict --quiet -) ||
	erreur "fichier altéré ou incomplet : la sauvegarde $NOM est inutilisable."
ok "fichiers intacts."

age --decrypt -i "$IDENTITE" -o "$TRAVAIL/empreinte.sauvegarde" "$DOSSIER/empreinte.txt.age" ||
	erreur "déchiffrement impossible : cette clé n'est pas l'une des clés destinataires de la sauvegarde."

# --- 3. Base neuve, propriété d'alpha_owner --------------------------------------------
EXISTE="$(sql_admin -c "SELECT 1 FROM pg_database WHERE datname = '$BASE_CIBLE'")"
[ -z "$EXISTE" ] || erreur "la base $BASE_CIBLE existe déjà."
info "Création de la base $BASE_CIBLE"
sql_admin <<-SQL
	CREATE DATABASE "$BASE_CIBLE" OWNER alpha_owner ENCODING 'UTF8' TEMPLATE template0;
	REVOKE ALL ON DATABASE "$BASE_CIBLE" FROM PUBLIC;
	GRANT CONNECT ON DATABASE "$BASE_CIBLE" TO alpha_app;
SQL

# --- 4. Restauration (déchiffrement en flux, une seule transaction) --------------------
info "Restauration (pg_restore, transaction unique)"
DEBUT=$SECONDS
age --decrypt -i "$IDENTITE" "$DOSSIER/base.dump.age" |
	pg_owner "$BASE_CIBLE" pg_restore --single-transaction --exit-on-error --no-password ||
	erreur "pg_restore a échoué : la base $BASE_CIBLE est vide (transaction annulée). Supprimez-la : DROP DATABASE \"$BASE_CIBLE\"."
ok "base restaurée en $((SECONDS - DEBUT)) s."

# --- 5. Empreinte : la base restaurée est-elle identique à la base sauvegardée ? -------
info "Comparaison des empreintes (structure, RLS, triggers, droits, données)"
if grep -q '^empreinte=.*données complete' "$DOSSIER/manifeste.txt"; then COMPLETE=true; else COMPLETE=false; fi
{
	echo "\\set donnees_completes $COMPLETE"
	cat "$EMPREINTE_SQL"
} | pg_owner "$BASE_CIBLE" psql -X -q -A -t -v ON_ERROR_STOP=1 | sed '/^$/d' | LC_ALL=C sort >"$TRAVAIL/empreinte.restauree"
# Une sauvegarde antérieure à l'empreinte sans valeur de séquence : on compare
# les séquences sur leur seul nom.
normaliser() { sed -E 's/^(sequence\|[^|]+)\|.*/\1/' "$1" | LC_ALL=C sort; }
if ! diff <(normaliser "$TRAVAIL/empreinte.sauvegarde") <(normaliser "$TRAVAIL/empreinte.restauree") >"$TRAVAIL/ecarts"; then
	avert "la base restaurée DIFFÈRE de la base sauvegardée (< sauvegarde, > restaurée) :"
	head -n 40 "$TRAVAIL/ecarts" >&2
	avert "base $BASE_CIBLE conservée pour analyse."
	exit 3
fi
NB="$(wc -l <"$TRAVAIL/empreinte.restauree")"
for cat in table politique trigger fonction donnees; do
	printf '    %-10s %s\n' "$cat" "$(grep -c "^$cat|" "$TRAVAIL/empreinte.restauree" || true)" >&2
done
ok "empreinte identique ($NB éléments) : données, politiques RLS, triggers et droits conformes."

# --- 6. Fichiers déposés ---------------------------------------------------------------
if [ -f "$DOSSIER/media.tar.gz.age" ]; then
	NB_FICHIERS="$(age --decrypt -i "$IDENTITE" "$DOSSIER/media.tar.gz.age" | tar -tzf - | grep -vc '/$' || true)"
	ok "archive des fichiers déposés lisible ($NB_FICHIERS fichier(s))."
fi

# --- 7. Chaîne d'audit -----------------------------------------------------------------
if [ "$VERIFIER_AUDIT" = "oui" ]; then
	info "Vérification de la chaîne d'audit sur $BASE_CIBLE (alpha_app, sous RLS)"
	code=0
	if [ "$PG_MODE" = "docker" ]; then
		VERSION="$(version_deployee "$ENV_NOM")"
		[ -n "$VERSION" ] || erreur "aucune version déployée pour $ENV_NOM : impossible de lancer manage.py."
		MDP_APP="$(valeur_env "$FICHIER_ENV" ALPHA_APP_PASSWORD)"
		# File Celery 15 : les éventuelles alertes de rupture préparées pendant le
		# contrôle ne sont PAS envoyées par le worker en service.
		ALPHA_VERSION="$VERSION" compose_env "$ENV_NOM" run --rm --no-deps -T \
			-e "DATABASE_URL=postgres://alpha_app:$MDP_APP@db:5432/$BASE_CIBLE" \
			-e "CELERY_BROKER_URL=redis://redis:6379/15" \
			backend python manage.py verifier_chaine_audit --tous || code=$?
	else
		[ -n "${ALPHA_MANAGE_PY:-}" ] || erreur "mode local : définissez ALPHA_MANAGE_PY (ex. « …/python …/manage.py »)."
		: "${ALPHA_APP_PASSWORD:?ALPHA_APP_PASSWORD requis en mode local}"
		# shellcheck disable=SC2086  # ALPHA_MANAGE_PY = interpréteur + chemin
		DATABASE_URL="postgres://alpha_app:$ALPHA_APP_PASSWORD@${PGHOST:-127.0.0.1}:${PGPORT:-5432}/$BASE_CIBLE" \
			$ALPHA_MANAGE_PY verifier_chaine_audit --tous || code=$?
	fi
	case "$code" in
		0) ok "chaîne d'audit intacte sur la base restaurée." ;;
		2)
			avert "chaîne d'audit ROMPUE sur la base restaurée."
			exit 4
			;;
		*) erreur "vérification de la chaîne d'audit impossible (code $code)." ;;
	esac
fi

# --- 8. Bascule (optionnelle) ------------------------------------------------------------
if [ "$REMPLACER" != "oui" ]; then
	ok "restauration de $NOM vérifiée dans la base $BASE_CIBLE (la base en service n'a pas été touchée)."
	echo "    Supprimer la base de test : scripts/restauration.sh ne le fait pas ; en SQL (superutilisateur) :" >&2
	echo "    DROP DATABASE \"$BASE_CIBLE\";" >&2
	exit 0
fi

VERSION="$(version_deployee "$ENV_NOM")"
[ -n "$VERSION" ] || erreur "aucune version déployée pour $ENV_NOM (scripts/deploy.sh deployer d'abord)."
ANCIENNE="${DB_EN_SERVICE}_avant_restau_${HORODATAGE,,}"
if [ "$CONFIRME" != "oui" ]; then
	avert "La base « $DB_EN_SERVICE » et les fichiers déposés de $ENV_NOM vont être REMPLACÉS par la sauvegarde $NOM."
	avert "Les données écrites depuis cette sauvegarde seront perdues (l'ancienne base reste disponible sous $ANCIENNE)."
	read -r -p "Tapez « $ENV_NOM » pour confirmer : " reponse
	[ "$reponse" = "$ENV_NOM" ] || erreur "abandon."
fi
export ALPHA_VERSION="$VERSION"
info "Arrêt de l'application $ENV_NOM"
compose_env "$ENV_NOM" stop backend worker beat frontend
info "Bascule : $DB_EN_SERVICE → $ANCIENNE ; $BASE_CIBLE → $DB_EN_SERVICE"
sql_admin <<-SQL
	SELECT pg_terminate_backend(pid) FROM pg_stat_activity
	 WHERE datname IN ('$DB_EN_SERVICE', '$BASE_CIBLE') AND pid <> pg_backend_pid();
	ALTER DATABASE "$DB_EN_SERVICE" RENAME TO "$ANCIENNE";
	ALTER DATABASE "$BASE_CIBLE" RENAME TO "$DB_EN_SERVICE";
SQL
if [ -f "$DOSSIER/media.tar.gz.age" ]; then
	info "Restauration des fichiers déposés (volume ${PROJET}_media)"
	IMAGE_DB="$(docker inspect -f '{{.Config.Image}}' "$DB_CONTENEUR")"
	age --decrypt -i "$IDENTITE" "$DOSSIER/media.tar.gz.age" |
		docker run --rm -i --network none -v "${PROJET}_media:/donnees" "$IMAGE_DB" \
			sh -c 'find /donnees -mindepth 1 -delete && tar -xzf - -C /donnees && chown -R 10001:10001 /donnees'
fi
info "Redémarrage de l'application $ENV_NOM (version $VERSION)"
compose_env "$ENV_NOM" up -d --no-deps --wait backend worker beat frontend
ok "restauration de $NOM en service sur $ENV_NOM."
echo "    Ancienne base conservée : $ANCIENNE (à supprimer après contrôle : DROP DATABASE \"$ANCIENNE\";)" >&2

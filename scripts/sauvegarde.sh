#!/usr/bin/env bash
# =============================================================================
# ALPHA — sauvegarde chiffrée hors site d'un environnement (tâche D3)
#
#   scripts/sauvegarde.sh <prod|recette> [--motif quotidienne|avant-deploiement|manuelle]
#                                         [--sans-envoi]
#   scripts/sauvegarde.sh <prod|recette> --signaler-echec   (appelé par systemd, OnFailure)
#
# Lancée chaque nuit par le minuteur systemd alpha-sauvegarde@prod.timer (et
# @recette), et par scripts/deploy.sh avant chaque déploiement.
#
# Contenu d'une sauvegarde (dossier alpha-<env>_<horodatage UTC>_<motif>/) :
#   base.dump.age         pg_dump format « custom » de la base, chiffré (age)
#   empreinte.txt.age     empreinte de la base (structure, RLS, triggers, droits,
#                         données) prise dans le MÊME instantané que le dump,
#                         chiffrée ; restauration.sh la compare à la base restaurée
#   media.tar.gz.age      volume des fichiers déposés, chiffré (si présent)
#   manifeste.txt         en clair : métadonnées et SHA-256 des fichiers chiffrés
#
# Chiffrement : age, avec la ou les CLÉS PUBLIQUES de ALPHA_SAUVEGARDE_DESTINATAIRES.
# La clé privée n'est JAMAIS sur le VPS : un attaquant qui prend le serveur ne
# peut pas lire les sauvegardes. Aucun fichier en clair n'est écrit sur le disque.
# Envoi : rclone vers un stockage objet compatible S3 (ALPHA_SAUVEGARDE_DESTINATION).
#
# Réglages : /etc/alpha/ops.env (modèle : infra/ops.env.example).
# Documentation : docs/ops/deploiement.md § 8.
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
MOTIF="quotidienne"
ENVOI="oui"
SIGNALER_ECHEC="non"
while [ $# -gt 0 ]; do
	case "$1" in
		--motif)
			MOTIF="${2:-}"
			shift
			;;
		--sans-envoi) ENVOI="non" ;;
		--signaler-echec) SIGNALER_ECHEC="oui" ;;
		*) erreur "option inconnue : $1" ;;
	esac
	shift
done
[[ "$MOTIF" =~ ^[a-z0-9-]+$ ]] || erreur "motif invalide : $MOTIF"

charger_config_ops oui
ENV_MAJ="$(printf '%s' "$ENV_NOM" | tr '[:lower:]' '[:upper:]')"
PING_VAR="ALPHA_SAUVEGARDE_PING_URL_$ENV_MAJ"
PING_URL="${!PING_VAR:-}"

if [ "$SIGNALER_ECHEC" = "oui" ]; then
	signaler "$PING_URL" down "sauvegarde $ENV_NOM en échec (voir journalctl -u alpha-sauvegarde@$ENV_NOM)"
	exit 0
fi

# --- Réglages ----------------------------------------------------------------
PG_MODE="${ALPHA_PG_MODE:-docker}"
DESTINATAIRES="${ALPHA_SAUVEGARDE_DESTINATAIRES:-/etc/alpha/sauvegarde-destinataires.txt}"
DESTINATION="${ALPHA_SAUVEGARDE_DESTINATION:-}"
SPOOL="${ALPHA_SAUVEGARDE_SPOOL:-/var/backups/alpha}"
RETENTION_LOCALE="${ALPHA_SAUVEGARDE_RETENTION_LOCALE_JOURS:-3}"
EMPREINTE_COMPLETE="${ALPHA_SAUVEGARDE_EMPREINTE_DONNEES:-complete}"
EMPREINTE_SQL="$ALPHA_RACINE/infra/sauvegarde/empreinte.sql"
export RCLONE_CONFIG="${RCLONE_CONFIG:-/etc/alpha/rclone.conf}"

for outil in age sha256sum flock; do
	command -v "$outil" >/dev/null 2>&1 || erreur "outil manquant : $outil (voir docs/ops/deploiement.md § 2)."
done
if [ "$ENVOI" = "oui" ]; then
	command -v rclone >/dev/null 2>&1 || erreur "outil manquant : rclone."
	[ -n "$DESTINATION" ] || erreur "ALPHA_SAUVEGARDE_DESTINATION vide dans $ALPHA_OPS_CONFIG."
fi

# La liste des destinataires ne doit contenir QUE des clés publiques.
[ -s "$DESTINATAIRES" ] || erreur "$DESTINATAIRES absent ou vide (clés publiques age)."
if grep -q 'AGE-SECRET-KEY' "$DESTINATAIRES"; then
	erreur "$DESTINATAIRES contient une CLÉ PRIVÉE age : elle ne doit jamais être sur le serveur. Gardez seulement la ligne « age1… »."
fi
grep -qE '^(age1[0-9a-z]+|ssh-(ed25519|rsa) )' "$DESTINATAIRES" ||
	erreur "$DESTINATAIRES ne contient aucune clé publique age (age1…)."

# --- Accès à PostgreSQL ----------------------------------------------------------
# docker : outils PostgreSQL du conteneur db (même version que le serveur),
#          connexion par la socket locale du conteneur (authentification « trust »
#          de l'image officielle, aucun mot de passe à manipuler).
# local  : outils installés sur l'hôte, connexion TCP (PGHOST, PGPORT,
#          ALPHA_OWNER_PASSWORD) ; sert aux tests et à un PostgreSQL hors Docker.
PROJET="alpha-$ENV_NOM"
FICHIER_ENV="$(fichier_env "$ENV_NOM")"
if [ -f "$FICHIER_ENV" ]; then
	DB_NOM="${ALPHA_DB_NAME:-$(valeur_env "$FICHIER_ENV" ALPHA_DB_NAME)}"
else
	DB_NOM="${ALPHA_DB_NAME:-}"
fi
DB_NOM="${DB_NOM:-alpha}"
case "$PG_MODE" in
	docker)
		DB_CONTENEUR="$(conteneur_service "$PROJET" db)"
		[ -n "$DB_CONTENEUR" ] || erreur "le conteneur db du projet $PROJET ne tourne pas."
		pg_outil() { # pg_outil <programme> [args…] (rôle alpha_owner, base DB_NOM)
			local prog="$1"
			shift
			docker exec -i -u postgres "$DB_CONTENEUR" "$prog" -U alpha_owner -d "$DB_NOM" "$@"
		}
		;;
	local)
		: "${ALPHA_OWNER_PASSWORD:?ALPHA_OWNER_PASSWORD requis en mode local}"
		pg_outil() {
			local prog="$1"
			shift
			PGPASSWORD="$ALPHA_OWNER_PASSWORD" "$prog" -h "${PGHOST:-127.0.0.1}" -p "${PGPORT:-5432}" \
				-U alpha_owner -d "$DB_NOM" "$@"
		}
		;;
	*) erreur "ALPHA_PG_MODE inconnu : $PG_MODE (docker ou local)." ;;
esac

# --- Préparation -------------------------------------------------------------------
HORODATAGE="$(date -u +%Y%m%dT%H%M%SZ)"
NOM="${PROJET}_${HORODATAGE}_${MOTIF}"
mkdir -p "$SPOOL/$ENV_NOM"
chmod 700 "$SPOOL" "$SPOOL/$ENV_NOM"
DOSSIER="$SPOOL/$ENV_NOM/$NOM"

# Une seule sauvegarde à la fois par environnement.
exec 9>"$SPOOL/$ENV_NOM/.verrou"
flock -n 9 || erreur "une sauvegarde de $ENV_NOM est déjà en cours."

ETAPE="préparation"
DOSSIER_CREE="non"
echec() {
	local code=$?
	# Hérité par les sous-shells (set -E : pipelines, coprocessus) : seul le
	# shell principal signale l'échec, une seule fois.
	if [ "$BASHPID" != "$$" ]; then exit "$code"; fi
	trap - ERR
	avert "échec à l'étape « $ETAPE » (code $code)."
	signaler "$PING_URL" down "sauvegarde $ENV_NOM : échec à l'étape $ETAPE"
	if [ -n "${PGSNAP_PID:-}" ]; then kill "$PGSNAP_PID" 2>/dev/null || true; fi
	# Une sauvegarde incomplète ne doit pas être confondue avec une bonne.
	# (seulement le dossier créé par CETTE exécution).
	if [ "$DOSSIER_CREE" = "oui" ]; then mv "$DOSSIER" "$DOSSIER.INCOMPLETE" 2>/dev/null || true; fi
	exit "$code"
}
trap echec ERR

[ ! -e "$DOSSIER" ] || erreur "$DOSSIER existe déjà (deux sauvegardes dans la même seconde ?)."
mkdir "$DOSSIER"
DOSSIER_CREE="oui"
info "Sauvegarde $NOM → $DOSSIER"

# --- 1. Instantané, dump et empreinte ----------------------------------------------
# Une session psql garde une transaction REPEATABLE READ ouverte et exporte son
# instantané : pg_dump et l'empreinte voient exactement les mêmes données, même
# si l'application écrit pendant la sauvegarde.
ETAPE="ouverture de l'instantané"
coproc PGSNAP { pg_outil psql -X -q -A -t -v ON_ERROR_STOP=1 2>&1; }
# Copies des descripteurs : bash efface PGSNAP dès que psql s'arrête.
exec {SNAP_LIRE}<&"${PGSNAP[0]}" {SNAP_ECRIRE}>&"${PGSNAP[1]}"
printf '%s\n' "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;" "SELECT pg_export_snapshot();" >&"$SNAP_ECRIRE"
INSTANTANE=""
read -r -t 60 INSTANTANE <&"$SNAP_LIRE" || true
[[ "$INSTANTANE" =~ ^[0-9A-F]+-[0-9A-F]+(-[0-9]+)?$ ]] ||
	{
		ETAPE="ouverture de l'instantané ($INSTANTANE)"
		false
	}

ETAPE="pg_dump"
pg_outil pg_dump --snapshot="$INSTANTANE" --format=custom --compress=6 --no-sync |
	age --encrypt -R "$DESTINATAIRES" -o "$DOSSIER/base.dump.age"
[ -s "$DOSSIER/base.dump.age" ]

ETAPE="empreinte"
{
	if [ "$EMPREINTE_COMPLETE" = "complete" ]; then
		echo '\set donnees_completes true'
	else
		echo '\set donnees_completes false'
	fi
	cat "$EMPREINTE_SQL"
	echo "SELECT '__FIN_EMPREINTE__';"
} >&"$SNAP_ECRIRE"
EMPREINTE=""
NB_LIGNES=0
ligne=""
while IFS= read -r -t 3600 ligne <&"$SNAP_LIRE"; do
	[ "$ligne" = "__FIN_EMPREINTE__" ] && break
	EMPREINTE+="$ligne"$'\n'
	NB_LIGNES=$((NB_LIGNES + 1))
done
[ "$ligne" = "__FIN_EMPREINTE__" ] || {
	ETAPE="empreinte (psql : ${ligne:-sortie interrompue})"
	false
}
printf '%s\n' "COMMIT;" '\q' >&"$SNAP_ECRIRE"
exec {SNAP_ECRIRE}>&- {SNAP_LIRE}<&-
wait "$PGSNAP_PID" 2>/dev/null || true
PGSNAP_PID=""
grep -q '^table|' <<<"$EMPREINTE" || {
	ETAPE="empreinte (vide)"
	false
}
EMPREINTE_TRIEE="$(LC_ALL=C sort <<<"$EMPREINTE" | sed '/^$/d')"
printf '%s\n' "$EMPREINTE_TRIEE" | age --encrypt -R "$DESTINATAIRES" -o "$DOSSIER/empreinte.txt.age"
NB_TABLES="$(grep -c '^donnees|' <<<"$EMPREINTE_TRIEE" || true)"
NB_EVENEMENTS_AUDIT="$(grep '^donnees|evenement_audit|' <<<"$EMPREINTE_TRIEE" | cut -d'|' -f3 || true)"

# --- 2. Fichiers déposés (volume media) ------------------------------------------
ETAPE="fichiers déposés"
MEDIA="absent"
if [ "$PG_MODE" = "docker" ]; then
	VOLUME_MEDIA="${PROJET}_media"
	if docker volume inspect "$VOLUME_MEDIA" >/dev/null 2>&1; then
		IMAGE_DB="$(docker inspect -f '{{.Config.Image}}' "$DB_CONTENEUR")"
		docker run --rm --network none -v "$VOLUME_MEDIA:/donnees:ro" "$IMAGE_DB" \
			tar -C /donnees -czf - . |
			age --encrypt -R "$DESTINATAIRES" -o "$DOSSIER/media.tar.gz.age"
		MEDIA="media.tar.gz.age"
	fi
elif [ -n "${ALPHA_MEDIA_DIR:-}" ] && [ -d "$ALPHA_MEDIA_DIR" ]; then
	tar -C "$ALPHA_MEDIA_DIR" -czf - . | age --encrypt -R "$DESTINATAIRES" -o "$DOSSIER/media.tar.gz.age"
	MEDIA="media.tar.gz.age"
fi

# --- 3. Manifeste ------------------------------------------------------------------
ETAPE="manifeste"
VERSION_PG="$(pg_outil psql -X -A -t -c 'SHOW server_version' 2>/dev/null | head -n 1 | tr -d '\r' || true)"
{
	echo "# ALPHA — manifeste de sauvegarde (aucun secret)"
	echo "nom=$NOM"
	echo "environnement=$ENV_NOM"
	echo "date_utc=$HORODATAGE"
	echo "motif=$MOTIF"
	echo "hote=$(hostname)"
	echo "version_alpha=$(version_deployee "$ENV_NOM")"
	echo "base=$DB_NOM"
	echo "postgresql=$VERSION_PG"
	echo "format_dump=pg_dump custom (-Fc), compression 6"
	echo "chiffrement=age (X25519), destinataires : $(grep -cE '^(age1|ssh-)' "$DESTINATAIRES") clé(s) publique(s)"
	echo "empreinte=$NB_LIGNES lignes, données $EMPREINTE_COMPLETE"
	echo "tables=$NB_TABLES"
	echo "evenements_audit=${NB_EVENEMENTS_AUDIT:-0}"
	echo "media=$MEDIA"
	echo "# sha256 des fichiers chiffrés (sha256sum -c)"
	(cd "$DOSSIER" && sha256sum -- *.age)
} >"$DOSSIER/manifeste.txt"
TAILLE="$(du -sh "$DOSSIER" | cut -f1)"
ok "sauvegarde locale prête : $TAILLE (${NB_EVENEMENTS_AUDIT:-0} événements d'audit)."

# --- 4. Envoi hors site ------------------------------------------------------------
if [ "$ENVOI" = "oui" ]; then
	ETAPE="envoi hors site"
	ANNEE="${HORODATAGE:0:4}"
	MOIS="${HORODATAGE:4:2}"
	CIBLE="$DESTINATION/$ENV_NOM/$ANNEE/$MOIS/$NOM"
	info "Envoi vers $CIBLE"
	# --immutable : ne jamais écraser un objet existant ; pas de suppression côté
	# distant (la clé d'accès du VPS n'a pas ce droit, voir docs/ops/deploiement.md § 8).
	rclone copy "$DOSSIER" "$CIBLE" --immutable --retries 5 --low-level-retries 10 \
		--stats-one-line --stats 0 -q
	ETAPE="vérification de l'envoi"
	rclone check "$DOSSIER" "$CIBLE" --one-way -q
	# Copie mensuelle (1er du mois) conservée plus longtemps (règle de cycle de
	# vie du préfixe « mensuel/ » sur le stockage).
	if [ "$MOTIF" = "quotidienne" ] && [ "${HORODATAGE:6:2}" = "01" ]; then
		ETAPE="copie mensuelle"
		rclone copy "$DOSSIER" "$DESTINATION/$ENV_NOM/mensuel/$NOM" --immutable -q
	fi
	ok "envoyée et vérifiée hors site."
else
	avert "--sans-envoi : sauvegarde conservée seulement en local ($DOSSIER)."
fi

# --- 5. Rétention locale -------------------------------------------------------------
ETAPE="rétention locale"
find "$SPOOL/$ENV_NOM" -mindepth 1 -maxdepth 1 -type d -name "${PROJET}_*" \
	-mtime +"$RETENTION_LOCALE" -exec rm -rf -- {} + 2>/dev/null || true

trap - ERR
signaler "$PING_URL" up "$NOM $TAILLE"
ok "sauvegarde $NOM terminée."

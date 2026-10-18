#!/usr/bin/env bash
# =============================================================================
# ALPHA — fonctions communes aux scripts d'exploitation du VPS (tâche D3)
#
# Chargé (source) par scripts/deploy.sh, sauvegarde.sh, restauration.sh et
# veille.sh. Ne s'exécute pas seul.
#
# Configuration d'exploitation : /etc/alpha/ops.env (modèle : infra/ops.env.example),
# hors du dépôt, root:root 600. Chemin modifiable par ALPHA_OPS_CONFIG.
# =============================================================================

# shellcheck disable=SC2034  # variables utilisées par les scripts appelants

ALPHA_RACINE="${ALPHA_RACINE:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
ALPHA_ETAT="${ALPHA_ETAT:-$ALPHA_RACINE/.deploiements}"
ALPHA_OPS_CONFIG="${ALPHA_OPS_CONFIG:-/etc/alpha/ops.env}"

if [ -t 2 ]; then
	_C_INFO=$'\033[1;34m' _C_AVERT=$'\033[1;33m' _C_ERR=$'\033[1;31m' _C_OK=$'\033[1;32m' _C_RAZ=$'\033[0m'
else
	_C_INFO='' _C_AVERT='' _C_ERR='' _C_OK='' _C_RAZ=''
fi

horodater() { date -u +%Y-%m-%dT%H:%M:%SZ; }
info() { printf '%s==>%s %s\n' "$_C_INFO" "$_C_RAZ" "$*" >&2; }
ok() { printf '%sOK%s  %s\n' "$_C_OK" "$_C_RAZ" "$*" >&2; }
avert() { printf '%sAttention :%s %s\n' "$_C_AVERT" "$_C_RAZ" "$*" >&2; }
erreur() {
	printf '%sErreur :%s %s\n' "$_C_ERR" "$_C_RAZ" "$*" >&2
	exit 1
}

# Environnements autorisés (projets compose alpha-recette et alpha-prod).
verifier_env_nom() {
	case "${1:-}" in
		recette | prod) ;;
		*) erreur "environnement inconnu « ${1:-} » : attendu recette ou prod." ;;
	esac
}

# Charge /etc/alpha/ops.env s'il existe (variables ALPHA_SAUVEGARDE_*, ALPHA_VEILLE_*…).
# Le fichier doit appartenir à root et ne pas être lisible par les autres :
# il contient les URL de sonde et le chemin des identifiants du stockage hors site.
charger_config_ops() {
	local obligatoire="${1:-oui}"
	if [ ! -f "$ALPHA_OPS_CONFIG" ]; then
		[ "$obligatoire" = "oui" ] &&
			erreur "$ALPHA_OPS_CONFIG introuvable (modèle : infra/ops.env.example, voir docs/ops/deploiement.md § 8)."
		return 0
	fi
	verifier_droits_secret "$ALPHA_OPS_CONFIG"
	# shellcheck disable=SC1090
	set -a && . "$ALPHA_OPS_CONFIG" && set +a
}

# Un fichier de secrets ne doit être lisible que par son propriétaire.
verifier_droits_secret() {
	local f="$1" droits
	droits="$(stat -c '%a' "$f")"
	case "$droits" in
		600 | 400) ;;
		*) erreur "$f a les droits $droits : il contient des secrets, faites « chmod 600 $f »." ;;
	esac
	if grep -q $'\r' "$f"; then
		erreur "$f contient des fins de ligne Windows (CRLF) : « sed -i 's/\\r\$//' $f »."
	fi
}

# Fichier d'environnement compose d'une cible (recette, prod, caddy).
fichier_env() { printf '%s/.env.%s' "$ALPHA_RACINE" "$1"; }

# valeur_env FICHIER NOM : valeur de NOM dans un fichier .env (sans l'exporter ni
# l'interpréter ; les guillemets simples englobants sont retirés).
valeur_env() {
	local v
	v="$(grep -E "^$2=" "$1" | tail -n 1 | cut -d= -f2-)" || true
	v="${v%\'}"
	v="${v#\'}"
	printf '%s' "$v"
}

# Contrôle d'un .env.<cible> avant usage : présent, droits 600, plus aucune
# valeur d'exemple.
verifier_fichier_env() {
	local f
	f="$(fichier_env "$1")"
	[ -f "$f" ] || erreur "$f introuvable : lancez « scripts/deploy.sh secrets $1 » puis complétez-le."
	verifier_droits_secret "$f"
	if grep -nE '^[[:space:]]*[^#[:space:]][^#]*(A_GENERER|A_RENSEIGNER)' "$f" >&2; then
		erreur "$f contient encore des valeurs à générer ou à renseigner (lignes ci-dessus)."
	fi
}

# Version déployée d'un environnement (vide si aucune).
version_deployee() {
	local f="$ALPHA_ETAT/$1/version"
	if [ -f "$f" ]; then cat "$f"; fi
}

# docker compose pour un environnement applicatif. ALPHA_VERSION doit être
# exportée par l'appelant pour les commandes qui créent des conteneurs.
compose_env() {
	local env="$1"
	shift
	docker compose -p "alpha-$env" \
		--project-directory "$ALPHA_RACINE" \
		--env-file "$(fichier_env "$env")" \
		-f "$ALPHA_RACINE/docker-compose.yml" \
		-f "$ALPHA_RACINE/docker-compose.$env.yml" \
		"$@"
}

compose_proxy() {
	docker compose -p alpha-proxy \
		--project-directory "$ALPHA_RACINE" \
		--env-file "$(fichier_env caddy)" \
		-f "$ALPHA_RACINE/docker-compose.proxy.yml" \
		"$@"
}

# Identifiant du conteneur d'un service d'un projet compose (vide s'il ne tourne pas).
conteneur_service() {
	docker ps -q \
		--filter "label=com.docker.compose.project=$1" \
		--filter "label=com.docker.compose.service=$2" | head -n 1
}

# Signale un état à une sonde « push » (docs/ops/monitoring.md) :
#   - Uptime Kuma : URL contenant /api/push/ ; l'état et le message passent
#     dans la requête (?status=up|down&msg=…) ;
#   - Healthchecks.io (ou compatible) : toute autre URL ; succès = POST sur l'URL,
#     échec = POST sur l'URL suivie de /fail ; message dans le corps.
#   signaler URL up|down MESSAGE
# Ne fait jamais échouer l'appelant : une sonde injoignable est seulement signalée.
signaler() {
	local url="${1:-}" statut="$2" message="${3:0:250}"
	[ -n "$url" ] || return 0
	case "$statut" in up | down) ;; *) statut=down ;; esac
	if [[ "$url" == */api/push/* ]]; then
		curl -fsS -m 15 --retry 3 --retry-delay 5 -G "${url%%\?*}" \
			--data-urlencode "status=$statut" \
			--data-urlencode "msg=$message" \
			--data-urlencode "ping=" >/dev/null 2>&1
	else
		[ "$statut" = "down" ] && url="${url%/}/fail"
		curl -fsS -m 15 --retry 3 --retry-delay 5 --data-raw "$message" "$url" >/dev/null 2>&1
	fi || avert "sonde de surveillance injoignable ($statut : $message)."
}

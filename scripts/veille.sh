#!/usr/bin/env bash
# =============================================================================
# ALPHA — veille du VPS : contrôles locaux envoyés à la surveillance externe
# (tâche D3, docs/ops/monitoring.md)
#
#   scripts/veille.sh systeme
#       conteneurs (en marche, sondes de santé), disque, mémoire, âge de la
#       dernière sauvegarde réussie. Lancé toutes les 5 minutes par
#       alpha-veille.timer. Chaque passage envoie « up » ou « down » à la sonde
#       ALPHA_VEILLE_PING_URL : l'ABSENCE de signal (VPS arrêté, systemd ou
#       réseau en panne) déclenche elle aussi l'alerte côté surveillance.
#
#   scripts/veille.sh audit <prod|recette>
#       manage.py verifier_chaine_audit --tous (rôle alpha_app, sous RLS) ;
#       code 2 = chaîne ROMPUE. Lancé chaque nuit par alpha-audit@<env>.timer,
#       en plus de la tâche Celery de 02:00 (qui alerte par e-mail) : si le
#       worker, beat ou le SMTP sont en panne, l'alerte passe quand même.
#
# Codes de sortie : 0 tout va bien, 1 au moins un problème (visible dans
# « systemctl --failed » et journalctl -u alpha-veille).
# Réglages : /etc/alpha/ops.env (modèle : infra/ops.env.example).
# =============================================================================
set -Eeuo pipefail
umask 077

SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
# shellcheck source=scripts/ops-commun.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/ops-commun.sh"

aide() {
	sed -n '2,/^# =====/p' "$SCRIPT" | sed -e 's/^# \{0,1\}//' -e '/^=====/d'
}

PROBLEMES=()
probleme() {
	PROBLEMES+=("$*")
	avert "$*"
}

# --- Conteneurs --------------------------------------------------------------------
# Un projet est « attendu » s'il a déjà été déployé (version enregistrée) ou, pour
# le proxy, si .env.caddy existe. Chaque conteneur d'un projet attendu doit être
# en marche et ne pas être « unhealthy » ; migrate (tâche ponctuelle) est ignoré.
controler_projet() {
	local projet="$1" lignes nom service etat sante redemarrages n=0
	lignes="$(docker ps -a --filter "label=com.docker.compose.project=$projet" \
		--format '{{.Names}}|{{.Label "com.docker.compose.service"}}|{{.State}}' 2>/dev/null || true)"
	if [ -z "$lignes" ]; then
		probleme "$projet : aucun conteneur."
		return 0
	fi
	while IFS='|' read -r nom service etat; do
		[ -n "$nom" ] || continue
		case "$service" in migrate | tests) continue ;; esac
		# Conteneurs « docker compose run » (manage, audit…) : ignorés.
		[ "$(docker inspect -f '{{index .Config.Labels "com.docker.compose.oneoff"}}' "$nom" 2>/dev/null)" = "True" ] && continue
		n=$((n + 1))
		sante="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}' "$nom" 2>/dev/null || echo '?')"
		redemarrages="$(docker inspect -f '{{.RestartCount}}' "$nom" 2>/dev/null || echo 0)"
		if [ "$etat" != "running" ]; then
			probleme "$nom ($projet) : $etat."
		elif [ "$sante" = "unhealthy" ]; then
			probleme "$nom ($projet) : sonde de santé en échec."
		elif [ "${redemarrages:-0}" -gt "${ALPHA_VEILLE_REDEMARRAGES_MAX:-5}" ]; then
			probleme "$nom ($projet) : $redemarrages redémarrages (boucle de plantage ?)."
		fi
	done <<<"$lignes"
	info "$projet : $n conteneur(s) contrôlé(s)."
}

# --- Disque ------------------------------------------------------------------------------
controler_disque() {
	local seuil="${ALPHA_VEILLE_SEUIL_DISQUE_PCT:-85}" chemin racine_docker pct vus=""
	racine_docker="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
	for chemin in / "$racine_docker" "${ALPHA_SAUVEGARDE_SPOOL:-/var/backups/alpha}"; do
		[ -e "$chemin" ] || continue
		# Même système de fichiers déjà contrôlé : on ne le compte qu'une fois.
		local dev
		dev="$(stat -c '%d' "$chemin")"
		case " $vus " in *" $dev "*) continue ;; esac
		vus="$vus $dev"
		pct="$(df --output=pcent "$chemin" | tail -n 1 | tr -dc '0-9')"
		DISQUE_RESUME="${DISQUE_RESUME:-}${DISQUE_RESUME:+ }$chemin=$pct%"
		if [ "$pct" -ge "$seuil" ]; then
			probleme "disque $chemin rempli à $pct % (seuil $seuil %) : scripts/deploy.sh nettoyer, journaux, sauvegardes locales."
		fi
	done
}

# --- Mémoire -------------------------------------------------------------------------------
controler_memoire() {
	local dispo_ko total_ko swap_total swap_libre seuil_mo="${ALPHA_VEILLE_SEUIL_RAM_DISPO_MO:-500}"
	dispo_ko="$(awk '/^MemAvailable:/ { print $2 }' /proc/meminfo)"
	total_ko="$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo)"
	swap_total="$(awk '/^SwapTotal:/ { print $2 }' /proc/meminfo)"
	swap_libre="$(awk '/^SwapFree:/ { print $2 }' /proc/meminfo)"
	MEMOIRE_RESUME="RAM dispo $((dispo_ko / 1024)) Mo/$((total_ko / 1024)) Mo"
	if [ $((dispo_ko / 1024)) -lt "$seuil_mo" ]; then
		probleme "mémoire disponible faible : $((dispo_ko / 1024)) Mo (seuil $seuil_mo Mo)."
	fi
	if [ "${swap_total:-0}" -gt 0 ]; then
		local swap_pct=$(((swap_total - swap_libre) * 100 / swap_total))
		MEMOIRE_RESUME="$MEMOIRE_RESUME, swap $swap_pct %"
		if [ "$swap_pct" -ge "${ALPHA_VEILLE_SEUIL_SWAP_PCT:-60}" ]; then
			probleme "swap utilisé à $swap_pct % : la mémoire manque (docker stats)."
		fi
	fi
	# Conteneurs tués par le noyau faute de mémoire (limite compose atteinte).
	local oom
	oom="$(docker ps -a -q --filter "label=com.docker.compose.project" | xargs -r docker inspect \
		-f '{{if .State.OOMKilled}}{{.Name}}{{end}}' 2>/dev/null | sed '/^$/d' | tr -d '/' | tr '\n' ' ')"
	[ -z "$oom" ] || probleme "conteneur(s) arrêté(s) par manque de mémoire (OOM) : $oom"
}

# --- Dernière sauvegarde réussie (contrôle de secours : la sonde de la
# sauvegarde alerte déjà en cas d'échec ou d'absence) ---------------------------------
controler_sauvegardes() {
	local env age_max_h="${ALPHA_VEILLE_SAUVEGARDE_AGE_MAX_H:-26}" spool="${ALPHA_SAUVEGARDE_SPOOL:-/var/backups/alpha}" derniere age_h
	for env in prod recette; do
		[ -n "$(version_deployee "$env")" ] || continue
		derniere="$(find "$spool/$env" -mindepth 1 -maxdepth 1 -type d -name "alpha-${env}_*" \
			! -name '*.INCOMPLETE' -printf '%T@\n' 2>/dev/null | sort -n | tail -n 1 | cut -d. -f1 || true)"
		if [ -z "$derniere" ]; then
			probleme "$env : aucune sauvegarde locale dans $spool/$env."
			continue
		fi
		age_h=$((($(date +%s) - derniere) / 3600))
		if [ "$age_h" -ge "$age_max_h" ]; then
			probleme "$env : dernière sauvegarde réussie il y a $age_h h (maximum $age_max_h h, perte de données admise 24 h)."
		fi
	done
}

cmd_systeme() {
	charger_config_ops oui
	# Filet de sécurité : une erreur imprévue du script lui-même est signalée
	# (sinon la surveillance ne verrait qu'un silence, ou pire, rien).
	trap 'signaler "${ALPHA_VEILLE_PING_URL:-}" down "veille.sh systeme a échoué (ligne $LINENO), voir journalctl -u alpha-veille"' ERR
	command -v docker >/dev/null 2>&1 || erreur "docker introuvable."
	if ! docker info >/dev/null 2>&1; then
		probleme "le démon Docker ne répond pas."
	else
		local projets="${ALPHA_VEILLE_PROJETS:-}" p
		if [ -z "$projets" ]; then
			[ -f "$(fichier_env caddy)" ] && projets="alpha-proxy"
			for p in recette prod; do
				[ -n "$(version_deployee "$p")" ] && projets="$projets alpha-$p"
			done
		fi
		for p in $projets; do controler_projet "$p"; done
		controler_memoire
	fi
	controler_disque
	controler_sauvegardes

	local resume="${DISQUE_RESUME:-} ; ${MEMOIRE_RESUME:-}"
	if [ "${#PROBLEMES[@]}" -eq 0 ]; then
		signaler "${ALPHA_VEILLE_PING_URL:-}" up "OK $resume"
		ok "veille : aucun problème ($resume)."
		return 0
	fi
	signaler "${ALPHA_VEILLE_PING_URL:-}" down "${#PROBLEMES[@]} problème(s) : ${PROBLEMES[*]}"
	return 1
}

cmd_audit() {
	local env="${1:-}" version sortie code=0 var url
	verifier_env_nom "$env"
	charger_config_ops oui
	var="ALPHA_AUDIT_PING_URL_$(printf '%s' "$env" | tr '[:lower:]' '[:upper:]')"
	url="${!var:-}"
	version="$(version_deployee "$env")"
	if [ -z "$version" ]; then
		info "$env : aucune version déployée, contrôle de la chaîne d'audit sans objet."
		return 0
	fi
	verifier_fichier_env "$env"
	export ALPHA_VERSION="$version"
	info "Vérification des chaînes d'audit de $env (version $version, rôle alpha_app)"
	# Service backend : connexion alpha_app, donc sous RLS (§ 6.4). --no-deps : ne
	# relance ni migrate ni la base.
	sortie="$(compose_env "$env" run --rm --no-deps -T backend \
		python manage.py verifier_chaine_audit --tous 2>&1)" || code=$?
	printf '%s\n' "$sortie" >&2
	case "$code" in
		0)
			signaler "$url" up "chaînes d'audit $env intactes"
			ok "chaînes d'audit de $env intactes."
			;;
		2)
			signaler "$url" down "CHAÎNE D'AUDIT ROMPUE sur $env : $(grep -m1 -i 'ROMPUE' <<<"$sortie" || true)"
			avert "chaîne d'audit ROMPUE sur $env : procédure « que faire si » de docs/ops/deploiement.md § 11."
			return 1
			;;
		*)
			signaler "$url" down "vérification de la chaîne d'audit $env impossible (code $code)"
			avert "vérification impossible (code $code)."
			return 1
			;;
	esac
}

commande="${1:-help}"
shift || true
case "$commande" in
	systeme) cmd_systeme ;;
	audit) cmd_audit "$@" ;;
	help | -h | --help) aide ;;
	*)
		aide
		erreur "commande inconnue : $commande"
		;;
esac

<!-- Généré depuis docs/architecture-sprint1.md -->
## 6. Journal d'audit


### 6.1 Écriture

Point d'entrée unique : `alpha.audit.services.journaliser(action, categorie, *, objet=None, objet_libelle=None, avant=None, apres=None, detail="", acteur=None, etablissement_id=None)`.
- Acteur, IP, user agent et `request_id` sont lus dans le contexte de requête ; `etablissement_id` vaut par défaut le tenant courant, sinon NULL (chaîne plateforme).
- `avant` et `apres` passent par `DjangoJSONEncoder` puis `json.loads` : uniquement des chaînes, entiers, booléens, null, listes et objets (les `Decimal` deviennent des chaînes). Les flottants sont interdits (ValueError).
- **Masquage** : chaque modèle déclare `AUDIT_CHAMPS` (liste blanche des champs journalisés) ; mots de passe, secrets TOTP, codes, jetons et hachages ne sont jamais journalisés.
- Écrit dans la transaction de l'action : l'action et sa trace sont validées ou annulées ensemble.
- Les échecs de connexion sont écrits par des vues qui **retournent** une réponse d'erreur (3.3), ce qui préserve l'événement.

Actions du sprint 1 : `auth.connexion.succes|echec`, `auth.verrouillage`, `auth.deconnexion`, `auth.session.expiree|revoquee`, `auth.mdp.oubli_demande|reinitialise|modifie`, `mfa.active|change|reenrole|codes_regeneres|code_secours_utilise`, `securite.connexion_inhabituelle`, `telephone.signale|reinitialise|annule`, `utilisateur.invite|active|modifie|suspendu|reactive|deverrouille`, `affectation.creee|terminee`, `role.cree|modifie|desactive|active`, `unite.creee|modifiee`, `absence.soumise|validee|refusee|annulee`, `delegation.active|terminee`, `parametres.securite.modifies`, `audit.export|controle`, `plateforme.etablissement.cree|modifie|statut`, `plateforme.administrateur.invite`.

### 6.2 Format canonique et calcul de la chaîne

Le service construit `payload_canonique` :

```python
payload = json.dumps({
    "v": 1,
    "etablissement_id": str | None,
    "horodatage": "2026-10-10T20:31:07.123456Z",   # UTC, microsecondes, suffixe Z
    "acteur_type": ..., "acteur_id": str | None, "acteur_libelle": ...,
    "categorie": ..., "action": ...,
    "objet_type": ..., "objet_id": ..., "objet_libelle": ...,
    "avant": ..., "apres": ..., "detail": ...,
    "ip": str | None, "user_agent": ..., "request_id": str,
}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

Le **trigger** (pas l'application) attribue `seq` et calcule :

```
cle_chaine       = etablissement_id ou 00000000-0000-0000-0000-000000000000 (plateforme)
genese           = hex(SHA-256("ALPHA-GENESIS|" + cle_chaine))
hash_precedent   = hash de l'événement seq-1 de la même chaîne, ou genese si seq = 1
hash             = hex(SHA-256(UTF-8(hash_precedent + "\n" + seq + "\n" + payload_canonique)))
```

Une chaîne par établissement plus une chaîne plateforme. Le verrou consultatif par chaîne sérialise les insertions d'un même établissement sans bloquer les autres.

### 6.3 SQL : chaînage, immutabilité, RLS

```sql
-- Chaînage : SECURITY DEFINER pour voir le dernier maillon même quand la RLS
-- masque la chaîne à l'appelant (ex. échec anonyme écrit dans la chaîne plateforme).
CREATE FUNCTION audit_chainer() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  k uuid := COALESCE(NEW.etablissement_id, '00000000-0000-0000-0000-000000000000'::uuid);
  dernier record;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('alpha.audit:' || k::text, 0));
  SELECT seq, hash INTO dernier FROM evenement_audit
   WHERE COALESCE(etablissement_id, '00000000-0000-0000-0000-000000000000'::uuid) = k
   ORDER BY seq DESC LIMIT 1;
  IF NOT FOUND THEN
    NEW.seq := 1;
    NEW.hash_precedent := encode(sha256(convert_to('ALPHA-GENESIS|' || k::text, 'UTF8')), 'hex');
  ELSE
    NEW.seq := dernier.seq + 1;
    NEW.hash_precedent := dernier.hash;
  END IF;
  NEW.hash := encode(sha256(convert_to(
                NEW.hash_precedent || E'\n' || NEW.seq::text || E'\n' || NEW.payload_canonique, 'UTF8')), 'hex');
  RETURN NEW;
END $$;

CREATE TRIGGER evenement_audit_chainer BEFORE INSERT ON evenement_audit
  FOR EACH ROW EXECUTE FUNCTION audit_chainer();

-- Ajout seul : bloque UPDATE, DELETE et TRUNCATE, y compris pour le propriétaire
CREATE FUNCTION audit_interdire_modification() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'evenement_audit est en ajout seul : % interdit', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER evenement_audit_sans_maj BEFORE UPDATE OR DELETE ON evenement_audit
  FOR EACH ROW EXECUTE FUNCTION audit_interdire_modification();
CREATE TRIGGER evenement_audit_sans_truncate BEFORE TRUNCATE ON evenement_audit
  FOR EACH STATEMENT EXECUTE FUNCTION audit_interdire_modification();

-- Droits : défense en profondeur
REVOKE UPDATE, DELETE, TRUNCATE ON evenement_audit FROM alpha_app;
REVOKE EXECUTE ON FUNCTION audit_chainer() FROM PUBLIC;

-- RLS
ALTER TABLE evenement_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE evenement_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_lecture ON evenement_audit FOR SELECT TO alpha_app
  USING (etablissement_id = app_current_tenant()
         OR (etablissement_id IS NULL AND app_scope() = 'platform'));
CREATE POLICY audit_insertion ON evenement_audit FOR INSERT TO alpha_app
  WITH CHECK (etablissement_id = app_current_tenant() OR etablissement_id IS NULL);
```

Limite assumée : un superutilisateur PostgreSQL peut désactiver les triggers. Ce cas est détecté par la vérification de la chaîne et par les ancres (6.5). Une copie des ancres hors de la base est prévue (point ouvert P7).

Conservation : 10 ans, sans purge au S1. Un partitionnement mensuel sera étudié quand la volumétrie le justifiera ; une partition ne pourra être archivée que selon une procédure documentée et exécutée par `alpha_owner`.

### 6.4 Vérification

Commande : `python manage.py verifier_chaine_audit [--etablissement <code> | --tous | --plateforme] [--depuis-seq N]`, exécutable aussi par la tâche Celery `audit.verifier_chaine(etablissement_id)`.

1. Crée une ligne `controle_integrite_audit` (`EN_COURS`).
2. Parcourt la chaîne par `seq` croissant (curseur serveur, lots de 5 000), sous le contexte de l'établissement (rôle `alpha_app`, donc pas de contournement de la RLS).
3. Pour chaque événement :
   a. `seq` = précédent + 1 (pas de trou) ;
   b. `hash_precedent` = `hash` du précédent (ou genèse) ;
   c. le payload recalculé depuis les **colonnes** est identique à `payload_canonique` (détecte la modification d'une colonne) ;
   d. le SHA-256 recalculé en Python vaut `hash` (détecte la modification du payload).
4. Vérifie que la dernière ancre `INTACTE` (`dernier_seq`, `dernier_hash`) est toujours présente et identique (détecte une troncature en fin de chaîne).
5. Termine avec le statut `INTACTE` (et nouvelle ancre) ou `ROMPUE` (avec `premier_seq_invalide` et le motif). Code de sortie 0 ou 2. En cas de rupture : e-mail immédiat aux titulaires de `audit.lecture` et à l'adresse de sécurité FYXOP, plus un événement `SECURITE`.
6. L'écran « Journal d'audit » affiche le dernier contrôle (« Intégrité vérifiée · Chaîne d'empreintes intacte · contrôle 10/10 20:00 »).

### 6.5 Planification (Celery beat, heure de Dakar)

| Tâche | Fréquence |
|---|---|
| `audit.verifier_toutes_chaines` (une sous-tâche par établissement, plus la chaîne plateforme) | tous les jours à 02:00 |
| `audit.envoyer_ancres` (dernier `seq`/`hash` de chaque chaîne vers l'adresse d'ancrage, P7) | tous les jours à 02:30 |
| `delegations.cloturer_delegations` / `activer_delegations` | toutes les 5 min |
| `comptes.purger_jetons_expires` (marquage, sans suppression des traces) | toutes les heures |
| `comptes.expirer_sessions_inactives` (nettoyage de `session_appareil`, sessions Django expirées) | toutes les 15 min |
| `comptes.reinitialiser_compteurs_verrouillage` (`verrouillages_24h`) | toutes les heures |
| `notifications.resume_quotidien` | toutes les 15 min (envoie aux utilisateurs dont `heure_resume` vient de passer) |

---


<!-- Généré depuis docs/architecture-sprint1.md -->
## 10. Décisions validées (15/10/2026, Souleymane)


Ces décisions remplacent les hypothèses de la section 9.

| # | Décision |
|---|---|
| P1 | E-mail unique sur toute la plateforme. L'isolation multi-tenant est inchangée : l'établissement est déduit du compte à la connexion. Le sous-domaine par client reste une évolution possible. |
| P2 | Durées validées (inactivité 15 min, session max 12 h, invitation 72 h, réinitialisation 30 min, 5 essais → 15 min, 3 verrouillages en 24 h → déblocage admin). Toutes ces durées sont **réglables par établissement** dans `ParametresEtablissement`, avec ces valeurs par défaut. |
| P3 | 12 caractères, 3 catégories sur 4, 5 derniers interdits. Expiration périodique = **réglage par établissement**, désactivé par défaut (la banque pilote peut l'activer à 90 jours). |
| P4 | Réinitialisation du dernier administrateur par le super-admin FYXOP, sur demande écrite signée de la direction du client + appel vidéo avec pièce d'identité. Les références de la demande sont saisies dans l'opération ; l'opération est journalisée et notifiée aux autres administrateurs de l'établissement. |
| P5 | Valideur = responsable hiérarchique, sinon un administrateur. Le délégataire doit détenir des pouvoirs **au moins égaux** à ceux de l'absent ; pas de sous-délégation ; délégation bornée dans le temps. |
| P6 | Accès super-admin : MFA + liste d'IP autorisées si FYXOP a une IP fixe, sinon VPN WireGuard sur le serveur (réglage d'infrastructure, tâche D3). La suspension manuelle d'un établissement par le super-admin reste à confirmer avec FYXOP. |
| P7 | Ancrage quotidien envoyé à deux destinataires : le contrôle interne / auditeur du client (paramètre de l'établissement) et une adresse sécurité FYXOP (paramètre de plateforme). |
| P8 | **Non tranché** : à décider par FYXOP avec la banque pilote. Développement et recette sur Hostinger en attendant ; l'application reste portable (Docker). |
| P9 | Passerelle SMS à choisir avant le 26/11/2026 (sprint 4) : API SMS d'Orange ou agrégateur local avec API REST. |
| P10 | Français seul au sprint 1 ; le sélecteur « English » est masqué tant qu'il n'y a pas de traduction. |
| P11 | Recette : Mailpit protégé par mot de passe, aucun e-mail réel. SMTP réel à partir du pilote. |

**Versions (décision du 15/10/2026, tâche D1)** : Django 5.2 LTS (5.2.18) au lieu de 5.1, qui ne reçoit plus de correctifs de sécurité ; Node 22 LTS au lieu de Node 20, en fin de support. Le reste de la pile est inchangé.

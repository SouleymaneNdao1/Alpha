<!-- Généré depuis docs/architecture-sprint1.md -->
## 9. Points ouverts et hypothèses à valider


| # | Sujet | Hypothèse retenue |
|---|---|---|
| P1 | Identification de l'établissement à la connexion | E-mail **unique sur toute la plateforme**, pas de sous-domaine par client. Alternative : `banque-x.alpha…` |
| P2 | Durées de sécurité | Inactivité 15 min, session max 12 h, invitation 72 h, lien de réinitialisation 30 min, 5 essais → 15 min de verrouillage, 3 verrouillages en 24 h → déblocage par l'administrateur |
| P3 | Politique de mot de passe | 12 caractères, 3 catégories sur 4, 5 derniers interdits, **pas d'expiration périodique** (la banque pilote peut exiger 90 jours) |
| P4 | Téléphone perdu du dernier administrateur | Réinitialisation par le super-admin FYXOP, après vérification d'identité documentée. Quels modes de vérification sont acceptés ? |
| P5 | Validation des absences | Valideur = responsable hiérarchique (`responsable_id`), sinon un administrateur. Le délégataire doit-il détenir le même rôle ou des pouvoirs équivalents ? (au S1 : aucune contrainte) |
| P6 | Super-admin | Restriction d'accès par IP (VPN FYXOP) ? Peut-il suspendre un établissement sans validation commerciale ? |
| P7 | Ancrage du journal | Envoi quotidien des dernières empreintes à une adresse FYXOP sécurité et à l'auditeur interne du client : destinataires à confirmer |
| P8 | Hébergement | Le CDC préconise un hébergement au Sénégal ou dans l'UEMOA (loi 2008-12, CDP) ; Hostinger n'y a pas de datacenter. Recette et production sur le **même** VPS KVM 2 pour le pilote ; un VPS dédié à la production est recommandé |
| P9 | Canaux de notification | SMS et push : préférences enregistrées au S1, envoi au S4 (passerelle SMS à choisir) |
| P10 | Langue | Le sélecteur Français/English est présent, mais seul le français est traduit au S1 |
| P11 | E-mails en recette | Mailpit protégé par mot de passe (aucun e-mail réel) ou SMTP réel avec liste blanche des testeurs ? |

---


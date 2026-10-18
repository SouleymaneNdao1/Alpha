"""Signaux de la boîte « À traiter » (raccordement des notifications, B9).

Envoyés par ``alpha.taches.services``, de façon SYNCHRONE, dans la transaction de
l'action : un récepteur qui écrit une notification in-app est validé ou annulé
avec elle. Un récepteur qui envoie un e-mail doit passer par
``transaction.on_commit`` (§ 3.7).

- ``tache_ouverte(sender=Tache, tache)`` ;
- ``tache_fermee(sender=Tache, tache)`` : ``tache.statut`` vaut TERMINEE ou ANNULEE ;
- ``tache_reassignee(sender=Tache, tache, avant)`` : ``avant`` = ancien destinataire
  ``{"assigne_utilisateur", "assigne_role", "assigne_unite"}`` (identifiants).
"""

from django.dispatch import Signal

tache_ouverte = Signal()
tache_fermee = Signal()
tache_reassignee = Signal()

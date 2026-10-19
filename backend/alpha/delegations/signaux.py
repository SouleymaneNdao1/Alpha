"""Signaux des absences et délégations (raccordement des notifications, B9).

Envoyés de façon SYNCHRONE dans la transaction de l'action (voir
``alpha.taches.signaux`` pour la règle des e-mails).

- ``absence_soumise(sender=Absence, absence, delegation)`` : le valideur a une tâche ;
- ``absence_decidee(sender=Absence, absence, delegation)`` : ``absence.statut`` vaut
  VALIDEE ou REFUSEE ; § 5.4 : notifier le demandeur et, si validée, le délégataire ;
- ``absence_annulee(sender=Absence, absence, delegation)`` ;
- ``delegation_active(sender=Delegation, delegation)`` : entrée en vigueur ;
- ``delegation_terminee(sender=Delegation, delegation)``.
"""

from django.dispatch import Signal

absence_soumise = Signal()
absence_decidee = Signal()
absence_annulee = Signal()
delegation_active = Signal()
delegation_terminee = Signal()

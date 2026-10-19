"""API du journal d'audit : ``/api/v1/audit/`` (architecture § 5.6, tâche B11).

Permissions (``Perm`` : utilisateur d'établissement, MFA, code dans l'un de ses rôles actifs) :
- liste, indicateurs, liste des contrôles : ``audit.lecture`` ;
- export Excel : ``audit.export`` (code distinct, § 5.6) ;
- lancement d'un contrôle : ``audit.lecture`` (§ 5.6 ; il n'existe pas de code ``audit.controle``).

Isolation : la RLS ne laisse voir que la chaîne de l'établissement courant (la chaîne de la
plateforme, ``etablissement_id`` NULL, n'est lisible qu'en portée « platform ») ; chaque
requête filtre aussi explicitement sur l'établissement. Le super-administrateur FYXOP est
refusé (403) : il lit la chaîne plateforme par ``/plateforme/audit`` (B10).
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from alpha.core import contexte
from alpha.core.erreurs import reponse_erreur
from alpha.core.schema_erreurs import erreurs
from alpha.organisation.codes_permission import CodePermission as C
from alpha.organisation.permissions import Perm

from . import export, filtres, tasks
from .libelles import PREFIXES_ADMINISTRATION
from .models import (
    Categorie,
    ControleIntegriteAudit,
    Declencheur,
    StatutControle,
)
from .pagination import PaginationCurseurJournal
from .serializers import (
    ControleSerializer,
    EvenementAuditSerializer,
    IndicateursSerializer,
    LancementControleSerializer,
    presenter_evenement,
)
from .services import journaliser

TAG = "Journal d'audit"
CONTROLE_EN_COURS = "CONTROLE_EN_COURS"
EXPORT_TROP_VOLUMINEUX = "EXPORT_TROP_VOLUMINEUX"
#: Un contrôle « EN_COURS » plus ancien est considéré comme abandonné (worker interrompu).
DELAI_CONTROLE_ABANDONNE = dt.timedelta(hours=1)

LectureAudit = Perm(C.AUDIT_LECTURE)
ExportAudit = Perm(C.AUDIT_EXPORT)

PARAMETRES_FILTRES = [filtres.FiltresJournalSerializer]


def _controles():
    return ControleIntegriteAudit.objects.filter(etablissement_id=contexte.tenant_courant())


class EvenementsVue(GenericAPIView):
    permission_classes = [LectureAudit]
    serializer_class = EvenementAuditSerializer
    pagination_class = PaginationCurseurJournal

    @extend_schema(
        tags=[TAG],
        operation_id="audit_evenements_liste",
        summary="Journal d'audit (plus récent d'abord, pagination par curseur)",
        description="Événements de l'établissement, horodatage décroissant. `next` est l'URL de "
        "la page suivante (curseur opaque), `null` à la fin.",
        parameters=PARAMETRES_FILTRES,
        responses={200: EvenementAuditSerializer(many=True), **erreurs(400)},
    )
    def get(self, request):
        criteres = filtres.lire_filtres(request.query_params)
        qs = filtres.appliquer_filtres(filtres.evenements_de_l_etablissement(), criteres)
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([presenter_evenement(e) for e in page])


class IndicateursVue(GenericAPIView):
    permission_classes = [LectureAudit]
    serializer_class = IndicateursSerializer

    @extend_schema(
        tags=[TAG],
        operation_id="audit_indicateurs",
        summary="Indicateurs du journal (tuiles et carte d'intégrité)",
        description="`evenements_aujourdhui` : depuis minuit (heure de Dakar). "
        "`connexions_echouees_24h` : `auth.connexion.echec`. `actions_administration_24h` : "
        "actions `" + "`, `".join(PREFIXES_ADMINISTRATION) + "`. `dernier_controle` : dernier "
        "contrôle terminé (INTACTE, ROMPUE ou ERREUR).",
        responses={200: IndicateursSerializer, **erreurs()},
    )
    def get(self, request):
        maintenant = timezone.now()
        minuit = timezone.make_aware(dt.datetime.combine(timezone.localdate(), dt.time.min))
        depuis_24h = maintenant - dt.timedelta(hours=24)
        chaine = filtres.evenements_de_l_etablissement()
        administration = Q()
        for prefixe in PREFIXES_ADMINISTRATION:
            administration |= Q(action__startswith=prefixe)

        controles = _controles()
        dernier = controles.exclude(statut=StatutControle.EN_COURS).order_by("-lance_le").first()
        en_cours = controles.filter(
            statut=StatutControle.EN_COURS, lance_le__gte=maintenant - DELAI_CONTROLE_ABANDONNE
        ).exists()
        return Response(
            {
                "evenements_aujourdhui": chaine.filter(horodatage__gte=minuit).count(),
                "connexions_echouees_24h": chaine.filter(
                    action="auth.connexion.echec", horodatage__gte=depuis_24h
                ).count(),
                "actions_administration_24h": chaine.filter(
                    administration, horodatage__gte=depuis_24h
                ).count(),
                "dernier_controle": ControleSerializer(dernier).data if dernier else None,
                "controle_en_cours": en_cours,
            }
        )


class ExportVue(GenericAPIView):
    permission_classes = [ExportAudit]
    serializer_class = EvenementAuditSerializer

    def perform_content_negotiation(self, request, force=False):
        # Un client qui annonce `Accept: …spreadsheetml.sheet` ne doit pas recevoir 406 :
        # les erreurs restent en JSON, le fichier est une HttpResponse directe.
        return super().perform_content_negotiation(request, force=True)

    @extend_schema(
        tags=[TAG],
        operation_id="audit_export_xlsx",
        summary="Export Excel du journal (même filtres que la liste)",
        description=f"Fichier .xlsx : feuille « Journal » (rang croissant) et feuille « Export ». "
        f"Au plus {export.MAX_LIGNES_DEFAUT} lignes, sinon 400 `{EXPORT_TROP_VOLUMINEUX}` "
        "(restreindre les filtres). L'export est lui-même journalisé (`audit.export`).",
        parameters=PARAMETRES_FILTRES,
        responses={
            (200, export.TYPE_MIME_XLSX): OpenApiResponse(
                OpenApiTypes.BINARY, description="Classeur Excel (pièce jointe)."
            ),
            **erreurs(400, r400=f"VALIDATION (filtres) ou {EXPORT_TROP_VOLUMINEUX}."),
        },
    )
    def get(self, request):
        criteres = filtres.lire_filtres(request.query_params)
        evenements = filtres.appliquer_filtres(filtres.evenements_de_l_etablissement(), criteres)
        etablissement = request.user.etablissement
        lisibles = filtres.filtres_lisibles(criteres)
        try:
            contenu, nb = export.generer(
                evenements,
                etablissement=f"{etablissement.raison_sociale} ({etablissement.code})",
                exporte_par=request.user.get_full_name() or str(request.user),
                filtres=lisibles,
            )
        except export.ExportTropVolumineux as erreur:
            return reponse_erreur(
                EXPORT_TROP_VOLUMINEUX,
                f"L'export dépasse {erreur.maximum} lignes : restreignez la période ou les "
                "filtres.",
                details={"maximum": erreur.maximum},
            )
        journaliser(
            "audit.export",
            Categorie.DOCUMENT,
            objet=("audit.journal", None),
            objet_libelle="Journal d'audit (export Excel)",
            apres={"nb_lignes": nb, "filtres": lisibles},
            detail=f"Export Excel du journal : {nb} ligne(s).",
            acteur=request.user,
        )
        reponse = HttpResponse(contenu, content_type=export.TYPE_MIME_XLSX)
        nom = export.nom_de_fichier(etablissement.code)
        reponse["Content-Disposition"] = f'attachment; filename="{nom}"'
        reponse["Cache-Control"] = "no-store"
        return reponse


class ControlesVue(GenericAPIView):
    permission_classes = [LectureAudit]
    serializer_class = ControleSerializer

    @extend_schema(
        tags=[TAG],
        operation_id="audit_controles_liste",
        summary="Contrôles d'intégrité du journal (plus récent d'abord)",
        responses={200: ControleSerializer(many=True), **erreurs()},
    )
    def get(self, request):
        page = self.paginate_queryset(_controles().order_by("-lance_le", "-id"))
        return self.get_paginated_response(ControleSerializer(page, many=True).data)

    @extend_schema(
        tags=[TAG],
        operation_id="audit_controles_lancer",
        summary="Lancer un contrôle d'intégrité (asynchrone)",
        description="Crée un contrôle `EN_COURS` (déclencheur MANUEL) et le confie à Celery. "
        "Suivre son résultat par `GET /audit/controles` ou `GET /audit/indicateurs`. "
        "Un seul contrôle à la fois : 409 `CONTROLE_EN_COURS` sinon.",
        request=None,
        responses={
            202: LancementControleSerializer,
            **erreurs(409, r409=f"{CONTROLE_EN_COURS} : un contrôle est déjà en cours."),
        },
    )
    def post(self, request):
        etablissement_id = contexte.tenant_courant()
        maintenant = timezone.now()
        deja = (
            _controles()
            .filter(
                statut=StatutControle.EN_COURS, lance_le__gte=maintenant - DELAI_CONTROLE_ABANDONNE
            )
            .first()
        )
        if deja is not None:
            return reponse_erreur(
                CONTROLE_EN_COURS,
                "Un contrôle d'intégrité est déjà en cours.",
                statut=status.HTTP_409_CONFLICT,
                details={"id": str(deja.id)},
            )
        controle = ControleIntegriteAudit.objects.create(
            etablissement_id=etablissement_id,
            lance_le=maintenant,
            declencheur=Declencheur.MANUEL,
            statut=StatutControle.EN_COURS,
        )
        journaliser(
            "audit.controle",
            Categorie.SECURITE,
            objet=controle,
            objet_libelle=f"Contrôle du {timezone.localtime(maintenant):%d/%m/%Y %H:%M}",
            detail="Contrôle d'intégrité du journal lancé manuellement.",
            acteur=request.user,
        )
        transaction.on_commit(
            lambda: tasks.executer_controle.delay(str(etablissement_id), str(controle.id))
        )
        return Response(
            {"id": controle.id, "statut": controle.statut}, status=status.HTTP_202_ACCEPTED
        )

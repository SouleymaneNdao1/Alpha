"""Routes ``/api/v1/admin/`` de l'organisation (§ 5.5, tâche B7)."""

from django.urls import path

from . import vues as v

urlpatterns = [
    path("roles", v.RolesVue.as_view(), name="admin-roles"),
    path("roles/<uuid:role_id>", v.RoleVue.as_view(), name="admin-role"),
    path(
        "roles/<uuid:role_id>/desactiver",
        v.DesactiverRoleVue.as_view(),
        name="admin-role-desactiver",
    ),
    path("roles/<uuid:role_id>/activer", v.ActiverRoleVue.as_view(), name="admin-role-activer"),
    path("permissions", v.PermissionsVue.as_view(), name="admin-permissions"),
    path("unites", v.UnitesVue.as_view(), name="admin-unites"),
    path("unites/<uuid:unite_id>", v.UniteVue.as_view(), name="admin-unite"),
]

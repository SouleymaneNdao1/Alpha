"""Routes des notifications, montées sous ``/api/v1/`` (§ 5.3, B9)."""

from django.urls import path

from . import vues

urlpatterns = [
    path(
        "moi/preferences-notification",
        vues.PreferencesNotificationVue.as_view(),
        name="moi-preferences-notification",
    ),
    path("moi/notifications", vues.NotificationsVue.as_view(), name="moi-notifications"),
    # Avant « <uuid> » : « tout-lu » n'est pas un identifiant (et l'uuid est typé).
    path(
        "moi/notifications/tout-lu",
        vues.NotificationsToutLuVue.as_view(),
        name="moi-notifications-tout-lu",
    ),
    path(
        "moi/notifications/<uuid:notification_id>/lue",
        vues.NotificationLueVue.as_view(),
        name="moi-notification-lue",
    ),
]

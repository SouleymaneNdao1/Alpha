from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = "alpha.notifications"
    label = "notifications"
    verbose_name = "Notifications"

    def ready(self) -> None:
        # Récepteurs des signaux des tâches et des délégations (B9).
        from . import recepteurs  # noqa: F401

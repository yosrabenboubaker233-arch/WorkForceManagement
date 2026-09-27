from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "attendance"
    verbose_name = "Pointage & Absences"

    def ready(self):
        import os
        import sys

        # Ne démarre le planificateur que lorsque le serveur tourne
        # réellement (pas pendant migrate/test/shell/makemigrations...),
        # et une seule fois même avec l'auto-reload de `runserver`.
        if "runserver" in sys.argv:
            if os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv:
                from . import scheduler
                scheduler.start()
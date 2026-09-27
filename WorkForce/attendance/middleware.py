import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

_CHECKIN_CACHE_KEY = "attendance:last_workday_check"
_ABSENCE_CACHE_KEY = "attendance:last_detect_absences:%s"  # %s = date du jour
_CHECKIN_INTERVAL_MINUTES = 15


class WorkdayCheckFallbackMiddleware:
    """Déclenche check_workday_alerts / detect_absences depuis une requête
    normale, si le planificateur APScheduler n'a pas pu démarrer (ou n'a
    pas tourné récemment). Ne bloque jamais la requête en cas d'erreur."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # On agit avant de traiter la requête, mais on ne doit JAMAIS
        # empêcher la page de s'afficher si un contrôle échoue.
        if request.user.is_authenticated:
            try:
                self._maybe_run_checks()
            except Exception:
                logger.exception("Échec du filet de sécurité des alertes de pointage.")
        return self.get_response(request)

    def _maybe_run_checks(self):
        now = timezone.localtime()
        today = now.date()

        if today.weekday() < 5 and 8 <= now.hour < 18:
            if cache.get(_CHECKIN_CACHE_KEY) is None:
                from django.core.management import call_command
                call_command("check_workday_alerts")
                cache.set(_CHECKIN_CACHE_KEY, True, timeout=_CHECKIN_INTERVAL_MINUTES * 60)

        if today.weekday() < 5 and now.hour >= 17:
            key = _ABSENCE_CACHE_KEY % today.isoformat()
            if cache.get(key) is None:
                from django.core.management import call_command
                call_command("detect_absences")
                # Ne se relance plus avant demain matin.
                cache.set(key, True, timeout=12 * 3600)
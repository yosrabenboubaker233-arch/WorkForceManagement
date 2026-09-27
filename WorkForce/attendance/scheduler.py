"""
Planificateur intégré à l'application : tant que le serveur Django tourne,
les vérifications de pointage se déclenchent automatiquement, SANS qu'il
soit nécessaire de lancer les commandes à la main ni de configurer une
tâche planifiée externe (cron / Planificateur de tâches Windows).

Deux tâches automatiques :
- `check_workday_alerts` : toutes les 15 minutes, du lundi au vendredi,
  de 8h à 17h (rappel de pointage manquant + détection des retards).
- `detect_absences` : une fois par jour à 17h00, du lundi au vendredi
  (confirmation des absences non justifiées de la journée écoulée).

LIMITE IMPORTANTE (à bien comprendre) : ce planificateur ne peut agir que
pendant que le processus du serveur est en cours d'exécution. Si le serveur
est complètement arrêté toute une journée (ex. le PC est éteint, ou
`runserver` n'a jamais été lancé ce jour-là), rien ne peut être calculé
pour cette journée — ni par ce planificateur, ni par aucune tâche planifiée
externe qui dépendrait elle aussi du PC. Ce n'est pas un bug : c'est la
même contrainte que n'importe quel système automatisé qui a besoin qu'un
processus soit actif pour agir. En cas de coupure, on peut rattraper une
journée passée après coup avec :

    python manage.py check_workday_alerts --date 2026-08-28
    python manage.py detect_absences --date 2026-08-28

Pour un déploiement en production avec plusieurs workers (ex. gunicorn
avec plusieurs process), ce planificateur démarrerait une fois par worker
et déclencherait donc les commandes en double — dans ce cas, préférer un
vrai cron externe (une seule exécution, indépendante du nombre de workers)
plutôt que ce planificateur intégré.
"""
import logging

logger = logging.getLogger(__name__)

_scheduler = None


def start():
    global _scheduler
    if _scheduler is not None:
        return  # déjà démarré dans ce process, ne rien dupliquer

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning(
            "APScheduler n'est pas installé : les vérifications automatiques de "
            "pointage (retard, pointage manquant, absence) ne se déclencheront "
            "PAS toutes seules. Installez-le avec : pip install apscheduler"
        )
        return

    from django.core.management import call_command
    from django.utils import timezone as dj_timezone

    def _run(command_name):
        try:
            call_command(command_name)
        except Exception:
            logger.exception("Échec de l'exécution automatique de '%s'", command_name)

    scheduler = BackgroundScheduler(timezone=str(dj_timezone.get_current_timezone()))

    scheduler.add_job(
        lambda: _run("check_workday_alerts"), "cron",
        day_of_week="mon-fri", hour="8-17", minute="*/15",
        id="check_workday_alerts", replace_existing=True,
    )
    scheduler.add_job(
        lambda: _run("detect_absences"), "cron",
        day_of_week="mon-fri", hour=17, minute=0,
        id="detect_absences", replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Planificateur de pointage démarré : check_workday_alerts toutes les 15 "
        "min (8h-17h) et detect_absences à 17h00, du lundi au vendredi."
    )
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from employees.models import Employee
from attendance.models import Attendance, AbsenceAlert
from leaves.models import LeaveRequest, Authorization
from notifications.models import Notification
from notifications.emailing import send_notification_email

LATE_GRACE_MINUTES = getattr(settings, "LATE_GRACE_MINUTES", 10)
MISSING_CHECKIN_GRACE_HOURS = getattr(settings, "MISSING_CHECKIN_GRACE_HOURS", 1)


class Command(BaseCommand):
    """
    Vérification "en cours de journée" (contrairement à `detect_absences`, qui
    tourne le soir pour figer le statut final) :

    - Si un employé n'a toujours pas pointé son arrivée alors que
      MISSING_CHECKIN_GRACE_HOURS (1h par défaut) s'est écoulée depuis le
      début de sa journée de travail, ET qu'il n'a ni congé ni autorisation
      couvrant cette période :
        -> il reçoit lui-même une notification (application + email)
           "Vous avez oublié de pointer." — envoyée que son COMPTE soit
           actif ou non actif, et quel que soit le statut de son dossier
           employé (actif/inactif) : ce rappel n'est jamais filtré sur
           ces critères.
        -> son manager (et la RH) reçoivent une alerte "absent ce jour".

    - Si l'employé a pointé, mais après l'heure prévue + LATE_GRACE_MINUTES
      (10 min par défaut) :
        -> son statut de pointage du jour passe à "En retard"
        -> LUI-MÊME reçoit une notification "retard enregistré"
        -> son manager (et la RH) reçoivent une alerte "en retard".

    A lancer via cron plusieurs fois pendant la matinée, par exemple :
        */15 8-11 * * 1-5 cd /chemin/du/projet && python manage.py check_workday_alerts

    Idempotent : chaque alerte n'est créée (et donc notifiée) qu'une seule
    fois par employé/jour/type, grâce à la contrainte d'unicité sur
    AbsenceAlert (employee, date, kind).
    """

    help = "Alerte le manager (absent/en retard) et l'employé (pointage oublié / retard) en cours de journée."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, help="Date cible (YYYY-MM-DD), par défaut aujourd'hui.")

    def handle(self, *args, **options):
        target_date = date.fromisoformat(options["date"]) if options.get("date") else timezone.localdate()

        if target_date.weekday() >= 5:
            self.stdout.write("Jour non ouvré.")
            return

        now = timezone.localtime()
        is_today = target_date == timezone.localdate()

        nb_missing, nb_late = 0, 0

        for employee in Employee.objects.select_related("user", "manager__user"):
            # NB : on ne filtre volontairement PAS sur employee.status ni sur
            # user.is_active : le rappel « vous avez oublié de pointer » (et son
            # email automatique) doit être envoyé au salarié que son compte soit
            # actif ou non actif, comme le statut de son dossier employé — seule
            # l'existence d'un congé/autorisation approuvé couvrant la période
            # dispense de l'alerte (cf. logique ci-dessous).
            attendance, _ = Attendance.objects.get_or_create(
                employee=employee, date=target_date,
                defaults={"status": Attendance.Status.ABSENT},
            )

            expected_start = attendance.expected_start
            missing_threshold = datetime.combine(target_date, expected_start) + timedelta(hours=MISSING_CHECKIN_GRACE_HOURS)
            late_threshold = (datetime.combine(target_date, expected_start) + timedelta(minutes=LATE_GRACE_MINUTES)).time()

            # Trop tôt pour juger un pointage manquant sur une date en cours.
            if is_today:
                missing_threshold_aware = timezone.make_aware(missing_threshold) if timezone.is_naive(missing_threshold) else missing_threshold
                if now < missing_threshold_aware:
                    continue

            # --- Congé validé couvrant la date -> rien à signaler ---
            on_leave = LeaveRequest.objects.filter(
                employee=employee, status=LeaveRequest.Status.APPROVED,
                start_date__lte=target_date, end_date__gte=target_date,
            ).exists()
            if on_leave:
                continue

            # --- Autorisation validée couvrant la période de pointage attendue ---
            covering_authorization = Authorization.objects.filter(
                employee=employee, date=target_date, status=Authorization.Status.APPROVED,
                start_time__lte=expected_start, end_time__gte=missing_threshold.time(),
            ).exists()
            if covering_authorization:
                continue

            manager_user = employee.manager.user if employee.manager else None
            hr_users = User.objects.filter(role__in=[User.Role.RH, User.Role.ADMIN])

            if not attendance.check_in:
                # ------------------------------------------------------
                # Pointage manquant depuis plus d'1h : rappel à l'employé
                # + alerte au manager/RH.
                # ------------------------------------------------------
                message = (
                    f"{employee} n'a pas encore pointé son arrivée le {target_date} "
                    f"({MISSING_CHECKIN_GRACE_HOURS}h après le début de journée), "
                    f"sans congé ni autorisation."
                )
                alert, created = AbsenceAlert.objects.get_or_create(
                    employee=employee, date=target_date, kind=AbsenceAlert.Kind.MISSING_CHECKIN,
                    defaults={"message": message},
                )
                if not created:
                    continue
                nb_missing += 1

                # 1) Rappel à l'employé lui-même.
                notif = Notification.objects.create(
                    recipient=employee.user,
                    category=Notification.Category.CHECKIN_MISSED,
                    title="Vous avez oublié de pointer",
                    message=(
                        f"Vous n'avez pas encore pointé votre arrivée aujourd'hui ({target_date}). "
                        f"Merci de régulariser votre pointage ou de contacter votre manager si vous "
                        f"êtes en congé/autorisation non enregistré(e)."
                    ),
                    link="/pointage/checkin/",
                )
                send_notification_email(notif)

                # 2) Alerte au manager + RH.
                for user in {u for u in [manager_user] if u} | set(hr_users):
                    notif = Notification.objects.create(
                        recipient=user,
                        category=Notification.Category.ABSENCE_ALERT,
                        title="Employé absent / pointage manquant",
                        message=message,
                        link="/pointage/alertes/",
                    )
                    send_notification_email(notif)

            elif attendance.check_in > late_threshold:
                # ------------------------------------------------------
                # Pointé, mais en retard : alerte à l'employé + manager/RH.
                # ------------------------------------------------------
                if attendance.status != Attendance.Status.LATE:
                    attendance.status = Attendance.Status.LATE
                    attendance.save(update_fields=["status"])

                message = (
                    f"{employee} est arrivé(e) en retard le {target_date} "
                    f"(pointé à {attendance.check_in.strftime('%H:%M')}, prévu à {expected_start.strftime('%H:%M')})."
                )
                alert, created = AbsenceAlert.objects.get_or_create(
                    employee=employee, date=target_date, kind=AbsenceAlert.Kind.LATE,
                    defaults={"message": message},
                )
                if not created:
                    continue
                nb_late += 1

                # 1) Notification à l'employé lui-même (manquait auparavant :
                #    seuls le manager et la RH étaient prévenus).
                notif = Notification.objects.create(
                    recipient=employee.user,
                    category=Notification.Category.LATE_ALERT,
                    title="Retard de pointage enregistré",
                    message=(
                        f"Vous avez pointé à {attendance.check_in.strftime('%H:%M')} le {target_date}, "
                        f"alors que votre horaire prévoit un début à {expected_start.strftime('%H:%M')}. "
                        f"Ce retard a été enregistré."
                    ),
                    link="/pointage/checkin/",
                )
                send_notification_email(notif)

                # 2) Alerte au manager + RH.
                for user in {u for u in [manager_user] if u} | set(hr_users):
                    notif = Notification.objects.create(
                        recipient=user,
                        category=Notification.Category.LATE_ALERT,
                        title="Employé en retard",
                        message=message,
                        link="/pointage/alertes/",
                    )
                    send_notification_email(notif)

        self.stdout.write(self.style.SUCCESS(
            f"{target_date} : {nb_missing} rappel(s) de pointage manquant, {nb_late} alerte(s) de retard."
        ))
from datetime import date

from django.core.management.base import BaseCommand

from accounts.models import User
from employees.models import Employee
from attendance.models import Attendance, AbsenceAlert
from leaves.models import LeaveRequest, Authorization
from notifications.models import Notification
from notifications.emailing import send_notification_email
from payroll.contract_utils import get_contract_on


class Command(BaseCommand):
    """
    Détection quotidienne des absences — indépendante d'une quelconque
    connexion à l'application (cahier des charges v3 §7) : à exécuter
    chaque jour ouvré via une tâche planifiée (cron), par exemple :

        0 19 * * 1-5 cd /chemin/du/projet && python manage.py detect_absences

    Règle de priorité (§7) :
      1. Congé validé sur la date          -> journée en congé
      2. Autorisation validée couvrant      -> absence justifiée (autorisation)
         la durée de travail du jour
      3. Pointage effectué                  -> présent
      4. Sinon                              -> absent (+ alerte si congé refusé)
    """

    help = "Vérifie chaque employé actif : congé -> autorisation -> pointage -> absence."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str)

    def handle(self, *args, **options):
        target_date = date.fromisoformat(options["date"]) if options.get("date") else date.today()

        if target_date.weekday() >= 5:
            self.stdout.write("Jour non ouvré.")
            return

        created_alerts = 0

        # Employés actifs : le champ réel est `status`, pas `is_active_employee`.
        for employee in Employee.objects.filter(status=Employee.Status.ACTIVE):
            # Un jour sans contrat actif n'est pas un jour de travail attendu :
            # on ne crée même pas de ligne Attendance pour cet employé ce jour-là.
            contract = get_contract_on(employee, target_date)
            if contract is None:
                continue

            attendance, _ = Attendance.objects.get_or_create(
                employee=employee, date=target_date,
                defaults={"status": Attendance.Status.ABSENT},
            )
            standard_hours = contract.hours_per_day

            # --- 1. Congé validé ce jour -> pas d'absence ---
            on_leave = LeaveRequest.objects.filter(
                employee=employee, status=LeaveRequest.Status.APPROVED,
                start_date__lte=target_date, end_date__gte=target_date,
            ).exists()
            if on_leave:
                attendance.status = Attendance.Status.ON_LEAVE
                attendance.save(update_fields=["status"])
                continue

            # --- 2. Autorisation validée couvrant toute la durée de travail ---
            authorization = Authorization.objects.filter(
                employee=employee, date=target_date, status=Authorization.Status.APPROVED,
            ).first()
            if authorization and authorization.duration_hours >= standard_hours:
                attendance.status = Attendance.Status.AUTHORIZED
                attendance.save(update_fields=["status"])
                continue

            # --- 3. A pointé -> présent ---
            if attendance.check_in:
                attendance.status = Attendance.Status.PRESENT
                attendance.save(update_fields=["status"])
                continue

            # --- 4. Ni congé, ni autorisation suffisante, ni pointage -> absence ---
            attendance.status = Attendance.Status.ABSENT
            attendance.save(update_fields=["status"])

            rejected_leave = LeaveRequest.objects.filter(
                employee=employee, status=LeaveRequest.Status.REJECTED,
                start_date__lte=target_date, end_date__gte=target_date,
            ).first()

            message = (
                f"{employee} est absent le {target_date} alors que son congé avait été refusé."
                if rejected_leave else
                f"{employee} est absent le {target_date} sans congé ni autorisation."
            )
            alert, was_created = AbsenceAlert.objects.get_or_create(
                employee=employee, date=target_date, kind=AbsenceAlert.Kind.ABSENCE,
                defaults={"leave_request": rejected_leave, "message": message},
            )
            if not was_created:
                continue
            created_alerts += 1

            # Notification (application + email) au manager ET à la RH,
            # comme l'exige le cahier des charges §7.
            destinataires = set()
            if employee.manager:
                destinataires.add(employee.manager.user)
            destinataires.update(User.objects.filter(role__in=[User.Role.RH, User.Role.ADMIN]))

            for user in destinataires:
                notif = Notification.objects.create(
                    recipient=user,
                    category=Notification.Category.ABSENCE_ALERT,
                    title="Alerte d'absence",
                    message=message,
                    link="/pointage/alertes/",
                )
                send_notification_email(notif)

        self.stdout.write(self.style.SUCCESS(f"{target_date} : {created_alerts} alerte(s) créée(s)."))

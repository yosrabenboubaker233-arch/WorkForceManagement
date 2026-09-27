"""
Commande sure : ajoute UN SEUL employe de demonstration avec un jeu de
donnees juin-aout 2026, sans jamais toucher a un compte, employe, contrat,
conge, autorisation, pointage ou paie existant.

NE TOUCHE PAS :
- ton compte admin/superutilisateur (contrairement a seed_demo) ;
- aucun utilisateur, employe, departement existant (recherche stricte par
  username="demo_presentation") ;
- si "demo_presentation" existe deja (execution precedente), il est
  reutilise tel quel, jamais recree ni ecrase.

Usage (depuis ton dossier reel, WorkForce/), sur toutes les plateformes :
    python manage.py add_demo_employee
"""
from decimal import Decimal
from datetime import date, time, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import User
from employees.models import Employee, Contract, Department
from attendance.models import Attendance
from leaves.models import LeaveType, LeaveRequest, Authorization, PayrollTreatment
from leaves.views import _apply_leave_balance_deduction, _convert_authorization_hours_to_leave
from payroll.models import Salary, SalaryHistory

USERNAME_DEMO = "demo_presentation"


class Command(BaseCommand):
    help = "Ajoute un employé de démonstration (juin-août 2026) sans toucher à aucune donnée existante."

    def handle(self, *args, **options):
        dept_demo, _ = Department.objects.get_or_create(name="[DEMO] Présentation")

        LEAVE_TYPES = [
            ("Congé annuel", True, PayrollTreatment.NO_DEDUCTION, True),
            ("Congé maladie", True, PayrollTreatment.LEGAL_INDEMNITY, False),
        ]
        for name, paid, treatment, reduces in LEAVE_TYPES:
            LeaveType.objects.get_or_create(
                name=name, defaults={"paid": paid, "treatment": treatment, "reduces_annual_balance": reduces},
            )
        lt_annuel = LeaveType.objects.get(name="Congé annuel")
        lt_maladie = LeaveType.objects.get(name="Congé maladie")

        if User.objects.filter(username=USERNAME_DEMO).exists():
            self.stdout.write(f"Le compte '{USERNAME_DEMO}' existe déjà : réutilisé tel quel, rien recréé.")
            demo_user = User.objects.get(username=USERNAME_DEMO)
        else:
            demo_user = User.objects.create_user(
                username=USERNAME_DEMO, password="Demo1234!", first_name="Employé", last_name="[DEMO]",
                role=User.Role.EMPLOYEE, email="demo.presentation@example.com",
            )
            self.stdout.write(self.style.SUCCESS(f"Compte créé : {USERNAME_DEMO} / Demo1234!"))

        employee, created_emp = Employee.objects.get_or_create(
            user=demo_user,
            defaults=dict(department=dept_demo, job_title="[DEMO] Développeur", hire_date=date(2022, 3, 1), leave_balance_days=18),
        )
        if not created_emp:
            self.stdout.write("Dossier Employee de démo déjà existant : réutilisé, valeurs non écrasées.")

        contract, created_contract = Contract.objects.get_or_create(
            employee=employee, contract_type="CDI",
            defaults=dict(
                start_date=date(2022, 3, 1), job_title="[DEMO] Développeur", department=dept_demo,
                base_salary=Decimal("2200.00"), bonuses=Decimal("150.00"), work_time="FULL_TIME", status="ACTIVE",
                weekly_hours=Decimal("40"), hours_per_day=Decimal("8"), work_days="1,2,3,4,5",
            ),
        )
        Salary.objects.get_or_create(employee=employee, defaults={"base_amount": Decimal("2200.00"), "bonus": Decimal("150.00")})

        if not created_contract:
            self.stdout.write("Un contrat existe déjà pour cet employé de démo : données juin-août non re-générées (évite les doublons).")
            self.stdout.write(f"\nConnecte-toi avec : {USERNAME_DEMO} (mot de passe déjà défini précédemment)")
            return

        def next_weekday(d, target_isoweekday):
            while d.isoweekday() != target_isoweekday:
                d += timedelta(days=1)
            return d

        def present(d, start=(8, 0), end=(16, 0)):
            Attendance.objects.update_or_create(
                employee=employee, date=d,
                defaults={"check_in": time(*start), "check_out": time(*end), "status": Attendance.Status.PRESENT},
            )

        ancien_salaire = contract.base_salary
        SalaryHistory.objects.create(
            employee=employee, previous_amount=ancien_salaire, new_amount=ancien_salaire + Decimal("200.00"),
            percentage=Decimal("10.00"), effective_date=date(2026, 7, 1), reason="Augmentation annuelle (démo)",
        )

        d = date(2026, 6, 1)
        while d <= date(2026, 6, 30):
            if d.isoweekday() <= 5:
                present(d)
            d += timedelta(days=1)

        debut_conge = next_weekday(date(2026, 6, 8), 1)
        conge_juin = LeaveRequest.objects.create(
            employee=employee, leave_type=lt_annuel, start_date=debut_conge,
            end_date=debut_conge + timedelta(days=2), status="APPROVED",
        )
        Attendance.objects.filter(employee=employee, date__range=(conge_juin.start_date, conge_juin.end_date)).update(
            status=Attendance.Status.ON_LEAVE, check_in=None, check_out=None,
        )
        _apply_leave_balance_deduction(conge_juin)

        jour_retard = next_weekday(date(2026, 6, 16), 2)
        present(jour_retard, start=(9, 15))
        call_command("check_workday_alerts", date=jour_retard.isoformat())

        samedi_juin = next_weekday(date(2026, 6, 20), 6)
        present(samedi_juin)

        jour_absence_juin = next_weekday(date(2026, 6, 25), 4)
        Attendance.objects.filter(employee=employee, date=jour_absence_juin).delete()
        call_command("detect_absences", date=jour_absence_juin.isoformat())

        jour_auth1 = next_weekday(date(2026, 6, 10), 3)
        auth1 = Authorization.objects.create(
            employee=employee, date=jour_auth1, start_time=time(8, 0), end_time=time(10, 0),
            reason="Rendez-vous médical", status="APPROVED",
        )
        present(jour_auth1, start=(10, 0), end=(16, 0))
        _convert_authorization_hours_to_leave(auth1)

        d = date(2026, 7, 1)
        while d <= date(2026, 7, 31):
            if d.isoweekday() <= 5:
                present(d)
            d += timedelta(days=1)

        debut_maladie = next_weekday(date(2026, 7, 6), 1)
        conge_maladie = LeaveRequest.objects.create(
            employee=employee, leave_type=lt_maladie, start_date=debut_maladie,
            end_date=debut_maladie + timedelta(days=2), status="APPROVED",
        )
        Attendance.objects.filter(employee=employee, date__range=(conge_maladie.start_date, conge_maladie.end_date)).update(
            status=Attendance.Status.ON_LEAVE, check_in=None, check_out=None,
        )
        _apply_leave_balance_deduction(conge_maladie)

        jour_auth2 = next_weekday(date(2026, 7, 14), 2)
        auth2 = Authorization.objects.create(
            employee=employee, date=jour_auth2, start_time=time(13, 0), end_time=time(16, 0),
            reason="Réunion externe", status="APPROVED",
        )
        present(jour_auth2, start=(8, 0), end=(13, 0))
        _convert_authorization_hours_to_leave(auth2)

        jour_absence_juillet = next_weekday(date(2026, 7, 21), 3)
        Attendance.objects.filter(employee=employee, date=jour_absence_juillet).delete()
        call_command("detect_absences", date=jour_absence_juillet.isoformat())

        d = date(2026, 8, 1)
        while d <= date(2026, 8, 27):
            if d.isoweekday() <= 5:
                present(d)
            d += timedelta(days=1)
        # 28/08 volontairement vide.

        jour_auth3 = next_weekday(date(2026, 8, 11), 2)
        auth3 = Authorization.objects.create(
            employee=employee, date=jour_auth3, start_time=time(8, 0), end_time=time(11, 0),
            reason="Formalités administratives", status="APPROVED",
        )
        present(jour_auth3, start=(11, 0), end=(16, 0))
        _convert_authorization_hours_to_leave(auth3)

        employee.refresh_from_db()
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.SUCCESS(f"Employé de démo créé : {employee} — connecte-toi avec {USERNAME_DEMO} / Demo1234!"))
        self.stdout.write(f"Solde de congé final : {employee.leave_balance_days} jours")
        self.stdout.write("28/08/2026 : aucun pointage — pour tester l'alerte en direct.")
        self.stdout.write("=" * 60)

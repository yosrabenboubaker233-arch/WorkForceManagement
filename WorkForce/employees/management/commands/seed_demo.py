from datetime import date

from django.core.management.base import BaseCommand

from accounts.models import User
from employees.models import Department, Employee, Contract
from leaves.models import LeaveType
from payroll.models import Salary


class Command(BaseCommand):
    help = "Génère un jeu de données de démonstration (tous rôles, avec dossier Employee)."

    def handle(self, *args, **options):
        dept, _ = Department.objects.get_or_create(name="Développement")
        dept_rh, _ = Department.objects.get_or_create(name="RH & Administration")
        dept_direction, _ = Department.objects.get_or_create(name="Direction")

        from leaves.models import PayrollTreatment

        # Traitement paie et impact sur le solde annuel — deux questions
        # indépendantes (cf. tableau fourni par le client). `paid` est
        # conservé pour compatibilité mais n'est plus la source utilisée
        # par le calcul de paie ni par la gestion du solde.
        LEAVE_TYPES = [
            ("Congé annuel", True, PayrollTreatment.NO_DEDUCTION, True),
            ("Congé maladie", True, PayrollTreatment.LEGAL_INDEMNITY, False),
            ("Congé maternité", True, PayrollTreatment.LEGAL_INDEMNITY, False),
            ("Congé paternité", True, PayrollTreatment.NO_DEDUCTION, False),
            ("Congé exceptionnel", True, PayrollTreatment.NO_DEDUCTION, False),
            ("Congé sans solde", False, PayrollTreatment.DEDUCTIBLE, False),
            ("Absence justifiée", True, PayrollTreatment.NO_DEDUCTION, False),
            ("Absence non justifiée", False, PayrollTreatment.DEDUCTIBLE, False),
            ("Formation", True, PayrollTreatment.NO_DEDUCTION, False),
            ("Mission professionnelle", True, PayrollTreatment.NO_DEDUCTION, False),
        ]
        for name, paid, treatment, reduces_annual_balance in LEAVE_TYPES:
            LeaveType.objects.update_or_create(
                name=name,
                defaults={"paid": paid, "treatment": treatment, "reduces_annual_balance": reduces_annual_balance},
            )

        # ------------------------------------------------------------------
        # Direction Générale — approuve les demandes des Managers, RH et Paie
        # ------------------------------------------------------------------
        direction_user, created = User.objects.get_or_create(
            username="direction1",
            defaults=dict(first_name="Ali", last_name="Mansour", role=User.Role.DIRECTION, email="direction@workforce-management.com"),
        )
        if created:
            direction_user.set_password("direction123")
            direction_user.save()
        direction_emp, _ = Employee.objects.get_or_create(
            user=direction_user,
            defaults=dict(department=dept_direction, job_title="Directeur Général", hire_date=date(2018, 1, 1)),
        )

        # ------------------------------------------------------------------
        # Super Administrateur — dossier Employee inclus (peut aussi pointer)
        # ------------------------------------------------------------------
        if not User.objects.filter(is_superuser=True).exists():
            admin_user = User.objects.create_superuser("admin", "admin@workforce-management.com", "admin123", role=User.Role.ADMIN)
            self.stdout.write("Superutilisateur: admin / admin123")
        else:
            admin_user = User.objects.filter(is_superuser=True).first()
        Employee.objects.get_or_create(
            user=admin_user,
            defaults=dict(department=dept_rh, job_title="Administrateur système", hire_date=date(2019, 1, 1)),
        )

        # ------------------------------------------------------------------
        # Manager — sans manager direct : ses congés passent par la Direction
        # ------------------------------------------------------------------
        manager_user, created = User.objects.get_or_create(
            username="manager1",
            defaults=dict(first_name="Sami", last_name="Ben Ali", role=User.Role.MANAGER, email="sami@workforce-management.com"),
        )
        if created:
            manager_user.set_password("manager123")
            manager_user.save()
        manager_emp, _ = Employee.objects.get_or_create(
            user=manager_user, defaults=dict(department=dept, job_title="Lead Développeur", hire_date=date(2020, 1, 10))
        )

        # ------------------------------------------------------------------
        # Employé — rattaché au manager ci-dessus : Manager puis RH
        # ------------------------------------------------------------------
        emp_user, created = User.objects.get_or_create(
            username="employe1",
            defaults=dict(first_name="Nour", last_name="Trabelsi", role=User.Role.EMPLOYEE, email="nour@workforce-management.com"),
        )
        if created:
            emp_user.set_password("employe123")
            emp_user.save()
        employee, _ = Employee.objects.get_or_create(
            user=emp_user,
            defaults=dict(manager=manager_emp, department=dept, job_title="Développeuse Django",
                          hire_date=date(2022, 3, 1), leave_balance_days=18),
        )

        # ------------------------------------------------------------------
        # RH — ses propres congés passent par la Direction (pas d'étape RH,
        # elle EST l'étape RH pour les autres).
        # ------------------------------------------------------------------
        rh_user, created = User.objects.get_or_create(
            username="rh1", defaults=dict(first_name="Ines", last_name="Chaabane", role=User.Role.RH, email="rh@workforce-management.com")
        )
        if created:
            rh_user.set_password("rh123456")
            rh_user.save()
        Employee.objects.get_or_create(
            user=rh_user,
            defaults=dict(department=dept_rh, job_title="Responsable RH", hire_date=date(2021, 6, 1)),
        )

        # ------------------------------------------------------------------
        # Paie — mêmes règles que RH : Direction seule.
        # ------------------------------------------------------------------
        payroll_user, created = User.objects.get_or_create(
            username="paie1", defaults=dict(first_name="Karim", last_name="Ayari", role=User.Role.PAYROLL, email="paie@workforce-management.com")
        )
        if created:
            payroll_user.set_password("paie12345")
            payroll_user.save()
        Employee.objects.get_or_create(
            user=payroll_user,
            defaults=dict(department=dept_rh, job_title="Gestionnaire Paie", hire_date=date(2022, 9, 1)),
        )

        Salary.objects.get_or_create(employee=employee, defaults={"base_amount": 2200, "bonus": 150})

        Contract.objects.get_or_create(
            employee=employee, contract_type="CDI",
            defaults=dict(
                start_date=date(2022, 3, 1), job_title="Développeuse Django", department=dept,
                base_salary=2200, bonuses=150, work_time="FULL_TIME", status="ACTIVE",
            ),
        )

        self.stdout.write(self.style.SUCCESS(
            "Comptes créés : admin/admin123, direction1/direction123, manager1/manager123, "
            "employe1/employe123, rh1/rh123456, paie1/paie12345 — tous ont un dossier Employee "
            "et peuvent donc pointer et demander des congés/autorisations."
        ))

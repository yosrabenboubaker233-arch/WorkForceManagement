from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from .forms import ContractForm
from .models import Employee, Department, Contract


class ContractFormTests(TestCase):
    """Etape 8 : le formulaire de contrat propose bien les heures/semaine,
    heures/jour et jours travailles, sans conflit avec le champ modele."""

    def setUp(self):
        self.department = Department.objects.create(name="IT")

    def test_formulaire_valide_avec_jours_travailles(self):
        form = ContractForm(data={
            "contract_type": "CDI", "start_date": "2026-01-01", "job_title": "Dev",
            "department": self.department.pk, "base_salary": "1800", "bonuses": "0",
            "work_time": "FULL_TIME", "weekly_hours": "40", "hours_per_day": "8",
            "work_days_choices": ["1", "2", "3", "4", "5"],
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_save_ecrit_la_chaine_csv_triee(self):
        user = User.objects.create_user(username="sami", password="x", role="EMPLOYEE")
        employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))

        form = ContractForm(data={
            "contract_type": "CDI", "start_date": "2026-01-01", "job_title": "Dev",
            "department": self.department.pk, "base_salary": "1800", "bonuses": "0",
            "work_time": "FULL_TIME", "weekly_hours": "40", "hours_per_day": "8",
            "work_days_choices": ["5", "1", "3"],
        })
        self.assertTrue(form.is_valid(), form.errors)
        contract = form.save(commit=False)
        contract.employee = employee
        contract.save()
        contract.refresh_from_db()
        self.assertEqual(contract.work_days, "1,3,5")
        self.assertEqual(contract.work_days_list, [1, 3, 5])

    def test_cdd_sans_date_de_fin_refuse(self):
        form = ContractForm(data={
            "contract_type": "CDD", "start_date": "2026-01-01", "job_title": "Dev",
            "department": self.department.pk, "base_salary": "1800", "bonuses": "0",
            "work_time": "FULL_TIME", "weekly_hours": "40", "hours_per_day": "8",
            "work_days_choices": ["1", "2", "3", "4", "5"],
        })
        self.assertFalse(form.is_valid())

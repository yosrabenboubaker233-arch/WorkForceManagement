from datetime import date, time
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from employees.models import Employee
from .models import Authorization, LeaveType, PayrollTreatment
from .forms import AuthorizationTreatmentForm


class AuthorizationDurationTests(TestCase):
    """duration_hours doit renvoyer un Decimal (calcul financier), plus un float."""

    def setUp(self):
        user = User.objects.create_user(username="sami", password="x", role="EMPLOYEE")
        self.employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))

    def test_duration_hours_est_decimal(self):
        auth = Authorization.objects.create(
            employee=self.employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(16, 0),
            reason="Test", status="APPROVED",
        )
        self.assertIsInstance(auth.duration_hours, Decimal)
        self.assertEqual(auth.duration_hours, Decimal("8.00"))

    def test_treatment_par_defaut_no_deduction(self):
        auth = Authorization.objects.create(
            employee=self.employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(9, 0),
            reason="Test", status="APPROVED",
        )
        self.assertEqual(auth.treatment, PayrollTreatment.NO_DEDUCTION)


class LeaveTypeTreatmentMigrationTests(TestCase):
    """paid est conserve pour compatibilite ; treatment est la source utilisee
    par le module de paie (migration de donnees testee ici au niveau modele)."""

    def test_creation_directe_avec_treatment(self):
        lt = LeaveType.objects.create(name="Maladie", paid=False, treatment=PayrollTreatment.DEDUCTIBLE)
        self.assertEqual(lt.treatment, PayrollTreatment.DEDUCTIBLE)
        self.assertFalse(lt.paid)


class AuthorizationTreatmentFormTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="sami", password="x", role="EMPLOYEE")
        self.employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))
        self.auth = Authorization.objects.create(
            employee=self.employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(16, 0),
            reason="Test", status="APPROVED",
        )

    def test_modifie_le_traitement_sans_toucher_au_reste(self):
        form = AuthorizationTreatmentForm(data={"treatment": "RECOVERABLE"}, instance=self.auth)
        self.assertTrue(form.is_valid())
        form.save()
        self.auth.refresh_from_db()
        self.assertEqual(self.auth.treatment, PayrollTreatment.RECOVERABLE)
        self.assertEqual(self.auth.status, "APPROVED")  # statut inchange


# =====================================================================
# Nouvelle demande client : solde de conge annuel (26 j/an), conversion
# heures d'autorisation -> jours, traçabilite, pas de double deduction.
# =====================================================================
from employees.models import Contract
from .models import LeaveRequest, LeaveBalanceTransaction
from .views import _apply_leave_balance_deduction, _convert_authorization_hours_to_leave


def make_employee_with_contract(username, hours_per_day="8", leave_balance_days=None):
    user = User.objects.create_user(username=username, password="x", role="EMPLOYEE")
    employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))
    if leave_balance_days is not None:
        employee.leave_balance_days = Decimal(leave_balance_days)
        employee.save(update_fields=["leave_balance_days"])
    Contract.objects.create(
        employee=employee, contract_type="CDI", start_date=date(2026, 1, 1), job_title="Dev",
        base_salary=Decimal("1800.00"), hours_per_day=Decimal(hours_per_day),
    )
    return employee


class AnnualLeaveBalanceDefaultTests(TestCase):
    def test_defaut_26_jours(self):
        user = User.objects.create_user(username="new_emp", password="x", role="EMPLOYEE")
        employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))
        self.assertEqual(employee.leave_balance_days, Decimal("26.0"))


class LeaveBalanceDeductionRulesTests(TestCase):
    """Impact paie et impact solde annuel sont deux questions independantes (§1)."""

    def setUp(self):
        self.employee = make_employee_with_contract("sami", leave_balance_days="26")

    def _leave(self, lt, start, end):
        return LeaveRequest.objects.create(
            employee=self.employee, leave_type=lt, start_date=start, end_date=end, status="APPROVED",
        )

    def test_conge_annuel_reduit_le_solde(self):
        lt = LeaveType.objects.create(name="Congé annuel", treatment=PayrollTreatment.NO_DEDUCTION, reduces_annual_balance=True)
        leave = self._leave(lt, date(2026, 3, 2), date(2026, 3, 3))  # 2 jours
        _apply_leave_balance_deduction(leave)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("24"))
        txn = LeaveBalanceTransaction.objects.get(employee=self.employee, source=LeaveBalanceTransaction.Source.LEAVE_REQUEST)
        self.assertEqual(txn.days_converted, Decimal("2"))
        self.assertEqual(txn.balance_before, Decimal("26"))
        self.assertEqual(txn.balance_after, Decimal("24"))

    def test_conge_maladie_ne_reduit_pas_le_solde(self):
        lt = LeaveType.objects.create(name="Congé maladie", treatment=PayrollTreatment.NO_DEDUCTION, reduces_annual_balance=False)
        leave = self._leave(lt, date(2026, 3, 2), date(2026, 3, 5))
        _apply_leave_balance_deduction(leave)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("26"))

    def test_maternite_ne_reduit_pas_le_solde(self):
        lt = LeaveType.objects.create(name="Maternité", treatment=PayrollTreatment.NO_DEDUCTION, reduces_annual_balance=False)
        leave = self._leave(lt, date(2026, 3, 2), date(2026, 3, 10))
        _apply_leave_balance_deduction(leave)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("26"))

    def test_sans_solde_ne_reduit_pas_le_solde_annuel(self):
        lt = LeaveType.objects.create(name="Congé sans solde", treatment=PayrollTreatment.DEDUCTIBLE, reduces_annual_balance=False)
        leave = self._leave(lt, date(2026, 3, 2), date(2026, 3, 2))
        _apply_leave_balance_deduction(leave)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("26"))  # payé/déductible != impact solde

    def test_aucune_transaction_si_pas_dimpact(self):
        lt = LeaveType.objects.create(name="Formation", treatment=PayrollTreatment.NO_DEDUCTION, reduces_annual_balance=False)
        leave = self._leave(lt, date(2026, 3, 2), date(2026, 3, 2))
        _apply_leave_balance_deduction(leave)
        self.assertEqual(LeaveBalanceTransaction.objects.filter(employee=self.employee).count(), 0)


class AuthorizationToLeaveConversionTests(TestCase):
    """Conversion heures d'autorisation -> jours de conge, selon hours_per_day
    du contrat, avec report des heures non completes (§3, §4)."""

    def setUp(self):
        self.employee = make_employee_with_contract("sami", hours_per_day="8", leave_balance_days="26")

    def _auth(self, start, end, d=date(2026, 3, 2)):
        return Authorization.objects.create(
            employee=self.employee, date=d, start_time=time(*start), end_time=time(*end),
            reason="Test", status="APPROVED",
        )

    def test_cumul_2h_3h_3h_egale_8h_convertit_1_jour(self):
        self._convertir((8, 0), (10, 0))   # 2h
        self._convertir((10, 0), (13, 0))  # 3h
        self._convertir((13, 0), (16, 0))  # 3h -> cumul 8h

        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("25"))       # -1 jour
        self.assertEqual(self.employee.authorization_hours_carry, Decimal("0"))  # rien en report

    def _convertir(self, start, end):
        auth = self._auth(start, end)
        _convert_authorization_hours_to_leave(auth)
        return auth

    def test_hours_per_day_non_code_en_dur_7h(self):
        employee = make_employee_with_contract("autre", hours_per_day="7", leave_balance_days="26")
        auth = Authorization.objects.create(
            employee=employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(15, 0),  # 7h
            reason="Test", status="APPROVED",
        )
        _convert_authorization_hours_to_leave(auth)
        employee.refresh_from_db()
        self.assertEqual(employee.leave_balance_days, Decimal("25"))  # 7h = 1 jour ici, pas 8h

    def test_reste_conserve_en_report(self):
        auth = self._auth((8, 0), (13, 0))  # 5h
        _convert_authorization_hours_to_leave(auth)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("26"))  # pas encore 1 jour
        self.assertEqual(self.employee.authorization_hours_carry, Decimal("5.00"))

        auth2 = self._auth((8, 0), (11, 0), d=date(2026, 3, 3))  # +3h -> cumul 8h
        _convert_authorization_hours_to_leave(auth2)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("25"))
        self.assertEqual(self.employee.authorization_hours_carry, Decimal("0"))

    def test_10h_donne_1_jour_et_2h_de_reste(self):
        auth = Authorization.objects.create(
            employee=self.employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(18, 0),  # 10h
            reason="Test", status="APPROVED",
        )
        _convert_authorization_hours_to_leave(auth)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.leave_balance_days, Decimal("25"))
        self.assertEqual(self.employee.authorization_hours_carry, Decimal("2.00"))

    def test_pas_de_double_deduction_treatment_force_no_deduction(self):
        auth = Authorization.objects.create(
            employee=self.employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(16, 0),
            reason="Test", status="APPROVED", treatment=PayrollTreatment.DEDUCTIBLE,
        )
        _convert_authorization_hours_to_leave(auth)
        auth.refresh_from_db()
        self.assertEqual(auth.treatment, PayrollTreatment.NO_DEDUCTION)

    def test_traçabilite_transaction_creee(self):
        auth = self._auth((8, 0), (16, 0))  # 8h
        _convert_authorization_hours_to_leave(auth)
        txn = LeaveBalanceTransaction.objects.get(employee=self.employee, source=LeaveBalanceTransaction.Source.AUTHORIZATION)
        self.assertEqual(txn.hours_consumed, Decimal("8.00"))
        self.assertEqual(txn.days_converted, Decimal("1"))
        self.assertEqual(txn.balance_before, Decimal("26"))
        self.assertEqual(txn.balance_after, Decimal("25"))

    def test_valeurs_decimal(self):
        auth = self._auth((8, 0), (10, 30))
        _convert_authorization_hours_to_leave(auth)
        self.employee.refresh_from_db()
        self.assertIsInstance(self.employee.authorization_hours_carry, Decimal)

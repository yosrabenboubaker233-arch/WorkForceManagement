"""
Tests automatises pour attendance - etape 9.

Couvre le bug corrige dans detect_absences (comparaison Decimal/float qui
plantait, heures issues du vrai contrat au lieu d'une plage horaire fixe) et
l'ordre de priorite conge > autorisation > pointage > absent.
"""
from datetime import date, time
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from accounts.models import User
from employees.models import Employee, Contract
from attendance.models import Attendance
from leaves.models import LeaveType, LeaveRequest, Authorization, PayrollTreatment


def make_employee(username, hours_per_day="8"):
    user = User.objects.create_user(username=username, password="x", role="EMPLOYEE")
    employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))
    Contract.objects.create(
        employee=employee, contract_type="CDI", start_date=date(2026, 1, 1), job_title="Dev",
        base_salary=Decimal("1800.00"), hours_per_day=Decimal(hours_per_day),
    )
    return employee


class DetectAbsencesCommandTests(TestCase):

    def test_pas_de_crash_avec_horaire_non_standard(self):
        """Le bug d'origine comparait un Decimal (duration_hours) a un float
        (plage horaire fixe 9h-17h) : ca plantait des que le contrat avait
        des heures/jour non entieres."""
        employee = make_employee("sami", hours_per_day="7.5")
        try:
            call_command("detect_absences", date="2026-03-03")
        except TypeError:
            self.fail("detect_absences a plante sur la comparaison Decimal/float")

    def test_absent_sans_rien(self):
        employee = make_employee("sami")
        call_command("detect_absences", date="2026-03-03")  # mardi
        att = Attendance.objects.get(employee=employee, date=date(2026, 3, 3))
        self.assertEqual(att.status, Attendance.Status.ABSENT)

    def test_present_avec_pointage(self):
        employee = make_employee("sami")
        Attendance.objects.create(
            employee=employee, date=date(2026, 3, 3), check_in=time(8, 0), check_out=time(17, 0),
        )
        call_command("detect_absences", date="2026-03-03")
        att = Attendance.objects.get(employee=employee, date=date(2026, 3, 3))
        self.assertEqual(att.status, Attendance.Status.PRESENT)

    def test_conge_prioritaire_sur_absence(self):
        employee = make_employee("sami")
        lt = LeaveType.objects.create(name="Conge paye", treatment=PayrollTreatment.NO_DEDUCTION)
        LeaveRequest.objects.create(
            employee=employee, leave_type=lt, start_date=date(2026, 3, 3),
            end_date=date(2026, 3, 3), status="APPROVED",
        )
        call_command("detect_absences", date="2026-03-03")
        att = Attendance.objects.get(employee=employee, date=date(2026, 3, 3))
        self.assertEqual(att.status, Attendance.Status.ON_LEAVE)

    def test_autorisation_couvrant_la_journee_prioritaire_sur_absence(self):
        employee = make_employee("sami")
        Authorization.objects.create(
            employee=employee, date=date(2026, 3, 3), start_time=time(8, 0), end_time=time(16, 0),
            reason="Formation externe", status="APPROVED",
        )
        call_command("detect_absences", date="2026-03-03")
        att = Attendance.objects.get(employee=employee, date=date(2026, 3, 3))
        self.assertEqual(att.status, Attendance.Status.AUTHORIZED)

    def test_employe_sans_contrat_est_ignore(self):
        user = User.objects.create_user(username="sans_contrat", password="x", role="EMPLOYEE")
        employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))
        call_command("detect_absences", date="2026-03-03")
        self.assertFalse(Attendance.objects.filter(employee=employee, date=date(2026, 3, 3)).exists())

    def test_weekend_ignore(self):
        make_employee("sami")
        call_command("detect_absences", date="2026-03-07")  # samedi
        self.assertEqual(Attendance.objects.filter(date=date(2026, 3, 7)).count(), 0)


# =====================================================================
# Nouvelle demande client (§7-9) : MISSING_CHECKIN != ABSENCE_NON_JUSTIFIEE,
# resolution automatique de l'alerte des qu'un pointage tardif arrive.
# =====================================================================
from attendance.models import AbsenceAlert
from attendance.views import _resolve_missing_checkin_alert


class MissingCheckinVsAbsenceTests(TestCase):
    """§7-9 : un pointage manquant en cours de journee n'est PAS une absence
    non justifiee tant que la journee n'est pas terminee, et les deux types
    d'alerte sont bien distincts."""

    def setUp(self):
        self.employee = make_employee("sami")

    def test_missing_checkin_distinct_de_absence(self):
        """Les deux Kind existent et peuvent coexister le meme jour sans
        se marcher dessus (contrainte d'unicite sur (employee, date, kind))."""
        d = date(2026, 3, 3)
        alert1 = AbsenceAlert.objects.create(
            employee=self.employee, date=d, kind=AbsenceAlert.Kind.MISSING_CHECKIN, message="rappel",
        )
        alert2 = AbsenceAlert.objects.create(
            employee=self.employee, date=d, kind=AbsenceAlert.Kind.ABSENCE, message="absence confirmee",
        )
        self.assertNotEqual(alert1.kind, alert2.kind)
        self.assertEqual(AbsenceAlert.objects.filter(employee=self.employee, date=d).count(), 2)

    def test_pointage_tardif_resout_lalerte_missing_checkin(self):
        d = date(2026, 3, 3)
        alert = AbsenceAlert.objects.create(
            employee=self.employee, date=d, kind=AbsenceAlert.Kind.MISSING_CHECKIN,
            message="rappel", resolved=False,
        )
        attendance = Attendance.objects.create(
            employee=self.employee, date=d, check_in=time(9, 15), status=Attendance.Status.PRESENT,
        )
        _resolve_missing_checkin_alert(attendance)
        alert.refresh_from_db()
        self.assertTrue(alert.resolved)

    def test_pointage_ne_touche_pas_lalerte_absence_finale(self):
        """Une alerte ABSENCE (fin de journee, deja confirmee) n'est jamais
        resolue par un pointage : seule MISSING_CHECKIN l'est."""
        d = date(2026, 3, 3)
        absence_alert = AbsenceAlert.objects.create(
            employee=self.employee, date=d, kind=AbsenceAlert.Kind.ABSENCE, message="absence", resolved=False,
        )
        attendance = Attendance.objects.create(
            employee=self.employee, date=d, check_in=time(9, 15), status=Attendance.Status.PRESENT,
        )
        _resolve_missing_checkin_alert(attendance)
        absence_alert.refresh_from_db()
        self.assertFalse(absence_alert.resolved)

    def test_sans_alerte_prealable_ne_plante_pas(self):
        attendance = Attendance.objects.create(
            employee=self.employee, date=date(2026, 3, 3), check_in=time(8, 5), status=Attendance.Status.PRESENT,
        )
        _resolve_missing_checkin_alert(attendance)  # ne doit pas lever d'exception

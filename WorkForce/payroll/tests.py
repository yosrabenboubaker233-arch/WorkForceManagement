"""
Tests automatises - etape 9 du plan valide avec le client.

Couvre : jours ouvrables/heures prevues, resolution contrat/SalaryHistory par
date, heures supplementaires (cas 1 et 2 du client, semaine a cheval sur deux
mois, limite interne), deduction d'absences motif par motif, generation
complete du bulletin (exemples exacts du cahier des charges), et surtout la
non-regression : un bulletin deja valide ne doit jamais changer.
"""
from datetime import date, time, timedelta
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from employees.models import Employee, Contract
from attendance.models import Attendance, AbsenceAlert
from leaves.models import LeaveType, LeaveRequest, Authorization, PayrollTreatment
from payroll.models import Salary, SalaryHistory, PayslipRecord, PayrollPolicy
from payroll.calendar_utils import nb_jours_ouvrables_mois, heures_prevues_mois, is_jour_ferie, is_jour_repos
from payroll.contract_utils import get_contract_on, get_effective_base_salary, get_effective_contract_terms
from payroll.utils import compute_overtime_hours, compute_absence_deduction, build_payslip


def make_employee(username, base_salary="1800.00", weekly_hours="40", hours_per_day="8",
                   work_days="1,2,3,4,5", start_date=date(2026, 1, 1)):
    user = User.objects.create_user(username=username, password="x", role="EMPLOYEE")
    employee = Employee.objects.create(user=user, hire_date=start_date)
    Contract.objects.create(
        employee=employee, contract_type="CDI", start_date=start_date, job_title="Dev",
        base_salary=Decimal(base_salary), weekly_hours=Decimal(weekly_hours),
        hours_per_day=Decimal(hours_per_day), work_days=work_days,
    )
    return employee


def make_attendance(employee, a_date, start, end):
    return Attendance.objects.create(
        employee=employee, date=a_date, check_in=time(*start), check_out=time(*end),
    )


class CalendarUtilsTests(TestCase):
    """Heures prevues du mois = jours ouvrables x heures/jour (cahier des charges)."""

    def setUp(self):
        self.employee = make_employee("sami")

    def test_exemples_cahier_des_charges(self):
        self.assertEqual(nb_jours_ouvrables_mois(self.employee, 2026, 3), 22)
        self.assertEqual(heures_prevues_mois(self.employee, 2026, 3), Decimal("176"))
        self.assertEqual(nb_jours_ouvrables_mois(self.employee, 2026, 8), 21)
        self.assertEqual(heures_prevues_mois(self.employee, 2026, 8), Decimal("168"))

    def test_jour_ferie_reduit_les_jours_ouvrables(self):
        from payroll.models import PublicHoliday
        PublicHoliday.objects.create(date=date(2026, 3, 20), label="Fete nationale")
        self.assertEqual(nb_jours_ouvrables_mois(self.employee, 2026, 3), 21)
        self.assertTrue(is_jour_ferie(date(2026, 3, 20)))

    def test_jour_de_repos(self):
        self.assertTrue(is_jour_repos(self.employee, date(2026, 3, 7)))
        self.assertFalse(is_jour_repos(self.employee, date(2026, 3, 9)))

    def test_employe_sans_contrat_actif_nest_pas_ouvrable(self):
        user = User.objects.create_user(username="sans_contrat", password="x", role="EMPLOYEE")
        employee = Employee.objects.create(user=user, hire_date=date(2026, 1, 1))
        self.assertEqual(nb_jours_ouvrables_mois(employee, 2026, 3), 0)
        self.assertEqual(heures_prevues_mois(employee, 2026, 3), Decimal("0"))


class ContractSalaryResolutionTests(TestCase):
    """Le contrat garde ses donnees legales ; les augmentations vivent dans
    SalaryHistory avec une date d'effet - jamais l'inverse."""

    def setUp(self):
        self.employee = make_employee("sami")

    def test_salaire_avant_pendant_apres_augmentation(self):
        SalaryHistory.objects.create(
            employee=self.employee, previous_amount=Decimal("1800.00"), new_amount=Decimal("2000.00"),
            percentage=Decimal("11.11"), effective_date=date(2026, 7, 1), reason="Augmentation annuelle",
        )
        self.assertEqual(get_effective_base_salary(self.employee, date(2026, 6, 30)), Decimal("1800.00"))
        self.assertEqual(get_effective_base_salary(self.employee, date(2026, 7, 1)), Decimal("2000.00"))
        self.assertEqual(get_effective_base_salary(self.employee, date(2026, 12, 1)), Decimal("2000.00"))

    def test_contrat_non_modifie_par_une_augmentation(self):
        contract = get_contract_on(self.employee, date(2026, 1, 1))
        SalaryHistory.objects.create(
            employee=self.employee, previous_amount=Decimal("1800.00"), new_amount=Decimal("2000.00"),
            percentage=Decimal("11.11"), effective_date=date(2026, 7, 1), reason="Augmentation",
        )
        contract.refresh_from_db()
        self.assertEqual(contract.base_salary, Decimal("1800.00"))
        self.assertEqual(contract.contract_type, "CDI")
        self.assertIsNone(contract.end_date)

    def test_salary_base_amount_resynchronise_automatiquement(self):
        salary = Salary.objects.get(employee=self.employee)
        self.assertEqual(salary.base_amount, Decimal("1800.00"))

        SalaryHistory.objects.create(
            employee=self.employee, previous_amount=Decimal("1800.00"), new_amount=Decimal("2500.00"),
            percentage=Decimal("38.89"), effective_date=date(2026, 2, 1), reason="Test",
        )
        salary.refresh_from_db()
        self.assertEqual(salary.base_amount, Decimal("2500.00"))

    def test_employe_sans_contrat_ni_historique(self):
        user = User.objects.create_user(username="legacy", password="x", role="EMPLOYEE")
        employee = Employee.objects.create(user=user, hire_date=date(2020, 1, 1))
        self.assertIsNone(get_effective_base_salary(employee, date(2026, 1, 1)))
        self.assertIsNone(get_effective_contract_terms(employee, date(2026, 1, 1)))


class OvertimeCalculationTests(TestCase):
    """Heures supplementaires : analyse hebdomadaire, jamais 'samedi = sup'
    par principe (cas 1 et 2 fournis par le client)."""

    def setUp(self):
        self.employee = make_employee("sami")

    def test_cas_1_samedi_travaille_avec_semaine_complete(self):
        for i in range(5):
            make_attendance(self.employee, date(2026, 3, 2 + i), (8, 0), (17, 0))
        make_attendance(self.employee, date(2026, 3, 7), (8, 0), (17, 0))

        r = compute_overtime_hours(self.employee, 2026, 3)
        self.assertEqual(r["normal_hours"], Decimal("40.00"))
        self.assertEqual(r["overtime_tier1_hours"], Decimal("8.00"))
        self.assertEqual(r["overtime_tier2_hours"], Decimal("0"))
        self.assertEqual(r["total_worked_hours"], Decimal("48.00"))
        self.assertEqual(len(r["weekly_alerts"]), 1)

    def test_cas_2_semaine_incomplete_avec_samedi_pas_dheures_sup(self):
        for i in range(4):
            make_attendance(self.employee, date(2026, 3, 9 + i), (8, 0), (17, 0))
        make_attendance(self.employee, date(2026, 3, 14), (8, 0), (17, 0))

        r = compute_overtime_hours(self.employee, 2026, 3)
        self.assertEqual(r["normal_hours"], Decimal("40.00"))
        self.assertEqual(r["overtime_tier1_hours"], Decimal("0"))
        self.assertEqual(len(r["weekly_alerts"]), 0)

    def test_semaine_a_cheval_sur_deux_mois(self):
        for i in range(5):
            make_attendance(self.employee, date(2026, 7, 27) + timedelta(days=i), (8, 0), (16, 0))
        make_attendance(self.employee, date(2026, 8, 1), (8, 0), (16, 0))

        juillet = compute_overtime_hours(self.employee, 2026, 7)
        aout = compute_overtime_hours(self.employee, 2026, 8)

        self.assertEqual(juillet["normal_hours"], Decimal("40.00"))
        self.assertEqual(juillet["overtime_tier1_hours"], Decimal("0"))
        self.assertEqual(juillet["total_worked_hours"], Decimal("40.00"))

        self.assertEqual(aout["normal_hours"], Decimal("0"))
        self.assertEqual(aout["overtime_tier1_hours"], Decimal("8.00"))
        self.assertEqual(aout["total_worked_hours"], Decimal("8.00"))

        self.assertEqual(juillet["total_worked_hours"] + aout["total_worked_hours"], Decimal("48.00"))

    def test_heures_sup_en_decimal_jamais_float(self):
        make_attendance(self.employee, date(2026, 3, 2), (8, 0), (17, 0))
        r = compute_overtime_hours(self.employee, 2026, 3)
        for key in ("normal_hours", "overtime_tier1_hours", "overtime_tier2_hours", "total_worked_hours"):
            self.assertIsInstance(r[key], Decimal)


class AbsenceDeductionTests(TestCase):
    """Aucune deduction automatique et uniforme : le motif determine le
    traitement (NO_DEDUCTION / DEDUCTIBLE / RECOVERABLE)."""

    def setUp(self):
        self.employee = make_employee("sami")
        self.hourly_rate = Decimal("10.714")

    def _remplir_mars_sauf(self, jour_exclu):
        """Marque tous les jours ouvrables de mars 2026 comme travailles,
        sauf jour_exclu, pour isoler le motif teste sur ce seul jour (sinon
        les autres jours, sans aucune trace, tomberaient dans le repli
        DEDUCTIBLE par defaut et fausseraient le total)."""
        d = date(2026, 3, 1)
        while d.month == 3:
            if d.isoweekday() <= 5 and d != jour_exclu:
                make_attendance(self.employee, d, (8, 0), (17, 0))
            d += timedelta(days=1)

    def test_conge_paye_aucune_deduction(self):
        self._remplir_mars_sauf(date(2026, 3, 2))
        lt = LeaveType.objects.create(name="Conge paye", treatment=PayrollTreatment.NO_DEDUCTION)
        LeaveRequest.objects.create(
            employee=self.employee, leave_type=lt, start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2), status="APPROVED",
        )
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertEqual(r["deductible_hours"], Decimal("0"))
        self.assertEqual(r["no_deduction_hours"], Decimal("8"))

    def test_conge_sans_solde_deductible(self):
        self._remplir_mars_sauf(date(2026, 3, 2))
        lt = LeaveType.objects.create(name="Conge sans solde", treatment=PayrollTreatment.DEDUCTIBLE)
        LeaveRequest.objects.create(
            employee=self.employee, leave_type=lt, start_date=date(2026, 3, 2),
            end_date=date(2026, 3, 2), status="APPROVED",
        )
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertEqual(r["deductible_hours"], Decimal("8"))
        self.assertGreater(r["deduction_amount"], Decimal("0"))

    def test_autorisation_a_recuperer_pas_de_deduction(self):
        self._remplir_mars_sauf(date(2026, 3, 2))
        Authorization.objects.create(
            employee=self.employee, date=date(2026, 3, 2), start_time=time(8, 0), end_time=time(16, 0),
            reason="Rendez-vous", status="APPROVED", treatment=PayrollTreatment.RECOVERABLE,
        )
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertEqual(r["deductible_hours"], Decimal("0"))
        self.assertEqual(r["recoverable_hours"], Decimal("8"))

    def test_absence_non_justifiee_deductible_par_defaut(self):
        self._remplir_mars_sauf(date(2026, 3, 2))
        Attendance.objects.create(employee=self.employee, date=date(2026, 3, 2), status=Attendance.Status.ABSENT)
        AbsenceAlert.objects.create(
            employee=self.employee, date=date(2026, 3, 2), kind="ABSENCE", message="x",
            justified=False, treatment=PayrollTreatment.DEDUCTIBLE,
        )
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertEqual(r["deductible_hours"], Decimal("8"))

    def test_absence_justifiee_reclassee_no_deduction_par_rh(self):
        self._remplir_mars_sauf(date(2026, 3, 2))
        Attendance.objects.create(employee=self.employee, date=date(2026, 3, 2), status=Attendance.Status.ABSENT)
        AbsenceAlert.objects.create(
            employee=self.employee, date=date(2026, 3, 2), kind="ABSENCE", message="x",
            justified=True, treatment=PayrollTreatment.NO_DEDUCTION,
        )
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertEqual(r["deductible_hours"], Decimal("0"))
        self.assertEqual(r["no_deduction_hours"], Decimal("8"))

    def test_jour_travaille_jamais_deduit(self):
        self._remplir_mars_sauf(None)
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertEqual(r["deductible_hours"], Decimal("0"))

    def test_montant_deduction_est_decimal(self):
        self._remplir_mars_sauf(None)
        r = compute_absence_deduction(self.employee, 2026, 3, self.hourly_rate)
        self.assertIsInstance(r["deduction_amount"], Decimal)


class BuildPayslipTests(TestCase):
    """Bulletin complet - verifie contre les exemples exacts du cahier des charges."""

    def setUp(self):
        self.employee = make_employee("sami")
        self.salary = Salary.objects.get(employee=self.employee)

    def _remplir_mois_normal(self, year, month):
        import calendar as cal
        for day in range(1, cal.monthrange(year, month)[1] + 1):
            d = date(year, month, day)
            if d.isoweekday() <= 5:
                make_attendance(self.employee, d, (8, 0), (16, 0) if month in (6, 7, 8) else (17, 0))

    def test_exemple_168h_10714_par_heure(self):
        self._remplir_mois_normal(2026, 8)
        payslip = build_payslip(self.salary, month=8, year=2026)
        self.assertEqual(payslip["heures_prevues"], Decimal("168.00"))
        self.assertEqual(payslip["taux_horaire"], Decimal("10.7143"))
        self.assertEqual(payslip["heures_sup"], Decimal("0"))

    def test_exemple_heures_sup_10714_dt(self):
        self._remplir_mois_normal(2026, 8)
        make_attendance(self.employee, date(2026, 8, 29), (8, 0), (16, 0))  # samedi, +8h
        payslip = build_payslip(self.salary, month=8, year=2026)
        self.assertEqual(payslip["heures_sup"], Decimal("8.00"))
        self.assertAlmostEqual(float(payslip["montant_heures_sup"]), 107.14, places=1)
        self.assertAlmostEqual(float(payslip["salaire_brut"]), 1907.14, places=1)

    def test_toutes_les_valeurs_financieres_sont_decimal(self):
        payslip = build_payslip(self.salary, month=8, year=2026)
        for key in ("salaire_base", "salaire_brut", "cnss", "irpp", "css",
                    "retenue_absences", "total_retenues", "salaire_net", "taux_horaire"):
            self.assertIsInstance(payslip[key], Decimal, key)

    def test_bulletin_valide_ne_change_plus_jamais(self):
        """Non-regression cruciale : une fiche deja generee et validee ne
        doit jamais etre recalculee, meme si le contrat change ensuite."""
        self._remplir_mois_normal(2026, 8)
        payslip = build_payslip(self.salary, month=8, year=2026)

        record = PayslipRecord.objects.create(
            employee=self.employee, month=8, year=2026,
            gross_amount=payslip["salaire_brut"], deductions_amount=payslip["total_retenues"],
            net_amount=payslip["salaire_net"], base_salary_used=payslip["salaire_base"],
            status=PayslipRecord.Status.VALIDATED,
        )
        montant_original = record.base_salary_used

        SalaryHistory.objects.create(
            employee=self.employee, previous_amount=Decimal("1800.00"), new_amount=Decimal("5000.00"),
            percentage=Decimal("177.78"), effective_date=date(2026, 2, 1), reason="Test",
        )
        self.salary.refresh_from_db()
        self.assertEqual(self.salary.base_amount, Decimal("5000.00"))

        record.refresh_from_db()
        self.assertEqual(record.base_salary_used, montant_original)
        self.assertEqual(record.base_salary_used, Decimal("1800.00"))


class PayrollPolicySingletonTests(TestCase):
    def test_get_solo_renvoie_toujours_la_meme_ligne(self):
        p1 = PayrollPolicy.get_solo()
        p2 = PayrollPolicy.get_solo()
        self.assertEqual(p1.pk, p2.pk)
        self.assertEqual(PayrollPolicy.objects.count(), 1)

    def test_valeurs_par_defaut_conformes_au_cahier(self):
        p = PayrollPolicy.get_solo()
        self.assertEqual(p.overtime_rate_1, Decimal("25.00"))
        self.assertEqual(p.internal_weekly_overtime_limit_percent, Decimal("15.00"))

from decimal import Decimal

from django.conf import settings as dj_settings
from django.db import models
from django.utils import timezone as django_timezone
from employees.models import Employee


class Salary(models.Model):
    class PaymentMode(models.TextChoices):
        VIREMENT = "VIREMENT", "Virement bancaire"
        CHEQUE = "CHEQUE", "Chèque"
        ESPECES = "ESPECES", "Espèces"

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="salary")
    base_amount = models.DecimalField("Salaire de base", max_digits=10, decimal_places=2)
    bonus = models.DecimalField("Primes", max_digits=10, decimal_places=2, default=0)
    benefits = models.DecimalField("Avantages", max_digits=10, decimal_places=2, default=0)
    presence_bonus = models.DecimalField("Prime de présence", max_digits=10, decimal_places=2, default=0)
    transport_allowance = models.DecimalField("Indemnité de transport", max_digits=10, decimal_places=2, default=0)
    payment_mode = models.CharField(max_length=15, choices=PaymentMode.choices, default=PaymentMode.VIREMENT)
    bank_name = models.CharField("Banque", max_length=120, blank=True)
    currency = models.CharField(max_length=10, default="TND")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Salaire"
        verbose_name_plural = "Salaires"

    @property
    def total(self):
        return self.base_amount + self.bonus + self.benefits + self.presence_bonus + self.transport_allowance

    def __str__(self):
        return f"{self.employee} — {self.total} {self.currency}"


class SalaryHistory(models.Model):
    class IncreaseType(models.TextChoices):
        PERCENTAGE = "PERCENTAGE", "Pourcentage"
        FIXED = "FIXED", "Montant fixe"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_history")
    previous_amount = models.DecimalField(max_digits=10, decimal_places=2)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, help_text="Taux d'augmentation en %")
    increase_type = models.CharField(max_length=12, choices=IncreaseType.choices, default=IncreaseType.PERCENTAGE)
    effective_date = models.DateField("Date d'effet")
    reason = models.CharField("Motif", max_length=255, blank=True)
    decided_by = models.CharField("Décidé par", max_length=150, blank=True)
    approved_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="salary_increases_approved", verbose_name="Approuvé/appliqué par",
    )
    approved_at = models.DateTimeField("Appliqué le", default=django_timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_date"]
        verbose_name = "Historique de rémunération"
        verbose_name_plural = "Historique de rémunération"

    def __str__(self):
        return f"{self.employee} : {self.previous_amount} → {self.new_amount} ({self.effective_date})"


class SalaryIncreaseProposal(models.Model):
    """Workflow réel d'entreprise pour une augmentation de salaire (v13) :

        Manager propose  ->  RH valide (budget/politique salariale)
             ->  Direction approuve  ->  Paie applique

    A chaque étape, l'étape en cours peut aussi rejeter (avec motif),
    ce qui arrête définitivement la proposition et notifie le proposant.
    La Paie n'applique jamais une augmentation qui n'a pas été validée par
    la RH puis approuvée par la Direction — elle ne décide jamais seule."""

    class Status(models.TextChoices):
        PENDING_RH = "PENDING_RH", "En attente de validation RH"
        PENDING_DIRECTION = "PENDING_DIRECTION", "En attente de validation Direction"
        APPROVED = "APPROVED", "Approuvée — en attente d'application par la Paie"
        REJECTED = "REJECTED", "Rejetée"
        APPLIED = "APPLIED", "Appliquée"

    class Motif(models.TextChoices):
        PERFORMANCE = "PERFORMANCE", "Performance / évaluation annuelle"
        ANCIENNETE = "ANCIENNETE", "Ancienneté / expérience"
        PROMOTION = "PROMOTION", "Promotion (changement de poste)"
        RESPONSABILITES = "RESPONSABILITES", "Nouvelles responsabilités"
        COMPETENCES = "COMPETENCES", "Nouvelles compétences / certifications"
        MARCHE = "MARCHE", "Alignement marché"
        AUTRE = "AUTRE", "Autre"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_proposals")

    # Snapshot au moment de la proposition, pour garder une trace fiable
    # même si le salaire de base change entre-temps.
    current_salary = models.DecimalField("Salaire actuel", max_digits=10, decimal_places=2)
    proposed_salary = models.DecimalField("Salaire proposé", max_digits=10, decimal_places=2)
    increase_type = models.CharField(max_length=12, choices=SalaryHistory.IncreaseType.choices, default=SalaryHistory.IncreaseType.PERCENTAGE)
    increase_percentage = models.DecimalField("Taux d'augmentation (%)", max_digits=5, decimal_places=2)

    motif = models.CharField("Motif principal", max_length=20, choices=Motif.choices, default=Motif.PERFORMANCE)
    reason = models.TextField("Justification détaillée", blank=True)
    effective_date = models.DateField("Date d'effet souhaitée")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_RH)

    # Étape 1 : Manager
    proposed_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="salary_proposals_made",
    )
    proposed_at = models.DateTimeField(auto_now_add=True)

    # Étape 2 : RH
    rh_reviewed_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="salary_proposals_rh_reviewed",
    )
    rh_reviewed_at = models.DateTimeField(null=True, blank=True)
    rh_note = models.CharField("Note RH (validation ou motif de rejet)", max_length=255, blank=True)

    # Étape 3 : Direction
    approved_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="salary_proposals_approved",
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField("Motif du rejet par la Direction", max_length=255, blank=True)

    # Étape 4 : Paie
    applied_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="salary_proposals_applied",
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    resulting_history = models.OneToOneField(
        SalaryHistory, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_proposal",
    )

    class Meta:
        ordering = ["-proposed_at"]
        verbose_name = "Proposition d'augmentation"
        verbose_name_plural = "Propositions d'augmentation"

    def __str__(self):
        return f"{self.employee} : {self.current_salary} → {self.proposed_salary} [{self.get_status_display()}]"


class PayslipRecord(models.Model):
    """Trace la génération/validation du bulletin de paie d'un employé pour
    un mois donné (cahier des charges v9 §1 — tableau de bord Paie :
    paie préparée / validée / en attente, masse salariale, retenues)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Préparée"
        VALIDATED = "VALIDATED", "Validée"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payslips")
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    gross_amount = models.DecimalField("Salaire brut", max_digits=10, decimal_places=2, default=0)
    deductions_amount = models.DecimalField("Total retenues", max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField("Net à payer", max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payslips_generated",
    )
    validated_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payslips_validated",
    )
    validated_at = models.DateTimeField(null=True, blank=True)

    # --- Snapshot figé des valeurs utilisées à la génération (jamais recalculé après coup) ---
    base_salary_used = models.DecimalField("Salaire de base utilisé", max_digits=10, decimal_places=2, null=True, blank=True)
    hourly_rate_used = models.DecimalField("Taux horaire utilisé", max_digits=10, decimal_places=4, null=True, blank=True)
    expected_hours_used = models.DecimalField("Heures prévues du mois", max_digits=6, decimal_places=2, null=True, blank=True)
    worked_hours_used = models.DecimalField("Heures travaillées", max_digits=6, decimal_places=2, null=True, blank=True)
    overtime_hours_used = models.DecimalField("Heures supplémentaires", max_digits=6, decimal_places=2, null=True, blank=True)
    overtime_amount_used = models.DecimalField("Montant heures sup.", max_digits=10, decimal_places=2, null=True, blank=True)
    absence_deduction_used = models.DecimalField("Déduction absences", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-year", "-month"]
        unique_together = ("employee", "month", "year")
        verbose_name = "Bulletin de paie"
        verbose_name_plural = "Bulletins de paie"

    def __str__(self):
        return f"{self.employee} — {self.month:02d}/{self.year} [{self.get_status_display()}]"


class PayrollRateSet(models.Model):
    """Barème de cotisations (CNSS, CSS) en vigueur à partir d'une date
    d'effet — donnée MÉTIER de la Paie (Loi de Finances), pas une
    configuration technique système. Seule la Paie peut créer un nouveau
    barème ; RH/Direction/Admin le consultent en lecture seule (voir
    accounts/decorators.strict_role_required).

    Historique conservé : plusieurs barèmes peuvent coexister, chacun
    identifié par sa date d'effet. Le barème applicable à une paie donnée
    est celui dont la date d'effet est la plus récente sans dépasser la
    période de paie (voir `active_for`)."""

    effective_date = models.DateField("Date d'effet", unique=True)
    cnss_rate = models.DecimalField("Taux CNSS salarié (%)", max_digits=6, decimal_places=4)
    css_rate = models.DecimalField("Taux CSS salarié (%)", max_digits=6, decimal_places=4)
    reference = models.CharField("Référence légale / note", max_length=255, blank=True)
    created_by = models.ForeignKey(
        dj_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payroll_rate_sets_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_date"]
        verbose_name = "Barème de paie"
        verbose_name_plural = "Barèmes de paie"

    def __str__(self):
        return f"Barème en vigueur au {self.effective_date}"

    @classmethod
    def active_for(cls, target_date=None):
        """Renvoie le barème applicable à une date donnée (le plus récent
        dont la date d'effet ne dépasse pas `target_date`), ou None si
        aucun barème n'a encore été configuré."""
        target_date = target_date or django_timezone.localdate()
        return cls.objects.filter(effective_date__lte=target_date).order_by("-effective_date").first()



class PayrollRateBracket(models.Model):
    """Une tranche du barème progressif de l'IRPP, rattachée à un
    PayrollRateSet. Laisser `upper_bound` vide pour la dernière tranche
    (plafond illimité)."""

    rate_set = models.ForeignKey(PayrollRateSet, on_delete=models.CASCADE, related_name="brackets")
    upper_bound = models.DecimalField(
        "Plafond annuel (TND)", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Laisser vide pour la dernière tranche (illimité)",
    )
    rate = models.DecimalField("Taux (%)", max_digits=5, decimal_places=2)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = "Tranche IRPP"
        verbose_name_plural = "Tranches IRPP"

    def __str__(self):
        plafond = f"jusqu'à {self.upper_bound} TND" if self.upper_bound is not None else "au-delà"
        return f"{plafond} — {self.rate}%"


class PublicHoliday(models.Model):
    """Jour férié chômé, utilisé pour le calcul des jours ouvrables du mois
    et pour distinguer un travail de jour férié (§8) d'un jour de repos normal."""

    date = models.DateField("Date", unique=True)
    label = models.CharField("Libellé", max_length=150)

    class Meta:
        ordering = ["date"]
        verbose_name = "Jour férié"
        verbose_name_plural = "Jours fériés"

    def __str__(self):
        return f"{self.label} ({self.date})"


class PayrollPolicy(models.Model):
    """Politique de paie de l'entreprise (ligne unique — le projet est mono-entreprise,
    cf. `settings.COMPANY_INFO`). Centralise tous les réglages configurables du calcul
    des heures supplémentaires et du taux horaire, pour éviter les valeurs codées en dur."""

    class HourlyRateMethod(models.TextChoices):
        PRORATA_HEURES_PREVUES = "PRORATA_HEURES_PREVUES", "Salaire mensuel / heures prévues du mois"
        FORFAIT_MENSUEL_FIXE = "FORFAIT_MENSUEL_FIXE", "Salaire mensuel / nombre fixe d'heures mensuelles"
        PERSONNALISEE = "PERSONNALISEE", "Méthode personnalisée"

    class RestDayPolicy(models.TextChoices):
        WEEKLY_THRESHOLD = "WEEKLY_THRESHOLD", "Compte dans le total hebdomadaire normal jusqu'au seuil"
        SPECIAL_RATE = "SPECIAL_RATE", "Catégorie et majoration spéciales dès la première heure"
        TIME_OFF_IN_LIEU = "TIME_OFF_IN_LIEU", "Compensé par du repos récupérable (via Authorization)"

    # --- Taux horaire ---
    hourly_rate_method = models.CharField(
        "Méthode de calcul du taux horaire", max_length=30,
        choices=HourlyRateMethod.choices, default=HourlyRateMethod.PRORATA_HEURES_PREVUES,
    )
    fixed_monthly_hours = models.DecimalField(
        "Heures mensuelles fixes (si méthode forfaitaire)", max_digits=6, decimal_places=2,
        default=Decimal("173.33"), help_text="Utilisé seulement si la méthode est « Forfait mensuel fixe ».",
    )

    # --- Heures supplémentaires ---
    overtime_rate_1 = models.DecimalField(
        "Majoration heures sup. taux 1 (%)", max_digits=5, decimal_places=2, default=Decimal("25.00"),
    )
    overtime_tier2_threshold_hours = models.DecimalField(
        "Seuil hebdo déclenchant le taux 2 (h)", max_digits=5, decimal_places=2, default=Decimal("48.00"),
        help_text="Au-delà de ce nombre d'heures dans la semaine, le taux 2 s'applique.",
    )
    overtime_rate_2 = models.DecimalField(
        "Majoration heures sup. taux 2 (%)", max_digits=5, decimal_places=2, default=Decimal("50.00"),
    )
    holiday_rate = models.DecimalField(
        "Majoration jour férié travaillé (%)", max_digits=5, decimal_places=2, default=Decimal("100.00"),
    )

    # --- Jour de repos (ex : samedi si non travaillé au contrat) ---
    rest_day_policy = models.CharField(
        "Politique de travail un jour de repos", max_length=20,
        choices=RestDayPolicy.choices, default=RestDayPolicy.WEEKLY_THRESHOLD,
    )
    rest_day_rate = models.DecimalField(
        "Majoration jour de repos (%) (si politique = Catégorie spéciale)",
        max_digits=5, decimal_places=2, default=Decimal("50.00"),
    )

    # --- Limite interne (distincte d'une éventuelle limite légale) ---
    internal_weekly_overtime_limit_percent = models.DecimalField(
        "Limite interne hebdomadaire d'heures sup. (%)", max_digits=5, decimal_places=2, default=Decimal("15.00"),
        help_text="Ex : 15% de 40h/semaine = 6h. Purement interne à l'entreprise, ne remplace aucune limite légale.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Politique de paie"
        verbose_name_plural = "Politique de paie"

    def __str__(self):
        return "Politique de paie de l'entreprise"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton : une seule ligne, mono-entreprise
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # empêche la suppression accidentelle du singleton

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
from datetime import datetime

from django.db import models

from employees.models import Employee
from .workflow import WorkflowMixin


class PayrollTreatment(models.TextChoices):
    """Impact d'une absence/autorisation sur le calcul de la paie (§7).

    Ce choix est partagé entre LeaveType, Authorization et AbsenceAlert pour
    que le module de paie centralise une seule et même logique de décision,
    sans dupliquer l'information à plusieurs endroits.
    """
    NO_DEDUCTION = "NO_DEDUCTION", "Aucune déduction (payé normalement)"
    DEDUCTIBLE = "DEDUCTIBLE", "Déductible du salaire"
    RECOVERABLE = "RECOVERABLE", "À récupérer (ni payé, ni déduit)"
    LEGAL_INDEMNITY = "LEGAL_INDEMNITY", "Indemnité légale (maladie/maternité — calcul non standardisé, à configurer)"


class LeaveType(models.Model):
    name = models.CharField("Type de congé", max_length=80)
    paid = models.BooleanField(
        "Congé payé", default=True,
        help_text="Champ historique conservé pour compatibilité ; utilisez « Traitement paie » ci-dessous.",
    )
    treatment = models.CharField(
        "Traitement paie", max_length=15, choices=PayrollTreatment.choices,
        default=PayrollTreatment.NO_DEDUCTION, blank=True,
        help_text="Détermine si ce type de congé donne lieu à une déduction sur la paie.",
    )
    reduces_annual_balance = models.BooleanField(
        "Réduit le solde de congé annuel", default=False,
        help_text=(
            "Indépendant du traitement paie ci-dessus : un congé payé ne réduit pas "
            "forcément le solde annuel (ex. maladie, formation, maternité). "
            "À cocher explicitement pour le congé annuel."
        ),
    )

    def __str__(self):
        return self.name


class LeaveRequest(WorkflowMixin, models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField("Date de début")
    end_date = models.DateField("Date de fin")
    reason = models.TextField("Motif / commentaire", blank=True)
    attachment = models.FileField("Justificatif", upload_to="leaves/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Demande de congé"
        verbose_name_plural = "Demandes de congé"

    def __str__(self):
        return f"{self.employee} — {self.start_date} → {self.end_date} ({self.get_status_display()})"

    @property
    def nb_days(self):
        return (self.end_date - self.start_date).days + 1

    def covers_date(self, a_date):
        return self.start_date <= a_date <= self.end_date
    
    @property
    def is_expired(self):
        """La date de DÉBUT de ce congé est passée sans décision : plus
        personne ne peut l'accepter ni le refuser (n'a plus de sens
        rétroactivement, même si la période demandée n'est pas terminée)."""
        from django.utils import timezone
        return self.start_date < timezone.localdate()


class Authorization(WorkflowMixin, models.Model):
    """Autorisation d'absence courte (ex : rendez-vous, sortie de 2h...)."""

    class Kind(models.TextChoices):
        SORTIE_EXCEPTIONNELLE = "SORTIE_EXCEPTIONNELLE", "Sortie exceptionnelle"
        RETARD_EXCEPTIONNEL = "RETARD_EXCEPTIONNEL", "Retard exceptionnel"
        ABSENCE_QUELQUES_HEURES = "ABSENCE_QUELQUES_HEURES", "Absence de quelques heures"
        RENDEZ_VOUS = "RENDEZ_VOUS", "Rendez-vous"
        PERMISSION_PERSONNELLE = "PERMISSION_PERSONNELLE", "Permission personnelle"
        AUTRE = "AUTRE", "Autre"

    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE, related_name="authorizations")
    kind = models.CharField("Type d'autorisation", max_length=30, choices=Kind.choices, default=Kind.AUTRE)
    date = models.DateField("Date")
    start_time = models.TimeField("Heure de début")
    end_time = models.TimeField("Heure de fin")
    reason = models.CharField("Motif", max_length=255)
    treatment = models.CharField(
        "Traitement paie", max_length=15, choices=PayrollTreatment.choices,
        default=PayrollTreatment.NO_DEDUCTION,
        help_text="Impact de cette autorisation sur la paie (ex : heures à récupérer).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Autorisation d'absence"
        verbose_name_plural = "Autorisations d'absence"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.employee} - {self.date} ({self.start_time}-{self.end_time}) [{self.get_status_display()}]"

    @property
    def duration_hours(self):
        from decimal import Decimal
        delta = datetime.combine(self.date, self.end_time) - datetime.combine(self.date, self.start_time)
        return (Decimal(delta.total_seconds()) / Decimal(3600)).quantize(Decimal("0.01"))
    
    @property
    def is_expired(self):
        """La date de cette autorisation est passée : plus personne ne peut
        l'accepter ni le refuser (n'a plus de sens rétroactivement)."""
        from django.utils import timezone
        return self.date < timezone.localdate()

class LeaveBalanceTransaction(models.Model):
    """Traçabilité minimale de toute variation du solde de congé annuel
    (§5) : congé annuel pris, conversion d'heures d'autorisation, cumul
    mensuel automatique, ou correction manuelle. Aucun mécanisme similaire
    n'existait dans le projet — modèle volontairement simple (pas de
    sur-ingénierie), en lecture seule une fois créé."""

    class Source(models.TextChoices):
        LEAVE_REQUEST = "LEAVE_REQUEST", "Congé annuel pris"
        AUTHORIZATION = "AUTHORIZATION", "Conversion d'heures d'autorisation"
        ACCRUAL = "ACCRUAL", "Acquisition mensuelle automatique"
        CORRECTION = "CORRECTION", "Correction manuelle"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_balance_transactions")
    date = models.DateField(auto_now_add=True)
    source = models.CharField(max_length=20, choices=Source.choices)
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    authorization = models.ForeignKey(Authorization, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    hours_consumed = models.DecimalField("Heures utilisées", max_digits=6, decimal_places=2, default=0)
    days_converted = models.DecimalField("Jours convertis/consommés", max_digits=5, decimal_places=2, default=0)
    balance_before = models.DecimalField("Solde avant", max_digits=6, decimal_places=2)
    balance_after = models.DecimalField("Solde après", max_digits=6, decimal_places=2)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Mouvement de solde de congé"
        verbose_name_plural = "Mouvements de solde de congé"

    def __str__(self):
        return f"{self.employee} — {self.get_source_display()} — {self.balance_before} → {self.balance_after}"
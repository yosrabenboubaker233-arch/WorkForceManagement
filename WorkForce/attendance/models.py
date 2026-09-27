from datetime import datetime, timedelta, time

from django.db import models
from django.conf import settings
from django.utils import timezone

import secrets

from employees.models import Employee
from leaves.models import PayrollTreatment


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Présent"
        LATE = "LATE", "En retard"
        ABSENT = "ABSENT", "Absent"
        ON_LEAVE = "ON_LEAVE", "En congé"
        AUTHORIZED = "AUTHORIZED", "Absence autorisée" 

    class Lieu(models.TextChoices):
        BUREAU = "bureau", "Bureau"
        TELETRAVAIL = "teletravail", "Télétravail"

    employee = models.ForeignKey("employees.Employee", on_delete=models.CASCADE)
    date = models.DateField()
    check_in = models.TimeField(null=True, blank=True)
    check_out = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ABSENT)
    lieu = models.CharField(max_length=15, choices=Lieu.choices, null=True, blank=True)

    # Pause déclarée (télétravail uniquement — cahier des charges v3 §7 :
    # "Télétravail : pointage déclaratif... peut prendre pause"). Horodatée
    # par le serveur, jamais par le navigateur, comme le reste du pointage.
    pause_start = models.TimeField("Début de pause", null=True, blank=True)
    pause_end = models.TimeField("Fin de pause", null=True, blank=True)

    # Rapport de travail (télétravail uniquement) : l'employé doit le
    # déposer AVANT de pouvoir pointer son départ. Envoyé automatiquement
    # à son manager (notification + email) une fois le départ pointé.
    rapport_teletravail = models.FileField(
        "Rapport de travail (télétravail)", upload_to="rapports_teletravail/", null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="unique_attendance_par_employe_et_jour"),
        ]

    # -----------------------------------------------------------------
    # Horaires et pause : calculés (rien n'est stocké en base pour ça),
    # dérivés uniquement de la date du pointage.
    # -----------------------------------------------------------------

    @property
    def is_summer_schedule(self):
        """Horaire d'été : juillet et août."""
        return self.date.month in (7, 8)

    @property
    def schedule_name(self):
        """Nom de l'horaire appliqué."""
        return "Été" if self.is_summer_schedule else "Normal"

    @property
    def expected_start(self):
        """Heure de début prévue."""
        return time(8, 0) if self.is_summer_schedule else time(9, 0)

    @property
    def expected_end(self):
        """Heure de fin prévue."""
        return time(15, 0) if self.is_summer_schedule else time(17, 0)

    @property
    def pause_duration(self):
        """
        Durée de pause déduite du temps de présence :
        - Télétravail avec pause déclarée (pause_start/pause_end renseignés) :
          la durée réelle de cette pause est utilisée.
        - Sinon (bureau, ou télétravail sans pause déclarée) : pause fixe
          selon l'horaire en vigueur (1h normal, 0h en horaire d'été).
        """
        if self.lieu == self.Lieu.TELETRAVAIL and self.pause_start and self.pause_end:
            debut = datetime.combine(self.date, self.pause_start)
            fin = datetime.combine(self.date, self.pause_end)
            duree = fin - debut
            return duree if duree.total_seconds() > 0 else timedelta(0)

        return timedelta(minutes=0) if self.is_summer_schedule else timedelta(hours=1)

    @property
    def worked_duration(self):
        """
        Temps réellement travaillé = (départ - arrivée) - pause fixe.
        Renvoie None tant que l'arrivée ET le départ ne sont pas tous les
        deux pointés (on ne peut pas calculer une durée incomplète).
        """
        if not self.check_in or not self.check_out:
            return None

        debut = datetime.combine(self.date, self.check_in)
        fin = datetime.combine(self.date, self.check_out)
        duree = fin - debut

        # Déduction de la pause fixe selon l'horaire (normal/été)
        duree -= self.pause_duration

        # Protection : jamais de durée négative (ex: pause > temps réellement passé)
        if duree.total_seconds() < 0:
            return timedelta(0)

        return duree

    @property
    def worked_hours(self):
        """Temps travaillé affiché au format HH:MM, ou '--' si incomplet."""
        duree = self.worked_duration
        if duree is None:
            return "--"

        total_minutes = int(duree.total_seconds() // 60)
        heures, minutes = divmod(total_minutes, 60)
        return f"{heures:02d}:{minutes:02d}"

    @property
    def worked_hours_decimal(self):
        """Temps travaillé en heures (Decimal), pour les calculs de paie. 0 si incomplet."""
        from decimal import Decimal
        duree = self.worked_duration
        if duree is None:
            return Decimal("0")
        return (Decimal(duree.total_seconds()) / Decimal(3600)).quantize(Decimal("0.01"))


class AbsenceAlert(models.Model):
    """Alerte générée automatiquement à propos du pointage d'un employé :
    - ABSENCE  : absent en fin de journée, sans congé ni autorisation (detect_absences, fin de journée)
    - LATE     : arrivé après l'heure prévue + tolérance (check_workday_alerts, ~1h après le début)
    - MISSING_CHECKIN : n'a toujours pas pointé 1h après le début de journée,
      alors qu'il n'a ni congé ni autorisation pour cette période (check_workday_alerts)."""

    class Kind(models.TextChoices):
        ABSENCE = "ABSENCE", "Absence"
        LATE = "LATE", "Retard"
        MISSING_CHECKIN = "MISSING_CHECKIN", "Pointage manquant"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="absence_alerts")
    date = models.DateField()
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ABSENCE)
    leave_request = models.ForeignKey(
        "leaves.LeaveRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts"
    )
    message = models.TextField()
    resolved = models.BooleanField(default=False)
    justified = models.BooleanField(
        "Absence justifiée", default=False,
        help_text="Coché par la RH une fois un justificatif accepté pour cette absence.",
    )
    treatment = models.CharField(
        "Traitement paie", max_length=15, choices=PayrollTreatment.choices,
        default=PayrollTreatment.DEDUCTIBLE,
        help_text="Impact sur la paie de cette absence non couverte par un congé ou une autorisation.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Alerte d'absence"
        verbose_name_plural = "Alertes d'absence"
        constraints = [
            models.UniqueConstraint(fields=["employee", "date", "kind"], name="unique_alert_per_employee_date_kind")
        ]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.employee} — {self.date}"


class PosteAutorise(models.Model):
    """
    PC de bureau autorisé pour effectuer le pointage.

    La vérification repose uniquement sur le cookie_secret.
    Chaque navigateur enregistré correspond à un poste physique autorisé.
    """
    nom = models.CharField(max_length=50, help_text="Ex: PC-Accueil, PC-Bureau-1...")
    cookie_secret = models.CharField(max_length=64, unique=True, editable=False)
    actif = models.BooleanField(default=True, help_text="Désactiver ici révoque immédiatement ce poste.")
    derniere_utilisation = models.DateTimeField(null=True, blank=True)
    ip_derniere_connexion = models.GenericIPAddressField(
        null=True, blank=True, help_text="Informatif uniquement (log), ne sert plus à la vérification."
    )
    date_enregistrement = models.DateTimeField(default=timezone.now)

    def save(self, *args, **kwargs):
        if not self.cookie_secret:
            self.cookie_secret = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom
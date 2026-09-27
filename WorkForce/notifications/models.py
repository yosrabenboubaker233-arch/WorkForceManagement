from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Category(models.TextChoices):
        LEAVE_NEW = "LEAVE_NEW", "Nouvelle demande de congé"
        LEAVE_APPROVED = "LEAVE_APPROVED", "Congé accepté"
        LEAVE_REJECTED = "LEAVE_REJECTED", "Congé refusé"
        AUTH_NEW = "AUTH_NEW", "Nouvelle demande d'autorisation"
        AUTH_APPROVED = "AUTH_APPROVED", "Autorisation acceptée"
        AUTH_REJECTED = "AUTH_REJECTED", "Autorisation refusée"
        ABSENCE_ALERT = "ABSENCE_ALERT", "Alerte d'absence"
        LATE_ALERT = "LATE_ALERT", "Alerte de retard"
        CHECKIN_MISSED = "CHECKIN_MISSED", "Pointage manquant"
        SALARY_UPDATE = "SALARY_UPDATE", "Mise à jour salariale"
        SALARY_INCREASE_REQUEST = "SALARY_INCREASE_REQUEST", "Demande d'augmentation"
        SALARY_INCREASE_DECIDED = "SALARY_INCREASE_DECIDED", "Décision sur une augmentation"
        CONTRACT_UPDATE = "CONTRACT_UPDATE", "Mise à jour de contrat"
        TASK_ASSIGNED = "TASK_ASSIGNED", "Nouvelle tâche assignée"
        TASK_COMMENT = "TASK_COMMENT", "Commentaire sur une tâche"
        TASK_STATUS = "TASK_STATUS", "Statut de tâche mis à jour"
        OTHER = "OTHER", "Autre"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.OTHER)
    title = models.CharField(max_length=150)
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"{self.title} → {self.recipient}"

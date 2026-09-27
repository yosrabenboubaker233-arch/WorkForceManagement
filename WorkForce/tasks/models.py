from django.conf import settings
from django.db import models

from employees.models import Employee


class Task(models.Model):
    """Tâche assignée par un manager à un membre de son équipe
    (cahier des charges v3 §8)."""

    class Status(models.TextChoices):
        TODO = "TODO", "À faire"
        IN_PROGRESS = "IN_PROGRESS", "En cours"
        DONE = "DONE", "Terminée"

    title = models.CharField("Titre", max_length=150)
    description = models.TextField("Description", blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="tasks")
    assigned_by = models.ForeignKey(
        Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks_assigned"
    )
    due_date = models.DateField("Échéance", null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.TODO)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Tâche"
        verbose_name_plural = "Tâches"

    def __str__(self):
        return f"{self.title} — {self.employee} ({self.get_status_display()})"

    @property
    def is_overdue(self):
        from django.utils import timezone
        return bool(self.due_date and self.due_date < timezone.localdate() and self.status != self.Status.DONE)


class TaskComment(models.Model):
    """Fil de discussion (type chat) attaché à une tâche : l'employé et
    le manager peuvent tous deux commenter, et l'employé peut y joindre
    un rapport (document/fichier) sur l'avancement de la tâche."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments")
    message = models.TextField("Message", blank=True)
    report = models.FileField("Rapport (fichier)", upload_to="task_reports/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Commentaire de tâche"
        verbose_name_plural = "Commentaires de tâche"

    def __str__(self):
        return f"{self.author} sur « {self.task.title} »"

    @property
    def report_name(self):
        return self.report.name.rsplit("/", 1)[-1] if self.report else ""